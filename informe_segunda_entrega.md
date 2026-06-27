# Segunda Entrega — Sistema de Gestión de Concesionaria mediante Chat de WhatsApp
**Trébol Motors**  
**Integrantes:** Juan Esteban Jiménez Vargas — Santiago Pérez Cardona  
**Curso:** Bases de Datos No Relacionales  
**Fecha:** Junio 2026

---

## Sección 1 — Correcciones al Modelo de la Primera Entrega

La revisión de la primera entrega identificó cuatro problemas. A continuación se documenta cada corrección aplicada. El script `01_correcciones_modelo.sql` contiene el DDL ejecutable en Supabase.

---

### Corrección 1 — Inconsistencia entre ERD y esquema físico: RETOMA.id_vehiculo_destino

**Problema señalado:** El ERD modela RETOMA–VEHICULO como 1:1 opcional ("un vehículo puede ser destino de como máximo una retoma activa a la vez"), pero el script original no incluía la restricción `UNIQUE` en `id_vehiculo_destino`. La base de datos aceptaba múltiples retomas apuntando al mismo vehículo, contradiciendo la cardinalidad declarada.

**Corrección aplicada:**
```sql
ALTER TABLE retoma
    ADD CONSTRAINT uq_retoma_vehiculo_destino
    UNIQUE (id_vehiculo_destino);
```

Con esta restricción, el motor de base de datos hace cumplir la regla de negocio: si un cliente tiene activa una retoma apuntando al vehículo 42, ningún otro registro de retoma puede apuntar también al vehículo 42. Esto elimina la inconsistencia entre el diseño conceptual y el físico.

---

### Corrección 2 — Índice B-tree faltante en BUSQUEDA_FILTRADA

**Problema señalado:** El esquema ya incluía índices sobre `vehiculo.estado_vehiculo`, `vehiculo.marca`, `vehiculo.precio_venta` y `vehiculo.kilometraje`. El índice ausente era el compuesto `(id_cliente, fecha_busqueda)` sobre `busqueda_filtrada`, necesario para recuperar el historial de búsquedas de un cliente ordenado cronológicamente.

**Corrección aplicada:**
```sql
CREATE INDEX IF NOT EXISTS idx_busqueda_cliente_fecha
    ON busqueda_filtrada (id_cliente, fecha_busqueda DESC);
```

El chatbot consulta frecuentemente "¿qué búsquedas hizo este cliente antes?" para contextualizar la sesión actual. Sin este índice, esa consulta escala linealmente con el total de búsquedas en la tabla; con él, la búsqueda usa un index scan sobre los registros del cliente específico.

---

### Corrección 3 — Referencias polimórficas sin integridad referencial

**Problema señalado:** Los campos `id_elemento_gen + tipo_elemento_gen` en `INTERACCION_CHATBOT` y los equivalentes en `NOTIFICACION` implementan referencias polimórficas que PostgreSQL no puede verificar mediante restricciones `FOREIGN KEY` estándar. La base de datos aceptaba `id_elemento_gen = 9999` con `tipo_elemento_gen = 'CITA'` aunque no existiera ninguna cita con ese ID.

**Corrección aplicada:** Se implementaron dos triggers `BEFORE INSERT OR UPDATE` que verifican la existencia del registro referenciado según el valor del discriminador:

```sql
CREATE OR REPLACE FUNCTION fn_validar_elemento_gen_interaccion()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.id_elemento_gen IS NULL THEN RETURN NEW; END IF;
    IF NEW.tipo_elemento_gen = 'CITA' THEN
        IF NOT EXISTS (SELECT 1 FROM cita WHERE id_cita = NEW.id_elemento_gen)
        THEN RAISE EXCEPTION 'id_elemento_gen=% no existe en cita', NEW.id_elemento_gen;
        END IF;
    -- (ídem para NEGOCIACION_PRECIO, RETOMA, SOLICITUD_ESPECIAL)
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

Los triggers rechazan cualquier inserción o actualización que referencie un registro inexistente, reproduciendo funcionalmente la protección que daría una `FOREIGN KEY` nativa.

---

### Corrección 4 — Dependencia transitiva en INTERACCION_CHATBOT (3FN)

**Problema señalado:** `tipo_elemento_gen` no depende directamente de `id_interaccion` (la clave primaria), sino del valor de `id_elemento_gen`. Si `id_elemento_gen = 15` siempre es una `CITA`, entonces `tipo_elemento_gen = 'CITA'` es una dependencia funcional transitiva a través de `id_elemento_gen`, violando 3FN.

**Decisión de diseño justificada:** La solución estrictamente correcta en 3FN sería usar columnas FK nulas separadas (`id_cita_gen`, `id_negociacion_gen`, `id_retoma_gen`, `id_solicitud_gen`). Se mantiene el patrón discriminador por las siguientes razones operativas:

1. En el contexto de un chatbot de WhatsApp, la capa de aplicación necesita determinar el tipo del elemento generado en una única consulta `SELECT tipo_elemento_gen FROM interaccion_chatbot WHERE id_interaccion = X`, sin evaluar cuál de cuatro columnas no es `NULL`.
2. La integridad referencial que normalmente garantizaría una `FK` nativa queda cubierta por el trigger de la Corrección 3.
3. La dependencia transitiva es una denormalización controlada y documentada, no una omisión inadvertida.

Este patrón es análogo al uso de "table inheritance" o "polymorphic associations" en frameworks ORM modernos, donde la 3FN se sacrifica deliberadamente a favor de la usabilidad operativa con cobertura de integridad por triggers.

---

## Sección 2 — Implementación del Sistema RAG

### 2.1 Arquitectura desplegada

La base de datos está operativa en **Supabase** (PostgreSQL 15 + extensión `pgvector`). El esquema completo incluye:

- **22 tablas relacionales** distribuidas en 13 módulos funcionales
- **11 tablas vectoriales** (`vec_*`) con índices HNSW (m=16, ef_construction=64, vector_cosine_ops)
- **3 tablas del experimento de chunking** (`experimento_chunking`, `chunk_resultado_experimento`, `evaluacion_experimento`)

**Volumen del dataset:**
| Tabla | Registros |
|---|---|
| administrador | 5 |
| cliente | 100 |
| vehiculo | 150 |
| vec_vehiculo_descripcion | 150 |
| vec_vehiculo_equipamiento | 150 |
| negociacion_precio | 39 |
| turno_negociacion | 39 |
| vec_turno_negociacion | 39 |
| cita | 44 |

### 2.2 Modelos de embeddings

**Texto (1024 dim):** se usó **BAAI/bge-m3** en lugar de `text-embedding-3-small` (OpenAI, 1536 dim) propuesto en la primera entrega. Justificación:

- Corre localmente sin costo de API, permitiendo regenerar embeddings libremente durante el experimento.
- Supera a `text-embedding-3-small` en benchmarks multilingües MTEB para español.
- Las tablas `vec_*` del esquema original mantienen `vector(1536)` para compatibilidad con el diseño; las tablas del experimento usan `vector(1024)` ajustada al modelo real.

**Imagen y texto multimodal (512 dim, espacio compartido):**

| Contenido | Modelo | Tabla destino |
|---|---|---|
| Fotos del catálogo | `clip-ViT-B-32` (igual al diseño original) | `vec_imagen_vehiculo` |
| Etiquetas de las fotos | `clip-ViT-B-32-multilingual-v1` | `vec_imagen_vehiculo_descripcion` |

El encoder de texto multilingüe está **alineado al espacio vectorial de CLIP**: un texto en español y una foto producen vectores comparables por similitud coseno. Esto es lo que habilita las consultas texto→imagen ("una camioneta SUV de color rojo" contra las fotos) e imagen→texto (la foto que un cliente envía por WhatsApp contra las etiquetas del catálogo).

**Conjunto de imágenes:** se indexaron 30 fotografías reales (Wikimedia Commons) mapeadas a vehículos del catálogo, cubriendo los 5 colores (rojo, azul, blanco, gris, negro), los 16 modelos y varios ángulos (frontal, trasera, interior). Cada foto lleva una etiqueta densa en español (color + tipo de carrocería + ángulo + segmento) que amplía la superficie de coincidencia de las consultas texto→imagen. La carga es reanudable: `pipeline_multimodal.py` solo procesa las imágenes sin embedding, con reintentos ante el límite de peticiones de Wikimedia.

**Ajuste de esquema documentado:** `vec_imagen_vehiculo_descripcion` estaba definida con `vector(1536)`. Para que la búsqueda imagen→texto sea matemáticamente posible, el embedding del texto debe vivir en el mismo espacio de 512 dimensiones que el embedding de la imagen — un vector de 1536 dim no es comparable por coseno con uno de 512. La tabla se redefinió con `vector(512)` en `04_multimodal.sql`, manteniendo el índice HNSW.

---

## Sección 3 — Experimento de Chunking

### 3.1 Por qué el chunking afecta la calidad del RAG

El modelo de recuperación vectorial busca fragmentos (chunks) que se inyectan como contexto al modelo generativo. La calidad de la respuesta depende directamente de si el chunk recuperado contiene exactamente la información relevante para la pregunta. En Trébol Motors el corpus es heterogéneo: coexisten fichas de vehículos (20-60 tokens), descripciones de equipamiento (~100 tokens) y mensajes de negociación conversacional (~20-30 tokens por turno). Una estrategia única de chunking producirá resultados subóptimos para al menos uno de estos tipos de contenido.

### 3.2 Las tres estrategias implementadas

El script `pipeline_embeddings.py` implementa las tres estrategias usando **LangChain RecursiveCharacterTextSplitter** y el modelo **BAAI/bge-m3**.

**Texto de entrada del experimento:** la ficha técnica del vehículo concatenada con su descripción comercial, unidas por punto (~145 caracteres, dos oraciones). Ejemplo:

> *"Mazda CX-5 2025 gris plata mecánica hibrido 2L suv 17.977 km estado excelente. Vehículo en perfectas condiciones, único dueño, papeles al día."*

Este diseño del corpus garantiza que las tres estrategias produzcan segmentaciones genuinamente distintas (un texto de una sola oración corta no fragmentaría con ninguna estrategia, invalidando la comparación).

| Estrategia | Parámetros | Comportamiento sobre el corpus |
|---|---|---|
| **Fixed-size** | 60 chars, overlap 15, sep: espacio | 3-4 fragmentos por registro, corta a mitad de frase |
| **Sentence-aware** | 100 chars, corte en `.`, `?`, `!`, `\n\n` | 2 chunks por registro, uno por oración completa |
| **Semantic** | Sin fragmentación — registro completo | 1 chunk por registro (unidad semántica = vehículo) |

#### Estrategia 1 — Fixed-size chunking
Corta el texto cada 60 caracteres considerando solo el espacio como separador. Produce fragmentos como `"Mazda CX-5 2025 gris plata mecánica"` y `"hibrido 2L suv 17.977 km"` — el sujeto queda separado de sus predicados, y el embedding de cada fragmento es más genérico que el del registro completo. Además, los fragmentos de la segunda oración (`"único dueño, papeles al día"`) son idénticos entre todos los vehículos, por lo que no aportan capacidad discriminativa a la recuperación.

#### Estrategia 2 — Sentence-aware chunking
Con límite de 100 caracteres y cortes priorizados en puntuación natural, divide el texto exactamente en el punto entre las dos oraciones: un chunk contiene la ficha técnica completa (toda la información discriminativa) y el otro la descripción comercial. Cada chunk es una oración coherente — no se separa sujeto de predicado — pero el registro del vehículo queda repartido en dos unidades de recuperación.

#### Estrategia 3 — Semantic chunking (entidad completa)
Vectoriza el registro completo del vehículo como un chunk único. La unidad semántica natural en este dominio **es el vehículo**: un cliente pregunta por el vehículo completo, no por un fragmento de su descripción. Mantener el registro íntegro garantiza que el embedding capture el perfil completo del objeto. El riesgo de esta estrategia es la dilución: si el registro contiene texto genérico (como la descripción comercial idéntica entre vehículos), ese contenido "promedia" el embedding y puede reducir levemente la similitud con consultas muy específicas — exactamente el trade-off que el experimento permite medir.

### 3.3 Resultados del experimento

**Metodología de evaluación (`evaluar_experimento.py`):** 6 preguntas de prueba (3 de recuperación estructurada en lenguaje natural, 3 de intención semántica) se ejecutan contra los chunks de cada estrategia. Para cada par pregunta-estrategia se registra el chunk top-1 por similitud coseno y se le asigna un puntaje 0-2 mediante una **rúbrica verificable contra los atributos relacionales del vehículo recuperado** (p. ej., para "¿Hay algún SUV automático?": 2 puntos si el vehículo recuperado cumple `carroceria='suv' AND transmision='automatica'`, 1 si cumple una condición, 0 si ninguna). Esto hace el experimento reproducible: re-ejecutar el script produce los mismos puntajes.

**Distribución de chunks generados** (986 en total): fixed-size 536 (3.6 por vehículo), sentence-aware 300 (2.0 por vehículo), semantic 150 (1.0 por vehículo).

**Resultados medidos** (`SELECT * FROM vw_resultados_experimento`):

| Estrategia | Similitud promedio | Puntaje promedio | Correctas | Parciales | Incorrectas |
|---|---|---|---|---|---|
| fixed-size | **0.5971** | 1.17 | 2 | 3 | 1 |
| sentence-aware | 0.5554 | **1.67** | 4 | 2 | **0** |
| semantic | 0.5429 | **1.67** | **5** | 0 | 1 |

**Conclusión del experimento — un hallazgo no trivial:** la estrategia con la similitud coseno promedio **más alta (fixed-size) es la de peor calidad de recuperación** (1.17 puntos, solo 2 correctas de 6). La explicación es estructural: un fragmento corto contiene menos contenido que "diluya" el embedding, así que alcanza similitudes numéricamente mayores con la consulta — pero al haber perdido el contexto del registro completo, esos fragmentos frecuentemente pertenecen al **vehículo equivocado**. La similitud coseno entre estrategias con chunks de distinta longitud **no es directamente comparable** como métrica de calidad; lo que importa es si el vehículo recuperado responde la pregunta.

Bajo la métrica correcta (puntaje de la rúbrica), la hipótesis de la primera entrega se confirma: **semantic gana en exactitud** (5/6 correctas) porque el embedding del registro completo preserva la asociación entre todos los atributos del vehículo. **Sentence-aware es la más consistente** (0 respuestas incorrectas): su primer chunk es exactamente la oración técnica de la ficha, pura señal discriminativa, aunque reparte el registro en dos unidades de recuperación. **Fixed-size es la peor opción para este corpus**, confirmando que fragmentar unidades semánticamente autosuficientes degrada la recuperación aunque las similitudes aparenten lo contrario.

Consecuencia de diseño: el chatbot de WhatsApp consulta los chunks de la estrategia semantic (`id_experimento = 3`), la ganadora en exactitud.

---

## Sección 4 — Integración con WhatsApp (Chatbot)

### 4.1 Arquitectura

El chatbot (`chatbot/chat_whatsapp.py`) es un webhook FastAPI que integra la API de WhatsApp Business (Meta) con el sistema RAG:

```
Cliente (WhatsApp) → Meta Graph API → POST /webhook
    → detect_intent(texto)        clasificación por palabras clave
    → run_rag_pipeline(texto)
        ├─ embedding de la consulta con BAAI/bge-m3 (1024 dim)
        ├─ extract_sql_filters     filtros relacionales detectados (precio, km, marca...)
        ├─ búsqueda vectorial      ORDER BY embedding <=> query_vector (pgvector, HNSW)
        └─ call_llm                Groq / Llama-3.1 genera la respuesta
    → send_whatsapp_message(respuesta) → Meta Graph API → Cliente
```

La búsqueda vectorial consulta `chunk_resultado_experimento` filtrando por la estrategia ganadora del experimento, demostrando en producción los conceptos de chunks, embeddings y búsqueda por similitud coseno de la primera entrega. La búsqueda es **híbrida**: el componente vectorial resuelve la intención semántica ("algo económico para la ciudad") y los filtros SQL detectados en el texto ("menos de 30 millones") acotan los resultados de forma exacta — la combinación que ninguna de las dos capas logra por separado.

### 4.2 Decisiones de conectividad (problemas reales resueltos)

Durante la implementación se diagnosticaron y resolvieron dos problemas de infraestructura documentables:

1. **Supabase directo es solo IPv6.** El host `db.PROYECTO.supabase.co` no tiene registro DNS A (IPv4), solo AAAA (IPv6). En redes sin IPv6 (la mayoría de redes residenciales en Colombia) la conexión falla con *could not translate host name*. Solución: usar el **connection pooler** de Supabase (`aws-1-us-west-2.pooler.supabase.com`, puerto 5432, usuario `postgres.PROYECTO`), que expone IPv4.

2. **DNS del ISP intermitente.** El módulo `db_conexion.py` implementa reintentos con backoff y, si la resolución DNS local falla, resuelve la IP vía **DNS-over-HTTPS** (consultando `8.8.8.8` directamente por IP, sin depender del DNS local) y conecta usando el parámetro `hostaddr` de libpq, que omite la resolución de nombres.

## Sección 5 — Demostración de capacidades (`demo_consultas.py`)

El script `demo_consultas.py` ejecuta en vivo las siete capacidades del sistema, mostrando para cada una la consulta SQL utilizada y los resultados reales desde Supabase. Puede ejecutarse completo (`python demo_consultas.py`) o por sección (`python demo_consultas.py 3`).

| # | Capacidad | Mecanismo |
|---|---|---|
| 1 | Consulta SQL común | Filtros B-tree sobre columnas estructuradas (`WHERE carroceria='suv' AND precio<35M`) |
| 2 | Texto a texto | Embedding bge-m3 de la consulta vs embeddings de fichas, `ORDER BY <=>` con HNSW |
| 3 | **Consulta híbrida** | `WHERE` relacional (poda exacta) + `ORDER BY` vectorial (ranking semántico) en una sola sentencia |
| 4 | Texto a imagen | Texto en español → CLIP multilingüe (512d) vs embeddings CLIP de las fotos |
| 5 | Imagen a texto / imagen a imagen | Foto de consulta → CLIP (512d) vs etiquetas y vs fotos del catálogo |
| 6 | 3 estrategias de chunking | La misma pregunta contra los chunks de cada estrategia + tabla del experimento |
| 7 | Definición de consulta híbrida | Explicación impresa con el SQL anotado |

### ¿Qué es una consulta híbrida?

Una **consulta híbrida** combina en una misma operación de recuperación dos mecanismos de naturaleza distinta:

1. **Búsqueda relacional (exacta):** filtros deterministas sobre columnas estructuradas (`precio_venta < 35000000`, `estado_vehiculo = 'disponible'`), resueltos con índices B-tree. Un registro cumple o no cumple — no hay grados intermedios.

2. **Búsqueda vectorial (semántica):** ranking por similitud de significado entre el embedding de la consulta y los embeddings del corpus, usando distancia coseno (operador `<=>` de pgvector) con índice HNSW. No filtra: ordena por cercanía semántica continua.

En PostgreSQL + pgvector ambas capas conviven en la misma sentencia:

```sql
SELECT v.marca, v.linea, v.precio_venta,
       1 - (cre.vector_embedding <=> :query_vector) AS similitud
FROM chunk_resultado_experimento cre
JOIN vehiculo v USING (id_vehiculo)
WHERE v.estado_vehiculo = 'disponible'      -- capa relacional (PODA)
  AND v.precio_venta < 35000000             -- capa relacional (PODA)
ORDER BY cre.vector_embedding <=> :query_vector  -- capa vectorial (ORDENA)
LIMIT 5;
```

Ninguna capa basta por sí sola: SQL no puede interpretar *"cómoda y segura para viajar"* (esa intención no existe en ninguna columna) y la búsqueda vectorial no puede garantizar *"menos de 35 millones"* (un embedding no entiende umbrales numéricos exactos — podría devolver un vehículo de 36 millones por ser semánticamente afín). La consulta híbrida une la **precisión** del modelo relacional con la **flexibilidad** del modelo vectorial, y es el fundamento del sistema RAG descrito en la Sección 1b de la primera entrega.

## Sección 6 — Scripts entregados

| Archivo | Descripción |
|---|---|
| `trebol_motors_schema.sql` | Esquema completo (tablas relacionales + vectoriales + índices HNSW) |
| `dataset.sql` | Dataset: 5 admins, 100 clientes, 150 vehículos, 39 negociaciones, 44 citas |
| `update_chunks_trebol.sql` | Actualización de chunk_texto en vec_vehiculo_descripcion (150 fichas) |
| `entrega_2.sql` | Tablas del experimento de chunking |
| `01_correcciones_modelo.sql` | Correcciones al modelo: UNIQUE retoma, índice busqueda_filtrada, triggers |
| `02_ground_truth_experimento.sql` | Vista de resultados y consultas de verificación del experimento |
| `03_consultas_rag_demo.sql` | Consultas RAG de demostración (3 categorías) |
| `04_multimodal.sql` | Capa multimodal: redefinición a vector(512) + 30 imágenes reales del catálogo (5 colores, varios ángulos) |
| `db_conexion.py` | Conexión robusta: pooler IPv4 + reintentos + fallback DNS-over-HTTPS |
| `pipeline_embeddings.py` | Pipeline completo: 3 estrategias de chunking + embeddings BGE-M3 |
| `evaluar_experimento.py` | Evaluación: 6 preguntas × 3 estrategias con rúbrica verificable |
| `pipeline_multimodal.py` | Embeddings CLIP: fotos del catálogo + etiquetas multilingües |
| `demo_consultas.py` | Demo de sustentación: las 7 capacidades ejecutables en vivo |
| `ejecutar_sql.py` | Utilidad para ejecutar archivos .sql con la conexión robusta |
| `chatbot/chat_whatsapp.py` | Webhook FastAPI: WhatsApp ↔ RAG ↔ Supabase |
| `chatbot/SETUP_WHATSAPP.md` | Guía de configuración del webhook (ngrok local / Render) |

**Orden de ejecución:**
1. `trebol_motors_schema.sql` (ya ejecutado)
2. `dataset.sql` (ya ejecutado)
3. `entrega_2.sql` (crear tablas del experimento)
4. `01_correcciones_modelo.sql` (aplicar correcciones)
5. `update_chunks_trebol.sql` (actualizar textos de fichas)
6. `python pipeline_embeddings.py` (generar chunks + embeddings de las 3 estrategias)
7. `python evaluar_experimento.py` (evaluar y registrar resultados reales)
8. `02_ground_truth_experimento.sql` (crear vista de resultados)
9. `python ejecutar_sql.py 04_multimodal.sql` (capa multimodal: imágenes)
10. `python pipeline_multimodal.py` (embeddings CLIP de fotos y etiquetas)
11. `python demo_consultas.py` (demo de las 7 capacidades)
12. `python chatbot/chat_whatsapp.py` + ngrok (demo WhatsApp en vivo)
