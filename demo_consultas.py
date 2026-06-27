"""
demo_consultas.py
=================
Trébol Motors — DEMO DE SUSTENTACIÓN
Autores: Juan Esteban Jiménez Vargas - Santiago Pérez Cardona

Demuestra en vivo las 7 capacidades del sistema:

  1. Consulta SQL común (relacional pura)
  2. Consulta texto a texto (vectorial pura, bge-m3)
  3. Consulta HÍBRIDA (SQL + vectorial combinadas)
  4. Consulta texto a imagen (CLIP multilingüe)
  5. Consulta imagen a texto / imagen a imagen (CLIP)
  6. Comparación de las 3 estrategias de chunking
  7. Explicación: qué es una consulta híbrida

Uso:
    python demo_consultas.py        → ejecuta todas las secciones
    python demo_consultas.py 3      → ejecuta solo la sección 3

Requiere haber ejecutado antes:
    pipeline_embeddings.py  (chunks + embeddings de texto)
    04_multimodal.sql + pipeline_multimodal.py  (imágenes CLIP)
"""

import io
import json
import os
import sys
import urllib.request

# Windows sin Modo Desarrollador: HuggingFace debe copiar en lugar
# de crear symlinks (debe configurarse antes de cargar los modelos)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from db_conexion import conectar

# Los modelos se cargan bajo demanda (lazy) para que las secciones
# puramente SQL no tengan que esperar la carga de los modelos.
_modelos = {}

def modelo_texto():
    """bge-m3 (1024 dim) — embeddings de texto en español."""
    if "bge" not in _modelos:
        from sentence_transformers import SentenceTransformer
        print("  (cargando BAAI/bge-m3...)")
        _modelos["bge"] = SentenceTransformer("BAAI/bge-m3")
    return _modelos["bge"]

def modelo_clip_texto():
    """CLIP texto multilingüe (512 dim) — consultas en español contra imágenes."""
    if "clip_txt" not in _modelos:
        from sentence_transformers import SentenceTransformer
        print("  (cargando clip-ViT-B-32-multilingual-v1...)")
        _modelos["clip_txt"] = SentenceTransformer(
            "sentence-transformers/clip-ViT-B-32-multilingual-v1")
    return _modelos["clip_txt"]

def modelo_clip_imagen():
    """CLIP imagen (512 dim) — embeddings de fotos."""
    if "clip_img" not in _modelos:
        from sentence_transformers import SentenceTransformer
        print("  (cargando clip-ViT-B-32...)")
        _modelos["clip_img"] = SentenceTransformer("clip-ViT-B-32")
    return _modelos["clip_img"]


def titulo(n, texto):
    print("\n" + "=" * 72)
    print(f"  SECCIÓN {n}: {texto}")
    print("=" * 72)


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 1 — CONSULTA SQL COMÚN
# ════════════════════════════════════════════════════════════════════
def seccion_1(cursor):
    titulo(1, "CONSULTA SQL COMÚN (relacional pura)")
    print("""
Pregunta de negocio: "SUVs disponibles de menos de 35 millones,
ordenadas por kilometraje"

Esta consulta usa SOLO la capa relacional: filtros exactos sobre
columnas estructuradas con índices B-tree. SQL la resuelve
perfectamente — no necesita embeddings.

SQL ejecutado:
    SELECT marca, linea, anio, kilometraje, precio_venta
    FROM vehiculo
    WHERE carroceria = 'suv'
      AND estado_vehiculo = 'disponible'
      AND precio_venta < 35000000
    ORDER BY kilometraje ASC
    LIMIT 5;
""")
    cursor.execute("""
        SELECT marca, linea, anio, kilometraje, precio_venta
        FROM vehiculo
        WHERE carroceria = 'suv'
          AND estado_vehiculo = 'disponible'
          AND precio_venta < 35000000
        ORDER BY kilometraje ASC
        LIMIT 5;
    """)
    print(f"{'Vehículo':<30} {'Año':>5} {'Km':>10} {'Precio':>15}")
    print("-" * 64)
    for marca, linea, anio, km, precio in cursor.fetchall():
        print(f"{marca + ' ' + linea:<30} {anio:>5} {km:>10,} {f'${precio:,.0f}':>15}")


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 2 — TEXTO A TEXTO (vectorial pura)
# ════════════════════════════════════════════════════════════════════
def seccion_2(cursor):
    titulo(2, "CONSULTA TEXTO A TEXTO (búsqueda vectorial semántica)")
    consulta = "quiero un carro confiable para mi familia que gaste poquita gasolina"
    print(f"""
Consulta del cliente (lenguaje natural, SIN filtros estructurados):
    "{consulta}"

Ningún WHERE de SQL puede resolver "confiable para mi familia" o
"gaste poquita gasolina" — no son columnas. El embedding de la
consulta (bge-m3, 1024 dim) se compara por SIMILITUD COSENO contra
los embeddings de las fichas de los vehículos usando el operador
<=> de pgvector con índice HNSW.

SQL ejecutado:
    SELECT v.marca, v.linea, cre.contenido_texto,
           1 - (cre.vector_embedding <=> %s::vector) AS similitud
    FROM chunk_resultado_experimento cre
    JOIN vehiculo v USING (id_vehiculo)
    WHERE cre.id_experimento = 3        -- estrategia semantic
    ORDER BY cre.vector_embedding <=> %s::vector
    LIMIT 5;
""")
    vec = json.dumps(modelo_texto().encode(consulta).tolist())
    cursor.execute("""
        SELECT v.marca, v.linea, v.anio, v.combustible,
               1 - (cre.vector_embedding <=> %s::vector) AS similitud
        FROM chunk_resultado_experimento cre
        JOIN vehiculo v USING (id_vehiculo)
        WHERE cre.id_experimento = 3
        ORDER BY cre.vector_embedding <=> %s::vector
        LIMIT 5;
    """, (vec, vec))
    print(f"{'Vehículo':<28} {'Año':>5} {'Combustible':>12} {'Similitud':>10}")
    print("-" * 58)
    for marca, linea, anio, comb, sim in cursor.fetchall():
        print(f"{marca + ' ' + linea:<28} {anio:>5} {comb:>12} {sim:>10.4f}")


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 3 — CONSULTA HÍBRIDA (SQL + vectorial)
# ════════════════════════════════════════════════════════════════════
def seccion_3(cursor):
    titulo(3, "CONSULTA HÍBRIDA (relacional + vectorial en una sola consulta)")
    consulta = "camioneta comoda y segura para viajar por carretera"
    print(f"""
Consulta del cliente:
    "{consulta}, que cueste menos de 35 millones y tenga
     menos de 60.000 km"

La parte SEMÁNTICA ("cómoda y segura para viajar") la resuelve el
embedding; la parte ESTRUCTURADA (precio < 35M, km < 60.000,
disponible) la resuelven los filtros SQL exactos. UNA SOLA consulta
combina ambas capas: el WHERE poda con índices B-tree y el ORDER BY
vectorial ordena por relevancia semántica con el índice HNSW.

SQL ejecutado:
    SELECT v.marca, v.linea, v.precio_venta, v.kilometraje,
           1 - (cre.vector_embedding <=> %s::vector) AS similitud
    FROM chunk_resultado_experimento cre
    JOIN vehiculo v USING (id_vehiculo)
    WHERE cre.id_experimento = 3
      AND v.estado_vehiculo = 'disponible'   ← filtro SQL
      AND v.precio_venta < 35000000          ← filtro SQL
      AND v.kilometraje < 60000              ← filtro SQL
    ORDER BY cre.vector_embedding <=> %s::vector   ← ranking vectorial
    LIMIT 5;
""")
    vec = json.dumps(modelo_texto().encode(consulta).tolist())
    cursor.execute("""
        SELECT v.marca, v.linea, v.anio, v.precio_venta, v.kilometraje,
               1 - (cre.vector_embedding <=> %s::vector) AS similitud
        FROM chunk_resultado_experimento cre
        JOIN vehiculo v USING (id_vehiculo)
        WHERE cre.id_experimento = 3
          AND v.estado_vehiculo = 'disponible'
          AND v.precio_venta < 35000000
          AND v.kilometraje < 60000
        ORDER BY cre.vector_embedding <=> %s::vector
        LIMIT 5;
    """, (vec, vec))
    print(f"{'Vehículo':<26} {'Año':>5} {'Precio':>14} {'Km':>9} {'Similitud':>10}")
    print("-" * 68)
    for marca, linea, anio, precio, km, sim in cursor.fetchall():
        print(f"{marca + ' ' + linea:<26} {anio:>5} {f'${precio:,.0f}':>14} "
              f"{km:>9,} {sim:>10.4f}")


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 4 — TEXTO A IMAGEN (CLIP)
# ════════════════════════════════════════════════════════════════════
def seccion_4(cursor):
    titulo(4, "CONSULTA TEXTO A IMAGEN (CLIP multimodal)")
    consulta = "una camioneta SUV de color rojo"
    print(f"""
Consulta del cliente (describe lo que quiere VER):
    "{consulta}"

El texto se embebe con el encoder CLIP multilingüe (512 dim) y se
compara contra los embeddings CLIP de las FOTOS del catálogo
(vec_imagen_vehiculo). Texto e imagen viven en el MISMO espacio
vectorial — por eso la comparación coseno entre ellos tiene sentido.
El color "rojo" no está en ninguna columna SQL de la imagen: está
EN LOS PIXELES, y CLIP lo captura.

SQL ejecutado:
    SELECT v.marca, v.linea, iv.url,
           1 - (viv.embedding <=> %s::vector) AS similitud
    FROM vec_imagen_vehiculo viv
    JOIN imagen_vehiculo iv USING (id_imagen)
    JOIN vehiculo v ON v.id_vehiculo = viv.id_vehiculo
    ORDER BY viv.embedding <=> %s::vector
    LIMIT 3;
""")
    vec = json.dumps(modelo_clip_texto().encode(consulta).tolist())
    cursor.execute("""
        SELECT v.marca, v.linea, iv.descripcion, iv.url,
               1 - (viv.embedding <=> %s::vector) AS similitud
        FROM vec_imagen_vehiculo viv
        JOIN imagen_vehiculo iv USING (id_imagen)
        JOIN vehiculo v ON v.id_vehiculo = viv.id_vehiculo
        ORDER BY viv.embedding <=> %s::vector
        LIMIT 3;
    """, (vec, vec))
    for i, (marca, linea, desc, url, sim) in enumerate(cursor.fetchall(), 1):
        print(f"  {i}. {marca} {linea}  (similitud {sim:.4f})")
        print(f"     etiqueta: {desc}")
        print(f"     foto: {url[:80]}...")
    print("""
Nota sobre la escala: en CLIP las similitudes TEXTO→IMAGEN rondan
0.20-0.30 incluso para emparejamientos correctos, porque texto e
imagen ocupan regiones distintas del espacio compartido (la
"brecha de modalidad"). Lo relevante no es el valor absoluto sino
el ORDEN del ranking: el top-1 es la foto que mejor corresponde a
la descripción. Compárese con imagen→imagen (sección 5b), donde
las similitudes correctas superan 0.75 por ser la misma modalidad.""")


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 5 — IMAGEN A TEXTO / IMAGEN A IMAGEN (CLIP)
# ════════════════════════════════════════════════════════════════════
def seccion_5(cursor):
    titulo(5, "CONSULTA IMAGEN A TEXTO E IMAGEN A IMAGEN (CLIP)")
    # Imagen de consulta: una foto que NO está en el catálogo
    # (simula la foto que un cliente envía por WhatsApp)
    # Foto externa de un Renault Duster que NO está en el catálogo
    # (otra unidad distinta a las 30 imágenes indexadas)
    url_consulta = ("https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/"
                    "Renault_Duster_2.0_Dynamique_2016_%2837006132966%29.jpg/"
                    "960px-Renault_Duster_2.0_Dynamique_2016_%2837006132966%29.jpg")
    print(f"""
Escenario: el cliente envía por WhatsApp la FOTO de una camioneta
que vio en la calle ("¿tienen algo parecido a esto?").

Foto de consulta (NO está en el catálogo):
    {url_consulta[:80]}...

La imagen se embebe con CLIP (512 dim) y se compara contra:
  a) las ETIQUETAS de texto del catálogo  → IMAGEN A TEXTO
  b) las FOTOS del catálogo               → IMAGEN A IMAGEN
""")
    from PIL import Image
    req = urllib.request.Request(
        url_consulta, headers={"User-Agent": "TrebolMotorsBot/1.0 (academico)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        img = Image.open(io.BytesIO(r.read())).convert("RGB")
    vec = json.dumps(modelo_clip_imagen().encode(img).tolist())

    print("--- a) IMAGEN A TEXTO: etiquetas más afines a la foto ---")
    cursor.execute("""
        SELECT vid.chunk_texto,
               1 - (vid.embedding <=> %s::vector) AS similitud
        FROM vec_imagen_vehiculo_descripcion vid
        ORDER BY vid.embedding <=> %s::vector
        LIMIT 3;
    """, (vec, vec))
    for i, (texto, sim) in enumerate(cursor.fetchall(), 1):
        print(f"  {i}. \"{texto}\"  (similitud {sim:.4f})")

    print("\n--- b) IMAGEN A IMAGEN: vehículos del catálogo visualmente similares ---")
    cursor.execute("""
        SELECT v.marca, v.linea, v.anio, v.precio_venta,
               1 - (viv.embedding <=> %s::vector) AS similitud
        FROM vec_imagen_vehiculo viv
        JOIN vehiculo v ON v.id_vehiculo = viv.id_vehiculo
        ORDER BY viv.embedding <=> %s::vector
        LIMIT 3;
    """, (vec, vec))
    for i, (marca, linea, anio, precio, sim) in enumerate(cursor.fetchall(), 1):
        print(f"  {i}. {marca} {linea} {anio} — ${precio:,.0f}  (similitud {sim:.4f})")


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 6 — LAS 3 ESTRATEGIAS DE CHUNKING
# ════════════════════════════════════════════════════════════════════
def seccion_6(cursor):
    titulo(6, "COMPARACIÓN DE LAS 3 ESTRATEGIAS DE CHUNKING")
    consulta = "¿Hay algún SUV automático disponible?"
    print(f"""
La MISMA pregunta se ejecuta contra los chunks generados por cada
estrategia. Se muestra el mejor chunk recuperado y su similitud:
    "{consulta}"
""")
    vec = json.dumps(modelo_texto().encode(consulta).tolist())

    cursor.execute("""
        SELECT ec.nombre_estrategia, COUNT(*),
               ROUND(AVG(LENGTH(cre.contenido_texto)), 0)
        FROM chunk_resultado_experimento cre
        JOIN experimento_chunking ec USING (id_experimento)
        GROUP BY ec.id_experimento, ec.nombre_estrategia
        ORDER BY ec.id_experimento;
    """)
    print(f"{'Estrategia':<18} {'Total chunks':>13} {'Long. promedio':>15}")
    print("-" * 48)
    for nombre, total, longitud in cursor.fetchall():
        print(f"{nombre:<18} {total:>13} {f'{longitud:.0f} chars':>15}")

    print("\nTop-1 recuperado por cada estrategia para la consulta:")
    for id_exp in (1, 2, 3):
        cursor.execute("""
            SELECT ec.nombre_estrategia, cre.contenido_texto,
                   1 - (cre.vector_embedding <=> %s::vector) AS similitud
            FROM chunk_resultado_experimento cre
            JOIN experimento_chunking ec USING (id_experimento)
            WHERE cre.id_experimento = %s
            ORDER BY cre.vector_embedding <=> %s::vector
            LIMIT 1;
        """, (vec, id_exp, vec))
        nombre, chunk, sim = cursor.fetchone()
        print(f"\n  [{nombre}] similitud = {sim:.4f}")
        print(f"  chunk: \"{chunk[:90]}{'...' if len(chunk) > 90 else ''}\"")

    print("""
Lectura del resultado: fixed-size recupera FRAGMENTOS sueltos
(menor contexto), sentence-aware recupera la oración técnica
completa, y semantic recupera el registro íntegro del vehículo.
Los resultados completos del experimento están en la vista
vw_resultados_experimento (6 preguntas × 3 estrategias).
""")
    cursor.execute("SELECT nombre_estrategia, similitud_promedio, puntaje_promedio, "
                   "respuestas_correctas, respuestas_parciales, respuestas_incorrectas "
                   "FROM vw_resultados_experimento;")
    filas = cursor.fetchall()
    if filas and filas[0][1] is not None:
        print(f"{'Estrategia':<18} {'Sim.prom':>9} {'Pts.prom':>9} "
              f"{'OK':>4} {'Parc':>5} {'Mal':>4}")
        print("-" * 54)
        for nombre, sim, pts, ok, parc, mal in filas:
            print(f"{nombre:<18} {sim:>9} {pts:>9} {ok:>4} {parc:>5} {mal:>4}")
    else:
        print("(Ejecuta evaluar_experimento.py para llenar la tabla de resultados)")


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 7 — QUÉ ES UNA CONSULTA HÍBRIDA
# ════════════════════════════════════════════════════════════════════
def seccion_7(cursor=None):
    titulo(7, "¿QUÉ ES UNA CONSULTA HÍBRIDA?")
    print("""
Una CONSULTA HÍBRIDA combina, en una misma operación de recuperación,
dos mecanismos de búsqueda de naturaleza distinta:

  1. BÚSQUEDA RELACIONAL (exacta)
     Filtros deterministas sobre columnas estructuradas:
     precio_venta < 35000000, carroceria = 'suv', estado = 'disponible'.
     Se resuelve con índices B-tree. Un registro CUMPLE o NO CUMPLE:
     no hay grados intermedios.

  2. BÚSQUEDA VECTORIAL (semántica)
     Ranking por similitud de significado entre el embedding de la
     consulta y los embeddings del corpus, usando distancia coseno
     (operador <=> de pgvector) con índice HNSW. No filtra: ORDENA
     por cercanía semántica con valores continuos entre 0 y 1.

En PostgreSQL + pgvector ambas capas conviven en la misma sentencia:

    SELECT ...
    FROM chunk_resultado_experimento cre
    JOIN vehiculo v USING (id_vehiculo)
    WHERE v.precio_venta < 35000000          ← capa relacional (PODA)
      AND v.estado_vehiculo = 'disponible'   ← capa relacional (PODA)
    ORDER BY cre.vector_embedding <=> :q     ← capa vectorial (ORDENA)
    LIMIT 5;

POR QUÉ NINGUNA CAPA BASTA POR SÍ SOLA:
  - SQL solo: no puede interpretar "cómoda y segura para viajar"
    — esa intención no existe en ninguna columna.
  - Vectorial solo: no puede garantizar "menos de 35 millones"
    — un embedding no entiende umbrales numéricos exactos; podría
    devolver un vehículo de 36 millones por ser semánticamente afín.

La consulta híbrida une la PRECISIÓN del modelo relacional con la
FLEXIBILIDAD del modelo vectorial: el WHERE garantiza las
restricciones duras del negocio y el ORDER BY vectorial ordena los
candidatos restantes por relevancia semántica real para el cliente.
Este es el fundamento del sistema RAG de Trébol Motors (Sección 1b
de la primera entrega).
""")


# ════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════
SECCIONES = {
    1: seccion_1, 2: seccion_2, 3: seccion_3,
    4: seccion_4, 5: seccion_5, 6: seccion_6, 7: seccion_7,
}

if __name__ == "__main__":
    print("Conectando a Supabase...")
    conn = conectar()
    cursor = conn.cursor()
    print("[OK] Conectado a la base de datos")

    if len(sys.argv) > 1:
        n = int(sys.argv[1])
        SECCIONES[n](cursor)
    else:
        for n in sorted(SECCIONES):
            SECCIONES[n](cursor)

    cursor.close()
    conn.close()
    print("\n[OK] Demo finalizada")
