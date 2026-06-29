"""
pipeline_multimodal.py
======================
Trébol Motors — Embeddings multimodales con CLIP
Autores: Juan Esteban Jiménez Vargas - Santiago Pérez Cardona

Genera los embeddings de la capa multimodal del sistema:
  1. vec_imagen_vehiculo: embeddings CLIP de las IMÁGENES
     (modelo clip-ViT-B-32, 512 dim — igual al diseño de la 1ª entrega)
  2. vec_imagen_vehiculo_descripcion: embeddings CLIP de las ETIQUETAS
     (modelo clip-ViT-B-32-multilingual-v1, 512 dim — encoder de texto
      multilingüe alineado al espacio CLIP, necesario para que las
      consultas en español funcionen contra imágenes)

Ambos modelos producen vectores EN EL MISMO ESPACIO de 512 dim,
lo que habilita las comparaciones cruzadas:
  texto → imagen   (consulta en español contra fotos del catálogo)
  imagen → texto   (foto del cliente contra etiquetas del catálogo)
  imagen → imagen  (foto del cliente contra fotos del catálogo)

Ejecutar DESPUÉS de aplicar 04_multimodal.sql en Supabase.

Dependencias adicionales: pip install pillow
"""

import io
import os
import time
import urllib.error
import urllib.request

# Windows sin Modo Desarrollador no permite symlinks: HuggingFace
# debe copiar archivos en lugar de enlazarlos (debe ir ANTES de
# importar sentence_transformers)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from PIL import Image
from sentence_transformers import SentenceTransformer

from db_conexion import conectar

# ============================================================
# CONEXIÓN Y MODELOS
# ============================================================
print("Conectando a Supabase...")
conn = conectar()
cursor = conn.cursor()
print("[OK] Conectado")

print("Cargando modelo CLIP de imagen (clip-ViT-B-32)...")
model_imagen = SentenceTransformer("clip-ViT-B-32")
print("[OK] Modelo de imagen cargado")

print("Cargando modelo CLIP de texto multilingue (clip-ViT-B-32-multilingual-v1)...")
model_texto = SentenceTransformer("sentence-transformers/clip-ViT-B-32-multilingual-v1")
print("[OK] Modelo de texto cargado")


def descargar_imagen(url: str) -> Image.Image:
    """Descarga una imagen de Wikimedia Commons (exige User-Agent).
    Reintenta con espera larga si Wikimedia limita las peticiones (429)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "TrebolMotorsBot/1.0 (proyecto academico)"}
    )
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            return Image.open(io.BytesIO(data)).convert("RGB")
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento < 2:
                espera = 45 * (intento + 1)
                print(f"    (rate limit 429 — esperando {espera}s antes de reintentar...)")
                time.sleep(espera)
            else:
                raise


# ============================================================
# PROCESAR LAS IMÁGENES DEL CATÁLOGO
# ============================================================
# REANUDABLE: solo procesa las imágenes que aún no tienen embedding
# (permite re-ejecutar tras un corte de rate limit sin repetir trabajo)
cursor.execute("""
    SELECT iv.id_imagen, iv.id_vehiculo, iv.url, iv.descripcion
    FROM imagen_vehiculo iv
    LEFT JOIN vec_imagen_vehiculo viv ON viv.id_imagen = iv.id_imagen
    WHERE viv.id_imagen IS NULL
    ORDER BY iv.id_imagen;
""")
imagenes = cursor.fetchall()
cursor.execute("SELECT COUNT(*) FROM imagen_vehiculo;")
total_catalogo = cursor.fetchone()[0]
print(f"\n[OK] {total_catalogo} imágenes en catálogo, "
      f"{len(imagenes)} pendientes de vectorizar")

procesadas = 0
for id_imagen, id_vehiculo, url, descripcion in imagenes:
    try:
        # 1. Embedding CLIP de la IMAGEN (512 dim)
        img = descargar_imagen(url)
        emb_imagen = model_imagen.encode(img).tolist()

        cursor.execute("""
            INSERT INTO vec_imagen_vehiculo (id_imagen, id_vehiculo, embedding)
            VALUES (%s, %s, %s);
        """, (id_imagen, id_vehiculo, emb_imagen))

        # 2. Embedding CLIP multilingüe de la ETIQUETA (512 dim)
        emb_etiqueta = model_texto.encode(descripcion).tolist()

        cursor.execute("""
            INSERT INTO vec_imagen_vehiculo_descripcion (id_imagen, chunk_texto, embedding)
            VALUES (%s, %s, %s)
            ON CONFLICT (id_imagen) DO UPDATE
                SET chunk_texto = EXCLUDED.chunk_texto,
                    embedding = EXCLUDED.embedding;
        """, (id_imagen, descripcion, emb_etiqueta))

        conn.commit()
        procesadas += 1
        print(f"  [{procesadas:2d}/{len(imagenes)}] imagen {id_imagen} "
              f"(vehículo {id_vehiculo}): OK — '{descripcion[:50]}'")

        # Pausa de cortesía para no disparar el rate limit de Wikimedia
        time.sleep(4)

    except Exception as e:
        conn.rollback()
        print(f"  [ERROR] imagen {id_imagen}: {e}")

print(f"\n[OK] PROCESO COMPLETADO: {procesadas}/{len(imagenes)} imágenes vectorizadas")
print("  - vec_imagen_vehiculo: embeddings CLIP de las fotos")
print("  - vec_imagen_vehiculo_descripcion: embeddings CLIP de las etiquetas")
print("\n  Ejecuta demo_consultas.py para ver las búsquedas multimodales.")

cursor.close()
conn.close()
