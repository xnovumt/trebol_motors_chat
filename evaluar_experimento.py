"""
evaluar_experimento.py
======================
Trébol Motors — Evaluación del Experimento de Chunking
Autores: Juan Esteban Jiménez Vargas - Santiago Pérez Cardona

Ejecuta las preguntas de prueba (ground truth) contra las 3 estrategias
de chunking y registra los resultados REALES en evaluacion_experimento:
  - similitud coseno del chunk top-1 recuperado por cada estrategia
  - puntaje 0-2 calculado con una rúbrica verificable contra los
    atributos relacionales del vehículo recuperado

Ejecutar DESPUÉS de pipeline_embeddings.py.

La rúbrica de puntaje (escala exigida: 0=incorrecto, 1=parcial, 2=correcto)
se evalúa automáticamente comparando los atributos SQL del vehículo
recuperado contra los criterios de la pregunta. Esto hace el experimento
reproducible: cualquiera puede re-ejecutar el script y obtener los
mismos puntajes.
"""

from sentence_transformers import SentenceTransformer

# Conexión robusta: pooler IPv4 + reintentos + fallback DNS-over-HTTPS
from db_conexion import conectar

# ============================================================
# GROUND TRUTH — 6 preguntas de prueba
# Categoría A: recuperación estructurada con lenguaje natural
# Categoría B: intención semántica sin filtros SQL exactos
# Cada pregunta define una rúbrica verificable sobre los
# atributos del vehículo recuperado (carroceria, km, etc.)
# ============================================================

def rubrica_suv_automatico(v):
    """A1: SUV + automática = 2 | una de las dos = 1 | ninguna = 0"""
    pts = (v["carroceria"] == "suv") + (v["transmision"] == "automatica")
    return pts

def rubrica_pickup_diesel_manual(v):
    """A2: pickup + diesel + manual: 3/3 = 2 | 2/3 = 1 | menos = 0"""
    aciertos = ((v["carroceria"] == "pickup")
                + (v["combustible"] == "diesel")
                + (v["transmision"] == "manual"))
    return 2 if aciertos == 3 else (1 if aciertos == 2 else 0)

def rubrica_fortuner_reciente(v):
    """A3: Toyota Fortuner 2024+ = 2 | Toyota Fortuner anterior = 1 | otro = 0"""
    if v["marca"] == "Toyota" and v["linea"] == "Fortuner":
        return 2 if v["anio"] >= 2024 else 1
    return 0

def rubrica_economico_ciudad(v):
    """B1: híbrido = +1, motor pequeño (<=1600cc) o hatchback = +1"""
    pts = 0
    if v["combustible"] == "hibrido":
        pts += 1
    if (v["cilindraje_cc"] or 9999) <= 1600 or v["carroceria"] == "hatchback":
        pts += 1
    return pts

def rubrica_poco_kilometraje(v):
    """B2: km < 20.000 = 2 | km < 40.000 = 1 | más = 0"""
    if v["kilometraje"] < 20000:
        return 2
    return 1 if v["kilometraje"] < 40000 else 0

def rubrica_camioneta_familiar(v):
    """B3: camioneta o suv = 2 | pickup = 1 | otro = 0"""
    if v["carroceria"] in ("camioneta", "suv"):
        return 2
    return 1 if v["carroceria"] == "pickup" else 0


PREGUNTAS = [
    {
        "categoria": "A",
        "texto": "¿Hay algún SUV automático disponible?",
        "ground_truth": "Vehículo con carroceria=suv y transmision=automatica",
        "rubrica": rubrica_suv_automatico,
    },
    {
        "categoria": "A",
        "texto": "Busco una pickup diesel mecánica",
        "ground_truth": "Vehículo con carroceria=pickup, combustible=diesel, transmision=manual",
        "rubrica": rubrica_pickup_diesel_manual,
    },
    {
        "categoria": "A",
        "texto": "¿Tienen Toyota Fortuner modelo 2024 o 2025?",
        "ground_truth": "Toyota Fortuner con anio >= 2024",
        "rubrica": rubrica_fortuner_reciente,
    },
    {
        "categoria": "B",
        "texto": "Quiero un carro económico que consuma poquito para andar en la ciudad",
        "ground_truth": "Vehículo híbrido y/o motor pequeño (1.6L) tipo hatchback",
        "rubrica": rubrica_economico_ciudad,
    },
    {
        "categoria": "B",
        "texto": "Necesito algo casi nuevo, con muy poco kilometraje",
        "ground_truth": "Vehículo con kilometraje < 20.000 km",
        "rubrica": rubrica_poco_kilometraje,
    },
    {
        "categoria": "B",
        "texto": "Busco una camioneta amplia y familiar para viajar con los niños",
        "ground_truth": "Vehículo con carroceria=camioneta o suv (espacio familiar)",
        "rubrica": rubrica_camioneta_familiar,
    },
]

# ============================================================
# EJECUCIÓN
# ============================================================

print("Conectando a Supabase...")
conn = conectar()
cursor = conn.cursor()
print("[OK] Conectado")

print("Cargando modelo BAAI/bge-m3...")
model = SentenceTransformer("BAAI/bge-m3")
print("[OK] Modelo cargado")

# Limpiar evaluaciones anteriores (idempotente)
cursor.execute("DELETE FROM evaluacion_experimento;")
conn.commit()

ESTRATEGIAS = [(1, "fixed-size"), (2, "sentence-aware"), (3, "semantic")]

print(f"\nEvaluando {len(PREGUNTAS)} preguntas x {len(ESTRATEGIAS)} estrategias...\n")

import json

for preg in PREGUNTAS:
    query_vector = json.dumps(model.encode(preg["texto"]).tolist())

    for id_exp, nombre in ESTRATEGIAS:
        # Top-1 chunk por similitud coseno para esta estrategia
        cursor.execute("""
            SELECT
                cre.contenido_texto,
                1 - (cre.vector_embedding <=> %s::vector) AS similitud,
                v.marca, v.linea, v.anio, v.carroceria, v.combustible,
                v.transmision, v.kilometraje, v.cilindraje_cc
            FROM chunk_resultado_experimento cre
            JOIN vehiculo v ON v.id_vehiculo = cre.id_vehiculo
            WHERE cre.id_experimento = %s
            ORDER BY cre.vector_embedding <=> %s::vector
            LIMIT 1;
        """, (query_vector, id_exp, query_vector))

        row = cursor.fetchone()
        chunk_texto, similitud = row[0], float(row[1])
        vehiculo = {
            "marca": row[2], "linea": row[3], "anio": row[4],
            "carroceria": row[5], "combustible": row[6],
            "transmision": row[7], "kilometraje": row[8],
            "cilindraje_cc": row[9],
        }

        puntaje = preg["rubrica"](vehiculo)

        cursor.execute("""
            INSERT INTO evaluacion_experimento
                (id_experimento, pregunta_test, ground_truth,
                 chunk_recuperado, similitud_coseno_recuperada, puntaje_humano)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (id_exp, preg["texto"], preg["ground_truth"],
              chunk_texto, round(similitud, 4), puntaje))

        print(f"  [{nombre:14s}] sim={similitud:.4f} pts={puntaje} | "
              f"{vehiculo['marca']} {vehiculo['linea']} {vehiculo['anio']} "
              f"({vehiculo['carroceria']}, {vehiculo['transmision']}, "
              f"{vehiculo['kilometraje']:,} km)")

    print(f"  Pregunta [{preg['categoria']}]: {preg['texto']}\n")

conn.commit()

# ============================================================
# RESUMEN FINAL
# ============================================================
print("=" * 70)
print("RESULTADOS DEL EXPERIMENTO (vw_resultados_experimento)")
print("=" * 70)
cursor.execute("SELECT * FROM vw_resultados_experimento;")
cols = [d[0] for d in cursor.description]
print(f"{'estrategia':<16} {'n':>3} {'sim_prom':>9} {'pts_prom':>9} "
      f"{'correctas':>10} {'parciales':>10} {'incorrectas':>12}")
for row in cursor.fetchall():
    print(f"{row[1]:<16} {row[2]:>3} {row[3]:>9} {row[4]:>9} "
          f"{row[5]:>10} {row[6]:>10} {row[7]:>12}")

cursor.close()
conn.close()
print("\n[OK] Evaluación completada y guardada en evaluacion_experimento")
