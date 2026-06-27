# 04 — Bot WhatsApp con RAG pipeline

## Arquitectura

```
Cliente WhatsApp
    │
    ▼
Meta Graph API
    │  POST /webhook
    ▼
chatbot/chat_whatsapp.py  (FastAPI)
    │
    ├── detect_intent()          ← scoring por keywords (5 categorías)
    │
    └── handle_intent()
            │
            ├── greeting   → respuesta fija de bienvenida
            ├── appointment → respuesta fija de agendamiento
            ├── negotiation → handle_negotiation() (extrae monto con regex)
            │
            └── catalog / detail → run_rag_pipeline()
                    │
                    ├── model.encode(query)         ← BAAI/bge-m3 1024 dim
                    ├── extract_sql_filters(query)  ← regex → WHERE clauses
                    ├── pgvector <=> coseno query    ← chunk_resultado_experimento
                    └── call_llm(contexto)           ← Groq / llama-3.1-8b-instant
                            │
                            ▼
                    Meta Graph API → respuesta al cliente
```

## Endpoints FastAPI

| Endpoint | Método | Descripción |
|---|---|---|
| `/webhook` | GET | Verificación inicial del webhook de Meta |
| `/webhook` | POST | Recibe mensajes entrantes de WhatsApp |
| `/health` | GET | Estado del servidor, modelo y BD |
| `/ui` | GET | Sirve el frontend web (index.html) |
| `/api/vehiculos` | GET | Lista vehículos disponibles (paginado) |
| `/api/buscar` | POST | Búsqueda semántica + filtros SQL |
| `/api/experimento` | GET | Resultados del experimento de chunking |

## Variables de entorno del bot

Todas en `.env` (ver `docs/01_infraestructura.md`):
- `DATABASE_URL` — conexión a Supabase
- `WA_TOKEN` — autenticación con Meta API
- `PHONE_NUMBER_ID` — número de WhatsApp registrado
- `VERIFY_TOKEN` — validación del webhook
- `GROQ_API_KEY` — LLM gratuito (opcional; sin él responde el contexto directo)

## Despliegue

```bash
# Local
cd chatbot
uvicorn chat_whatsapp:app --reload
# Abre http://localhost:8000/ui

# Producción (Render)
# Ver chatbot/render.yaml y chatbot/SETUP_WHATSAPP.md
```

## Detección de intención

Keyword scoring (no ML). Cada mensaje suma puntos por categoría:

```
catalog:     busco, quiero, hay, vehículo, carro, suv, pickup...
negotiation: precio, millones, descuento, cuánto, vale...
appointment: cita, agendar, test drive, horario...
detail:      motor, transmisión, km, kilometraje, año...
greeting:    hola, buenos días, ayuda...
```

La categoría con más puntos gana. Sin puntos → `catalog` por defecto.
