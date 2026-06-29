# 03 — Pipeline RAG: embeddings, chunking y evaluación

## Flujo completo

```
trebol_motors_datos.sql
        │
        ▼
tabla vehiculo (PostgreSQL / Supabase)
        │
        ▼
pipeline_embeddings.py
  ├── Estrategia 1: fixed-size  (60 chars, overlap 15)
  ├── Estrategia 2: sentence    (100 chars, corta en puntuación)
  └── Estrategia 3: semantic    (ficha completa del vehículo, sin fragmentar)
        │
        ▼
chunk_resultado_experimento  ← vectores 1024 dim (BAAI/bge-m3)
        │
        ▼
evaluar_experimento.py
  └── 6 preguntas de prueba → similitud coseno → puntaje 0-2
        │
        ▼
vw_resultados_experimento   ← vista resumen por estrategia
```

## Scripts del pipeline

### `pipeline_embeddings.py`
- Modelo: `BAAI/bge-m3` (1024 dimensiones, multilingüe, gratuito/local)
- 3 estrategias de chunking sobre los campos de la tabla `vehiculo`
- Guarda en `chunk_resultado_experimento` (id_experimento: 1, 2 o 3)
- Crea índice HNSW: `CREATE INDEX ... USING hnsw(vector_embedding vector_cosine_ops)`

### `pipeline_multimodal.py`
- Modelo: `clip-ViT-B-32` + `clip-ViT-B-32-multilingual-v1` (512 dim)
- Descarga ~30 imágenes de Wikimedia de vehículos similares al catálogo
- Guarda embeddings en `vec_imagen_vehiculo` y `vec_imagen_vehiculo_descripcion`
- Permite búsquedas texto→imagen e imagen→imagen

### `evaluar_experimento.py`
- 6 preguntas ground-truth con respuestas esperadas
- Ejecuta búsqueda vectorial para cada pregunta en cada estrategia
- Rubrica automática: 2 (correcto) / 1 (parcial) / 0 (incorrecto)
- Guarda en `evaluacion_experimento`

### `demo_consultas.py`
- Demuestra búsquedas híbridas: pgvector + filtros SQL en una sola query
- Muestra similitud coseno en los resultados

## Resultado del experimento

| Estrategia | Descripción | Resultado |
|---|---|---|
| fixed-size | Chunks de 60 chars con overlap 15 | Fragmenta referencias, scores bajos |
| sentence | 100 chars, corta en puntuación | Mejor, pero aún fragmenta datos numéricos |
| **semantic** | Ficha completa del vehículo | **Ganador** — vehículos de 20-60 tokens encajan perfectamente |

La estrategia `semantic` gana porque los registros de vehículos son cortos por naturaleza
y no se benefician del chunking — mejor vectorizar la ficha entera.

## Orden de ejecución

```bash
python pipeline_embeddings.py   # ~5 min (descarga bge-m3 la primera vez)
python pipeline_multimodal.py   # ~3 min (descarga CLIP)
python evaluar_experimento.py   # segundos
python demo_consultas.py        # segundos
```
