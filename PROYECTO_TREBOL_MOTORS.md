# Trébol Motors — Sistema RAG Multimodal para Concesionaria

**Autores:** Juan Esteban Jiménez Vargas · Santiago Pérez Cardona  
**Curso:** Bases de Datos Relacionales  
**Stack:** PostgreSQL 15 · pgvector · Python 3.12 · FastAPI · Supabase · WhatsApp Business API

---

## 1. El Problema

### 1.1 Contexto

Trébol Motors es una concesionaria de vehículos usados y nuevos ubicada en Manizales, Colombia. Como cualquier concesionaria mediana, enfrenta un problema de comunicación que no es técnico en apariencia pero lo es en el fondo: **los clientes preguntan en lenguaje humano, pero los datos están organizados en columnas SQL**.

Un cliente nunca llega y dice:
> `WHERE carroceria = 'suv' AND precio_venta < 35000000 AND kilometraje < 50000`

Un cliente llega y dice:
> *"Busco una camioneta cómoda y segura para viajar con los niños, que no cueste demasiado y tenga poco kilometraje"*

Esa brecha —entre la intención del cliente y la estructura de la base de datos— es el problema central.

### 1.2 Limitaciones del modelo relacional puro

Un sistema de consultas SQL tradicional puede resolver preguntas estructuradas exactas:
- `¿Tienen Toyota automáticos?` → `WHERE marca = 'Toyota' AND transmision = 'automatica'`
- `¿Cuánto cuesta el vehículo 42?` → `WHERE id_vehiculo = 42`

Pero **falla sistemáticamente** ante preguntas de intención semántica:
- *"Algo económico para la ciudad"* → no hay columna `economico`
- *"Un carro confiable para familia"* → no hay columna `confiable`
- *"Algo parecido a esto"* (con una foto enviada por WhatsApp) → SQL no puede comparar imágenes

Además, la concesionaria necesita:
- Gestionar negociaciones de precio de forma conversacional (turnos, ofertas, contraofertas)
- Registrar el historial completo de interacciones por cliente
- Agendar citas y test drives desde el mismo canal donde el cliente ya está: **WhatsApp**
- Manejar retomas (un cliente da su vehículo como parte de pago)
- Enviar notificaciones relevantes sin sobrecargar al asesor de ventas

### 1.3 El problema en una línea

> Un sistema de base de datos relacional por sí solo no puede entender el significado de una consulta en lenguaje natural, ni comparar imágenes, ni mantener una conversación contextualizada con un cliente.

---

## 2. La Solución: Arquitectura Híbrida Relacional + Vectorial

El proyecto construyó un sistema en tres capas que responden a este problema desde el modelo de datos hasta el canal de comunicación.

### 2.1 Capa Relacional (PostgreSQL 15 + Supabase)

La base de datos modela todos los procesos de negocio de la concesionaria con plena integridad referencial:

| Entidad | Qué representa |
|---|---|
| `vehiculo` | El catálogo completo: marca, línea, año, carrocería, combustible, transmisión, km, precio, color, estado |
| `cliente` | Clientes con número de WhatsApp, ciudad, estado (activo / inactivo / bloqueado) |
| `administrador` | Staff con roles y niveles de permisos (gerente, vendedor, soporte) |
| `negociacion_precio` | Negociaciones abiertas/cerradas/rechazadas sobre un vehículo y cliente |
| `turno_negociacion` | Cada oferta o contraoferta en una negociación, con actor y monto |
| `cita` | Citas de visita, test drive o evaluación de retoma |
| `retoma` | Cuando el cliente entrega su vehículo como parte de pago |
| `solicitud_especial` | Solicitudes fuera del catálogo actual |
| `busqueda_filtrada` | Historial de búsquedas del cliente desde el chatbot |
| `interaccion_chatbot` | Registro completo de conversaciones: pregunta, respuesta, intención |
| `notificacion` | Notificaciones generadas para el cliente o el asesor |

**El dataset:** ~150 vehículos (Mazda, Toyota, Chevrolet, Renault), ~50 clientes, 5 administradores, con negociaciones, citas y retomas en diferentes estados. Generado con datos sintéticos realistas para Colombia (precios en COP, ciudades colombianas, números de WhatsApp +57).

**Correcciones aplicadas en la segunda entrega** (`01_correcciones_modelo.sql`):
1. `UNIQUE` en `retoma.id_vehiculo_destino` — para que el esquema físico refleje la cardinalidad 1:1 declarada en el ERD.
2. Índice compuesto `(id_cliente, fecha_busqueda DESC)` en `busqueda_filtrada` — necesario para recuperar el historial cronológico del cliente desde el chatbot con eficiencia.
3. Triggers de validación en `interaccion_chatbot` y `notificacion` — estas tablas usan referencias polimórficas (`id_elemento_gen` + `tipo_elemento_gen`), un patrón que PostgreSQL no puede verificar con FK nativas. Los triggers `BEFORE INSERT OR UPDATE` verifican la existencia del registro referenciado en la tabla correcta según el discriminador, rechazando inserciones huérfanas.

### 2.2 Capa Vectorial (pgvector + embeddings)

La extensión `pgvector` en Supabase permite almacenar vectores de alta dimensión dentro de PostgreSQL y buscar por similitud coseno con el operador `<=>` usando índices **HNSW** (Hierarchical Navigable Small World) — el mismo algoritmo que usan los sistemas de búsqueda vectorial dedicados como Pinecone o Weaviate.

**Tablas vectoriales del sistema:**

| Tabla | Modelo | Dimensiones | Qué indexa |
|---|---|---|---|
| `vec_vehiculo_descripcion` | BAAI/bge-m3 | 1024 | Fichas técnicas en texto (marca, línea, año, carrocería, etc.) |
| `vec_vehiculo_equipamiento` | BAAI/bge-m3 | 1024 | Descripciones de equipamiento de cada vehículo |
| `vec_turno_negociacion` | BAAI/bge-m3 | 1024 | Mensajes de negociación (para buscar patrones de oferta similares) |
| `vec_imagen_vehiculo` | CLIP ViT-B/32 | 512 | Embeddings visuales de las fotos del catálogo |
| `vec_imagen_vehiculo_descripcion` | CLIP multilingual | 512 | Etiquetas en español alineadas al espacio CLIP |

**Decisión sobre el modelo de texto:** La primera entrega usaba `text-embedding-3-small` de OpenAI (1536 dim, API de pago). La segunda entrega migró a `BAAI/bge-m3` (1024 dim, gratuito, local) porque:
- Supera a text-embedding-3-small en benchmarks multilingües (MTEB)
- Corre en CPU sin costo de API
- Es ideal para español

### 2.3 El Experimento de Chunking (`pipeline_embeddings.py` + `02_ground_truth_experimento.sql`)

Antes de construir el sistema de búsqueda, el proyecto responde una pregunta de diseño fundamental: **¿cómo fragmentar el texto de una ficha técnica para maximizar la precisión de recuperación?**

Se compararon 3 estrategias sobre las descripciones de los ~150 vehículos:

| Estrategia | Configuración | Chunks por vehículo | Hipótesis |
|---|---|---|---|
| **Fixed-size** | 60 chars, overlap 15, separador: espacio | 3-4 | Menor precisión (corta a mitad de frase) |
| **Sentence-aware** | 100 chars, corta en `.`, `?`, `!`, `\n\n` | 1-2 | Mejor que fixed (chunks coherentes) |
| **Semantic** | Sin fragmentación — ficha completa | 1 | Máxima precisión en este dominio |

**Ground truth** (`evaluar_experimento.py`): 6 preguntas de prueba con rúbricas automáticas verificables:
- Categoría A (recuperación estructurada): `¿Hay algún SUV automático?`, `Busco una pickup diesel mecánica`, `¿Tienen Toyota Fortuner 2024?`
- Categoría B (intención semántica): `carro económico para la ciudad`, `algo casi nuevo con poco kilometraje`, `camioneta familiar para viajar`

Cada rúbrica evalúa los atributos SQL del vehículo recuperado (0 = incorrecto, 1 = parcial, 2 = correcto). Los resultados se persisten en `evaluacion_experimento` y se pueden consultar desde `vw_resultados_experimento`.

**Conclusión del experimento:** La estrategia **semantic** (ficha completa sin fragmentar) es la superior para este dominio. La justificación es importante: un cliente nunca pregunta por un "fragmento de descripción de vehículo" — pregunta por un vehículo. La unidad semántica natural ES el vehículo completo. Fixed-size produce chunks que cortan a mitad de frase (`"Mazda CX-5 2025 gris | plata mecánica..."`) generando embeddings más genéricos. Para textos cortos como fichas técnicas (20-60 tokens), la estrategia semantic no sufre el problema de dilución de señal que ocurre con textos muy largos (>400 tokens).

### 2.4 La Capa Multimodal (`pipeline_multimodal.py` + `04_multimodal.sql`)

El sistema añade una capa de búsqueda imagen ↔ texto usando **CLIP** (Contrastive Language–Image Pretraining), que proyecta imágenes y texto en el mismo espacio vectorial de 512 dimensiones.

Esto habilita tres tipos de consulta que SQL puro nunca podría resolver:

1. **Texto → Imagen:** *"Una camioneta SUV de color rojo"* → el sistema encuentra la foto del catálogo más similar visualmente. El color rojo no está en ninguna columna SQL — está en los píxeles, y CLIP lo captura.

2. **Imagen → Imagen:** El cliente envía una foto de un vehículo que vio en la calle preguntando *"¿tienen algo parecido a esto?"*. El sistema compara el embedding CLIP de la foto del cliente contra las 30 fotos del catálogo y devuelve las más similares visualmente.

3. **Imagen → Texto:** La misma foto del cliente se compara contra las etiquetas descriptivas del catálogo para encontrar la descripción textual más afín.

**Nota técnica importante:** En CLIP, las similitudes texto→imagen rondan 0.20-0.30 incluso en matches correctos. Esto es normal: texto e imagen ocupan regiones distintas del espacio compartido ("brecha de modalidad"). Lo relevante no es el valor absoluto sino el ranking — el top-1 es la foto que mejor corresponde. En cambio, similitudes imagen→imagen correctas superan 0.75 por ser la misma modalidad.

**Dataset de imágenes:** 30 fotos reales de Wikimedia Commons cubriendo los 5 colores del catálogo, los 16 modelos y varios ángulos (frontal, trasera, interior). Las etiquetas son descripciones densas en español para maximizar la superficie de coincidencia texto→imagen.

### 2.5 El Bot de WhatsApp (`chatbot/chat_whatsapp.py`)

El sistema completo se expone como un webhook FastAPI desplegado en Render, integrado con la WhatsApp Business API de Meta. Este es el canal real donde los clientes colombianos se comunicarían con la concesionaria.

**Flujo de un mensaje:**

```
Cliente escribe en WhatsApp
    → Meta API → POST /webhook (FastAPI)
        → detect_intent(texto)          # Clasifica: catálogo / negociación / cita / saludo
        → extract_sql_filters(texto)    # Detecta precios, km, marca, carrocería con regex
        → run_rag_pipeline(texto)       # Vector search + SQL filters + LLM
            → model.encode(texto)       # BAAI/bge-m3 → vector 1024 dim
            → pgvector <=> (similitud coseno) con filtros WHERE relacionales
            → call_llm(contexto)        # Groq / Llama-3.1-8b genera respuesta natural
        → send_whatsapp_message()       # Graph API de Meta → WhatsApp del cliente
```

**Detección de intención** (keyword scoring): El sistema clasifica el mensaje en 5 categorías:
- `catalog`: busca vehículos en el catálogo (pipeline RAG completo)
- `negotiation`: detecta montos y registra ofertas
- `appointment`: informa horarios y deriva a asesor
- `detail`: consulta equipamiento/características específicas
- `greeting`: respuesta de bienvenida con menú de opciones

**Filtros SQL automáticos** extraídos del lenguaje natural:
- *"menos de 30 millones"* → `AND v.precio_venta <= 30000000`
- *"menos de 50.000 km"* → `AND v.kilometraje < 50000`
- *"camioneta"* → `AND v.carroceria = 'camioneta'`
- *"híbrido"* → `AND v.combustible = 'hibrido'`
- *"Toyota"* → `AND LOWER(v.marca) = 'toyota'`

La **consulta híbrida resultante** combina ambas capas en una sola sentencia SQL — el WHERE poda con índices B-tree y el ORDER BY vectorial ordena por relevancia semántica:

```sql
SELECT v.marca, v.linea, v.precio_venta, v.kilometraje,
       1 - (cre.vector_embedding <=> $1::vector) AS similitud
FROM chunk_resultado_experimento cre
JOIN vehiculo v ON v.id_vehiculo = cre.id_vehiculo
WHERE cre.id_experimento = 3          -- chunks semánticos (ficha completa)
  AND v.estado_vehiculo = 'disponible'
  AND v.precio_venta <= 30000000      -- filtro relacional exacto
ORDER BY cre.vector_embedding <=> $1::vector   -- ranking semántico
LIMIT 4;
```

**Infraestructura de producción:**
- Servidor: Render (free tier, uvicorn)
- BD: Supabase (PostgreSQL 15 + pgvector, plan gratuito)
- LLM: Groq (Llama-3.1-8b-instant, gratuito hasta cierto volumen)
- Modelo local: BAAI/bge-m3 corriendo en el servidor de Render
- Conexión robusta: fallback DNS-over-HTTPS a 8.8.8.8 cuando el DNS del ISP falla (problema real que afectó el desarrollo)

---

## 3. Estructura de Archivos

```
entrega_final/
│
├── SQL (esquema y datos)
│   ├── entrega_2.sql                  # Tablas del experimento de chunking (1024 dim)
│   ├── 01_correcciones_modelo.sql     # Correcciones al esquema: UNIQUE, índice, triggers
│   ├── 02_ground_truth_experimento.sql # Vista vw_resultados_experimento
│   ├── 03_consultas_rag_demo.sql      # Consultas de demostración (A, B, C)
│   ├── 04_multimodal.sql              # Tablas CLIP + 30 imágenes de Wikimedia
│   ├── dataset.sql                    # Datos del catálogo (vehículos)
│   ├── trebol_motors_datos.sql        # Dataset completo (clientes, admins, citas, etc.)
│   └── update_chunks_trebol.sql       # Actualización de chunks en vec_vehiculo_descripcion
│
├── Python (pipelines y demo)
│   ├── db_conexion.py                 # Conexión robusta a Supabase (reintentos + DoH)
│   ├── pipeline_embeddings.py         # Genera chunks + embeddings BGE-M3 (3 estrategias)
│   ├── pipeline_multimodal.py         # Genera embeddings CLIP de imágenes y etiquetas
│   ├── evaluar_experimento.py         # Evalúa las 6 preguntas ground truth y guarda resultados
│   ├── demo_consultas.py              # Demo de 7 capacidades del sistema
│   ├── ejecutar_sql.py                # Utilidad para ejecutar archivos SQL
│   ├── front.py                       # Interfaz simple de prueba
│   ├── script.py                      # Scripts auxiliares
│   ├── prueba.py                      # Tests de conexión y consultas
│   └── test_conexion.py               # Verificación de conexión
│
├── chatbot/                           # Bot de WhatsApp listo para Render
│   ├── chat_whatsapp.py               # FastAPI webhook completo (RAG + LLM + Meta API)
│   ├── requirements.txt               # Dependencias de producción
│   ├── render.yaml                    # Config de despliegue en Render
│   ├── .env.example                   # Variables de entorno necesarias
│   └── SETUP_WHATSAPP.md              # Guía de configuración
│
└── Imágenes de muestra
    ├── camioneta.png, chevrolet.jpg
    ├── kwid.jpeg, renault.png, suv.png
    └── IMG_8185.jpg
```

---

## 4. Orden de Ejecución

Para reproducir el sistema completo desde cero:

```bash
# 1. Aplicar el esquema base (primera entrega)
#    → ya existente en Supabase

# 2. Correcciones al esquema
psql supabase_url -f 01_correcciones_modelo.sql

# 3. Tablas del experimento
psql supabase_url -f entrega_2.sql

# 4. Capa multimodal
psql supabase_url -f 04_multimodal.sql

# 5. Generar embeddings de texto (3 estrategias)
python pipeline_embeddings.py

# 6. Evaluar el experimento y guardar resultados
python evaluar_experimento.py

# 7. Crear la vista de resultados
psql supabase_url -f 02_ground_truth_experimento.sql

# 8. Generar embeddings de imágenes (CLIP)
python pipeline_multimodal.py

# 9. Ver la demo completa de 7 capacidades
python demo_consultas.py

# 10. Lanzar el bot de WhatsApp en producción
cd chatbot && uvicorn chat_whatsapp:app --host 0.0.0.0 --port 8000
```

---

## 5. Lo Que el Sistema Resuelve (Capacidades Demostradas)

| # | Tipo de consulta | Tecnología | Ejemplo |
|---|---|---|---|
| 1 | SQL pura | B-tree index | SUVs disponibles < $35M ordenadas por km |
| 2 | Texto → texto semántico | BGE-M3 + pgvector HNSW | "carro confiable para mi familia que gaste poco" |
| 3 | Híbrida (SQL + vectorial) | WHERE relacional + ORDER BY vectorial | "camioneta cómoda < 35M con < 60.000 km" |
| 4 | Texto → imagen | CLIP multilingual | "SUV rojo" → foto del catálogo más cercana |
| 5a | Imagen → texto | CLIP | Foto del cliente → etiqueta descriptiva más afín |
| 5b | Imagen → imagen | CLIP | Foto del cliente → vehículo visualmente más similar |
| 6 | Comparación de chunking | Experimento controlado | Semantic > sentence-aware > fixed-size |
| 7 | Bot WhatsApp end-to-end | FastAPI + Groq + Meta API | Conversación real desde WhatsApp |

---

## 6. Ideas para Escalar, Mejorar y Hacer el Producto Vendible

### 6.1 Mejoras inmediatas (bajo costo, alto impacto)

**Memoria conversacional por cliente**
Actualmente cada mensaje es independiente. Guardar los últimos N turnos por número de teléfono en Redis o en la tabla `busqueda_filtrada` (ya existe) permitiría que el bot recuerde *"como te decía antes sobre el Mazda CX-5..."* sin que el cliente lo repita. Una sesión con memoria de 5 turnos cuesta ~3 KB por cliente.

**Filtros de precio inteligentes**
El sistema ya detecta *"menos de 30 millones"*, pero no detecta rangos (*"entre 20 y 35 millones"*) ni abreviaciones regionales (*"30 palos"*, *"treinta kilos"*). Esto es solo ampliar las expresiones regulares en `extract_sql_filters`.

**Búsqueda por foto de WhatsApp**
El pipeline multimodal ya existe. Falta conectarlo al webhook: cuando el cliente envía una imagen en lugar de texto, descargar la imagen vía la API de Meta, generar su embedding CLIP y ejecutar la búsqueda imagen→imagen. Tres líneas adicionales en `receive_message()`.

**Notificaciones proactivas**
La tabla `notificacion` ya está diseñada. Con un cron job diario se puede avisar a clientes cuya negociación lleva más de X días sin respuesta, o notificar cuando llega un vehículo que coincide con una búsqueda previa registrada en `busqueda_filtrada`.

### 6.2 Escalabilidad técnica

**De Supabase free a producción real**
El tier gratuito de Supabase tiene 500 MB de base de datos y pgvector habilitado. Con 150 vehículos y 1024 dim por embedding, el índice HNSW ocupa ~50 MB. Para una concesionaria real con 500-2000 vehículos, el plan Pro de Supabase ($25/mes) es suficiente.

**Del modelo local a una API**
BAAI/bge-m3 corre en CPU pero consume ~570 MB de RAM — el límite del plan gratuito de Render. Para escalar sin subir de plan: alojar el modelo en Hugging Face Inference Endpoints (~$0.06/hora) o usar la API de embeddings de Cohere (multilingüe, pago por uso). El modelo local es la elección correcta para este proyecto académico, pero en producción la API es más predecible.

**Pool de conexiones**
El chatbot ya usa `psycopg2.pool.SimpleConnectionPool(1, 5)`. Para alta concurrencia (muchos mensajes simultáneos), `asyncpg` con un pool async es más eficiente. En el nivel de tráfico de una concesionaria mediana (decenas de mensajes/hora, no miles), el pool actual es suficiente.

**Re-ranking post-retrieval**
El sistema devuelve top-4 por similitud coseno. Un segundo pasaje con un modelo cross-encoder (que compara query + chunk directamente en lugar de embeddings separados) puede elevar la precisión. `cross-encoder/ms-marco-MiniLM-L-6-v2` es gratuito y mejora el ranking en ~5-10 puntos de precisión.

### 6.3 Extensiones de dominio (hacer el producto más completo)

**CRM integrado**
La estructura relacional ya tiene `cliente`, `negociacion_precio`, `turno_negociacion`, `cita`. Añadir una interfaz web simple (Streamlit o Next.js) que muestre el pipeline de ventas por asesor (tipo Kanban), con los vehículos en cada etapa, convertiría esto en un CRM funcional para la concesionaria.

**Retoma con valoración automática**
La tabla `retoma` registra el vehículo que el cliente entrega. Con un modelo de regresión entrenado sobre precios de vehículos usados en Colombia (datos de ML.com.co o TuCarro.com), el sistema podría dar una valoración automática inicial: *"Su Toyota Corolla 2019 con 45.000 km tiene un valor estimado de retoma de $42-46 millones"*.

**Comparador semántico de vehículos**
*"¿Qué diferencia hay entre el Mazda CX-5 y el Chevrolet Tracker?"* La tabla `vec_vehiculo_equipamiento` ya indexa equipamiento. Una consulta que recupera ambos documentos y los pasa al LLM como contexto genera una comparación en lenguaje natural sin que el desarrollador tenga que escribir lógica de comparación.

**Multi-concesionaria (SaaS)**
El esquema está diseñado para una sola concesionaria, pero añadir una tabla `concesionaria` con `id_concesionaria` como FK en `vehiculo`, `cliente`, `administrador`, etc., convierte el sistema en multi-tenant. Cada concesionaria tendría su propio chatbot de WhatsApp apuntando al mismo backend con filtro por `id_concesionaria`.

### 6.4 Aplicabilidad a otros dominios

Este sistema no es específico de vehículos. El patrón (base de datos relacional + pgvector + embeddings + chatbot en canal de mensajería) aplica directamente a:

| Dominio | Catálogo | Canal | Problema que resuelve |
|---|---|---|---|
| **Finca raíz** | Propiedades (barrio, m², precio, estrato) | WhatsApp / Instagram | "Aparto cerca al centro con parqueadero" |
| **Turismo** | Planes, hoteles, destinos | WhatsApp | "Algo para una luna de miel en el Eje Cafetero" |
| **Repuestos automotores** | Piezas con referencia, compatibilidad, precio | WhatsApp | "¿Tienen el filtro de aceite del Corolla 2018?" |
| **Salud** | Médicos, especialidades, disponibilidad | WhatsApp | "Traumatólogo que atienda los sábados" |
| **E-commerce B2B** | Catálogo de productos con especificaciones técnicas | WhatsApp / Telegram | "Tornillo M8 inox grado 8 en lote de 500" |

La arquitectura cambia: las tablas relacionales se adaptan al dominio, los textos que se vectorizan son las fichas del producto, y el LLM genera respuestas en el lenguaje del negocio. El núcleo (pgvector + búsqueda híbrida + webhook) es el mismo.

### 6.5 Pasos para hacerlo vendible

**Versión 1 — Producto mínimo vendible (2-4 semanas)**

1. Panel de administración web para cargar/editar el catálogo de vehículos sin tocar SQL.
2. Dashboard simple que muestra conversaciones activas, conversiones y métricas básicas (consultas por día, vehículos más buscados).
3. Script de onboarding automatizado: la concesionaria entrega su Excel de catálogo → el sistema lo importa, genera los embeddings y configura el bot.
4. Pricing: $150-300 USD/mes por concesionaria, con un onboarding de $500.

**Versión 2 — Producto competitivo (2-3 meses)**

1. Soporte para mensajes de voz (WhatsApp) → Whisper ASR → mismo pipeline RAG → respuesta de texto o voz.
2. Integración con sistemas de gestión de concesionarias existentes (SoftLand, JD Edwards) vía API para sincronizar el inventario automáticamente.
3. Analytics de intención: qué preguntan más los clientes, qué vehículos generan más interés pero no convierten, por qué los clientes se van sin comprar.
4. A/B testing de prompts: medir qué respuestas del LLM generan más conversaciones que terminan en cita.

**Versión 3 — Barrera competitiva (6+ meses)**

1. Fine-tuning del LLM con transcripciones reales de asesores de la concesionaria → el bot habla exactamente como los mejores vendedores de la empresa.
2. Score de propensión a compra: basado en el historial de interacciones, negociaciones y búsquedas, predecir qué clientes están a punto de convertir y alertar al asesor para que intervenga.
3. Marketplace multi-concesionaria: los clientes buscan en varias concesionarias desde un solo punto de entrada, y las concesionarias compiten por el cliente en tiempo real.

---

## 7. Lecciones Técnicas Clave

**La consulta híbrida es el corazón del sistema.** SQL exacto y búsqueda vectorial no son alternativas — son complementarias. El WHERE garantiza las restricciones duras del negocio (precio, disponibilidad, marca exacta) y el ORDER BY vectorial ordena por relevancia semántica real. Ninguna capa basta sola.

**La estrategia de chunking importa más de lo que parece.** Para fichas cortas (20-60 tokens), fragmentar empeora la recuperación porque rompe la unidad semántica natural. La estrategia óptima depende del dominio, no de una regla universal. El experimento documentado en este proyecto provee evidencia empírica para ese dominio específico.

**CLIP es la puerta de entrada a la búsqueda visual sin infraestructura propia.** Dos modelos públicos y gratuitos (clip-ViT-B-32 + su variante multilingual) habilitan texto→imagen e imagen→imagen en el mismo espacio vectorial, almacenados en PostgreSQL. No se necesita un sistema de búsqueda de imágenes dedicado.

**pgvector + PostgreSQL es suficiente hasta ~1M de vectores.** Para el 99% de las concesionarias de Colombia, pgvector con índice HNSW supera ampliamente sus necesidades. Las alternativas dedicadas (Pinecone, Weaviate, Qdrant) aportan valor a escala de decenas de millones de vectores o con requisitos de latencia de milisegundos a escala masiva.

**El canal donde está el cliente es el canal correcto.** Los colombianos están en WhatsApp. Un sistema tecnológicamente inferior pero disponible en WhatsApp supera a uno superior disponible solo como app o web. La integración con la Meta Business API es la decisión de distribución más importante del sistema.

---

*Proyecto académico — Bases de Datos Relacionales · 2026*
