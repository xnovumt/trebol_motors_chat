# 02 — Conexión a Supabase

## Arquitectura de conexión

```
Script / Bot
    │
    ├── load_dotenv()         ← lee .env local (dev) o env vars de Render (prod)
    │
    ├── DATABASE_URL          ← postgresql://user:pass@pooler.supabase.com:5432/postgres
    │
    └── psycopg2.connect()
            │
            ├── Intento 1: DNS normal del sistema
            │       └── si falla por DNS → intento con DoH
            │
            └── Fallback DNS-over-HTTPS (8.8.8.8 por IP directa)
                    └── resuelve hostname → conecta con hostaddr=
```

## Dos módulos de conexión

### 1. `db_conexion.py` — para scripts standalone

Lee `DATABASE_URL` del entorno (`.env`). Expone `conectar() → psycopg2.connection`.

```python
from db_conexion import conectar
conn = conectar()
```

Usado por: `pipeline_embeddings.py`, `pipeline_multimodal.py`, `evaluar_experimento.py`, `demo_consultas.py`.

### 2. `chatbot/chat_whatsapp.py` — para el bot FastAPI

Crea un `psycopg2.pool.SimpleConnectionPool` (min=1, max=5) al iniciar el servidor.
Se accede via `state["pool"]` desde los endpoints FastAPI.

```python
pool = state["pool"]
conn = pool.getconn()
try:
    cur = conn.cursor()
    cur.execute("SELECT ...")
    ...
finally:
    pool.putconn(conn)
```

## Supabase — dónde encontrar la URL de conexión

1. Ir a [app.supabase.com](https://app.supabase.com)
2. Seleccionar el proyecto
3. **Settings → Database → Connection String**
4. Elegir **Session mode** (no Transaction mode)
5. Copiar la URI y ponerla en `.env` como `DATABASE_URL`

> **Importante**: usar la URL del **pooler** (`pooler.supabase.com`), NO la directa (`db.*.supabase.co`).
> La URL directa es solo IPv6 y falla en redes sin soporte IPv6.

## Tablas principales

| Tabla | Descripción |
|---|---|
| `vehiculo` | Catálogo de vehículos disponibles |
| `chunk_resultado_experimento` | Chunks vectorizados por estrategia (id_experimento 1/2/3) |
| `evaluacion_experimento` | Resultados de evaluación de cada estrategia |
| `vw_resultados_experimento` | Vista resumen del experimento de chunking |
| `vec_imagen_vehiculo` | Embeddings CLIP de imágenes de vehículos |

## pgvector

El proyecto usa el operador `<=>` (distancia coseno) de pgvector:

```sql
ORDER BY cre.vector_embedding <=> $1::vector
LIMIT 4
```

pgvector está instalado en Supabase vía `CREATE EXTENSION vector`.
El índice HNSW acelera las búsquedas aproximadas de vecinos más cercanos.
