"""
pipeline_embeddings.py
======================
Trébol Motors — Experimento de Chunking (Segunda Entrega)
Autores: Juan Esteban Jiménez Vargas - Santiago Pérez Cardona

Ejecuta las 3 estrategias de chunking requeridas por el enunciado
sobre las descripciones de vehículos almacenadas en vec_vehiculo_descripcion,
genera embeddings con BAAI/bge-m3 (1024 dimensiones) y almacena los
resultados en chunk_resultado_experimento para comparación posterior.

Dependencias:
    pip install psycopg2-binary sentence-transformers langchain-text-splitters
"""

from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Conexión robusta: pooler IPv4 + reintentos + fallback DNS-over-HTTPS
# (ver db_conexion.py — la conexión directa db.*.supabase.co es solo
# IPv6 y el DNS del ISP es intermitente)
from db_conexion import conectar

try:
    conn = conectar()
    cursor = conn.cursor()
    print("[OK] Conexión a Supabase exitosa")
except Exception as e:
    print(f"[ERROR] Error de conexión: {e}")
    raise SystemExit(1)

# ============================================================
# MODELO DE EMBEDDINGS
# Modelo: BAAI/bge-m3 — 1024 dimensiones, multilingüe,
# gratuito y de alto rendimiento para español.
# Justificación del cambio respecto a la primera entrega:
# text-embedding-3-small (OpenAI, 1536 dim) requiere API key
# de pago; BAAI/bge-m3 corre localmente sin costo y supera
# a text-embedding-3-small en benchmarks multilingües (MTEB).
# Las tablas vec_* del esquema original (1536 dim) se mantienen
# intactas. El experimento usa chunk_resultado_experimento
# (1024 dim) que es la tabla creada para esta comparación.
# ============================================================
print("Cargando modelo BAAI/bge-m3 (1024 dim)...")
model = SentenceTransformer("BAAI/bge-m3")
print("[OK] Modelo cargado")

# ============================================================
# EXTRAER TEXTOS — ficha técnica + descripción comercial
# El texto de entrada del experimento es la ficha técnica
# (de vec_vehiculo_descripcion, ya actualizada por
# update_chunks_trebol.sql) concatenada con la descripción
# comercial del vehículo, unidas con punto. Esto produce un
# texto de DOS oraciones (~145 chars) que permite que las tres
# estrategias se comporten de forma distinta:
#   - fixed-size corta a mitad de frase (ignora la puntuación)
#   - sentence-aware corta exactamente en el punto entre oraciones
#   - semantic mantiene el registro completo como unidad
# ============================================================
cursor.execute("""
    SELECT vd.id_vehiculo,
           vd.chunk_texto || '. ' || COALESCE(v.descripcion, '')
    FROM vec_vehiculo_descripcion vd
    JOIN vehiculo v ON v.id_vehiculo = vd.id_vehiculo
    ORDER BY vd.id_vehiculo;
""")
vehiculos = cursor.fetchall()
print(f"[OK] {len(vehiculos)} fichas de vehículos listas para procesar")

# ============================================================
# DEFINICIÓN DE LAS 3 ESTRATEGIAS DE CHUNKING
# ============================================================

# --- Estrategia 1: Fixed-size chunking ---
# Corta rígidamente cada 60 caracteres (con solapamiento de 15)
# usando solo el espacio como separador. Sobre un texto de ~145
# chars produce 3-4 fragmentos que cortan a mitad de frase,
# separando el sujeto de sus predicados
# ("Mazda CX-5 2025 gris | plata mecánica hibrido...").
# Hipótesis: menor precisión, porque el promediado de tokens de
# un fragmento incompleto produce un embedding más genérico que
# el de la ficha completa.
fixed_splitter = RecursiveCharacterTextSplitter(
    chunk_size=60,
    chunk_overlap=15,
    separators=[" "]
)

# --- Estrategia 2: Sentence-aware chunking ---
# Respeta los límites naturales de oraciones: prioriza cortar en
# punto seguido, interrogación, exclamación o doble salto de línea.
# Con chunk_size=100 sobre un texto de dos oraciones (~145 chars),
# corta exactamente en el punto: produce un chunk con la ficha
# técnica completa y otro con la descripción comercial completa.
# Hipótesis: mejor que fixed-size porque cada chunk es una oración
# coherente, pero divide el registro del vehículo en dos unidades.
sentence_splitter = RecursiveCharacterTextSplitter(
    chunk_size=100,
    chunk_overlap=0,
    separators=["\n\n", ". ", "? ", "! ", " "]
)

# --- Estrategia 3: Semantic chunking (entidad completa) ---
# Sin fragmentación: la ficha descriptiva del vehículo se
# vectoriza como un único chunk. La unidad semántica natural
# en este dominio ES el vehículo: un cliente nunca pregunta por
# un "fragmento de descripción", pregunta por el vehículo.
# Hipótesis: máxima precisión para consultas de catálogo.
# Desventaja: para textos muy largos (>400 tokens) el embedding
# promedia demasiados tokens y pierde señal; en este dominio
# (fichas de 20-60 tokens) el riesgo no aplica.
ESTRATEGIAS = [
    {
        "id": 1,
        "nombre": "fixed-size",
        "splitter": fixed_splitter,
        "descripcion": "BGE-M3 | 60 chars | overlap 15 | separador: espacio (corta a mitad de frase)"
    },
    {
        "id": 2,
        "nombre": "sentence-aware",
        "splitter": sentence_splitter,
        "descripcion": "BGE-M3 | 100 chars | corta en límites de oración (punto, ?, !)"
    },
    {
        "id": 3,
        "nombre": "semantic",
        "splitter": None,  # Sin fragmentación — registro completo
        "descripcion": "BGE-M3 | Sin fragmentación — registro completo del vehículo como unidad semántica"
    }
]

# Registrar experimentos en la BD
for est in ESTRATEGIAS:
    cursor.execute("""
        INSERT INTO experimento_chunking (id_experimento, nombre_estrategia, configuracion_detallada)
        VALUES (%s, %s, %s)
        ON CONFLICT (id_experimento) DO UPDATE
            SET nombre_estrategia = EXCLUDED.nombre_estrategia,
                configuracion_detallada = EXCLUDED.configuracion_detallada;
    """, (est["id"], est["nombre"], est["descripcion"]))
conn.commit()
print("[OK] Experimentos registrados en BD")

# Limpiar resultados previos para evitar duplicados en re-ejecución
cursor.execute("DELETE FROM chunk_resultado_experimento;")
conn.commit()
print("[OK] Tabla chunk_resultado_experimento limpiada")

# ============================================================
# PIPELINE PRINCIPAL
# Para cada vehículo × estrategia:
#   1. Fragmentar el texto según la estrategia
#   2. Generar embedding con BGE-M3
#   3. Insertar en chunk_resultado_experimento
# ============================================================
total_chunks = 0
print("\nIniciando generación de embeddings...")

for id_vehiculo, texto_completo in vehiculos:
    for est in ESTRATEGIAS:

        # Fragmentar
        if est["splitter"] is not None:
            chunks = est["splitter"].split_text(texto_completo)
        else:
            chunks = [texto_completo]  # Estrategia 3: ficha completa

        for idx, chunk_texto in enumerate(chunks):
            # Generar embedding localmente (sin costo de API)
            vector = model.encode(chunk_texto).tolist()

            cursor.execute("""
                INSERT INTO chunk_resultado_experimento
                    (id_experimento, id_vehiculo, indice_chunk,
                     contenido_texto, vector_embedding)
                VALUES (%s, %s, %s, %s, %s);
            """, (est["id"], id_vehiculo, idx, chunk_texto, vector))
            total_chunks += 1

    # Commit por lote de vehículo para no perder progreso
    conn.commit()

    if id_vehiculo % 25 == 0:
        print(f"  Procesados {id_vehiculo} vehículos, {total_chunks} chunks...")

conn.commit()
print(f"\n[OK] PROCESO COMPLETADO")
print(f"  Total chunks generados: {total_chunks}")
print(f"  Distribución esperada:")
print(f"    fixed-size:     ~{total_chunks // 3 * 2 // 2} (2-3 chunks por vehículo)")
print(f"    sentence-aware: ~{total_chunks // 3} (1-2 chunks por vehículo)")
print(f"    semantic:       {len(vehiculos)} (1 chunk por vehículo)")
print(f"\n  Ejecuta 03_consultas_rag_demo.sql en Supabase para ver resultados.")

cursor.close()
conn.close()
