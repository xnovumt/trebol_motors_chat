"""
chat_whatsapp.py
================
Trébol Motors — Bot de WhatsApp con RAG
Autores: Juan Esteban Jiménez Vargas - Santiago Pérez Cardona

Webhook FastAPI que recibe mensajes de WhatsApp, ejecuta una búsqueda
vectorial + relacional sobre Supabase y responde vía la API de Meta.

Arquitectura del flujo:
  WhatsApp → Meta API → POST /webhook
    → detect_intent(texto)
    → rag_search(texto)        ← pgvector similarity sobre chunk_resultado_experimento
    → sql_filters(texto)       ← SQL relacional si hay filtros detectados
    → call_llm(contexto)       ← Groq / Llama-3 genera la respuesta
    → send_whatsapp(respuesta)
    → Meta API → WhatsApp
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import time
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import psycopg2
import psycopg2.pool
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

# ── Configuración ─────────────────────────────────────────────────────────────
SUPABASE_URI    = os.getenv("DATABASE_URL")
WA_TOKEN        = os.getenv("WA_TOKEN")          # Token permanente de Meta
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")   # ID del número de WhatsApp
VERIFY_TOKEN    = os.getenv("VERIFY_TOKEN")       # Token personalizado para el webhook
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")       # API key de Groq (gratuito)

# ── Estado global (cargado una sola vez al iniciar) ────────────────────────────
state: dict = {}


def _resolver_doh(hostname: str) -> Optional[str]:
    """Resuelve un hostname a IPv4 vía DNS-over-HTTPS de Google (8.8.8.8
    consultado directamente por IP). Funciona aunque el DNS local falle."""
    try:
        url = f"https://8.8.8.8/resolve?name={hostname}&type=A"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        for answer in data.get("Answer", []):
            if answer.get("type") == 1:
                return answer["data"]
    except Exception as e:
        print(f"DoH falló: {e}")
    return None


def crear_pool() -> psycopg2.pool.SimpleConnectionPool:
    """Crea el pool con reintentos y fallback de DNS (el DNS del ISP
    local es intermitente — ver db_conexion.py del proyecto)."""
    parsed = urllib.parse.urlparse(SUPABASE_URI)
    kwargs = dict(
        host=parsed.hostname, port=parsed.port or 5432,
        user=urllib.parse.unquote(parsed.username or ""),
        password=urllib.parse.unquote(parsed.password or ""),
        dbname=parsed.path.lstrip("/") or "postgres",
        sslmode="require", connect_timeout=15,
    )

    ultimo_error = None
    for intento in range(1, 4):
        try:
            return psycopg2.pool.SimpleConnectionPool(1, 5, **kwargs)
        except psycopg2.OperationalError as e:
            ultimo_error = e
            print(f"Pool intento {intento}/3 falló: {str(e).splitlines()[0]}")
            if "translate host name" in str(e):
                ip = _resolver_doh(parsed.hostname)
                if ip:
                    print(f"DNS alterno: {parsed.hostname} -> {ip}")
                    try:
                        return psycopg2.pool.SimpleConnectionPool(
                            1, 5, hostaddr=ip, **kwargs)
                    except psycopg2.OperationalError as e2:
                        ultimo_error = e2
            time.sleep(2 * intento)
    raise ultimo_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Carga el modelo de embeddings y el pool de conexiones al iniciar el servidor."""
    print("... Cargando modelo BAAI/bge-m3 (1024 dim)...")
    state["model"] = SentenceTransformer("BAAI/bge-m3")
    print("[OK] Modelo listo")

    print("... Creando pool de conexiones a Supabase...")
    state["pool"] = crear_pool()
    print("[OK] Pool listo")

    yield  # el servidor corre aquí

    state["pool"].closeall()
    print("Pool de conexiones cerrado")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_FRONTEND = pathlib.Path(__file__).parent / "frontend" / "index.html"


@app.get("/ui")
async def frontend():
    return FileResponse(str(_FRONTEND))


# ── WEBHOOK — Verificación (GET) ───────────────────────────────────────────────
@app.get("/webhook")
async def verify_webhook(request: Request):
    """
    Meta llama este endpoint UNA VEZ al configurar el webhook.
    Si el verify_token coincide, responde con el challenge como texto plano.
    """
    params = dict(request.query_params)
    if (params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == VERIFY_TOKEN):
        return PlainTextResponse(params["hub.challenge"])
    return PlainTextResponse("Token inválido", status_code=403)


# ── WEBHOOK — Recepción de mensajes (POST) ────────────────────────────────────
@app.post("/webhook")
async def receive_message(request: Request):
    """
    Meta envía aquí todos los eventos: mensajes, confirmaciones de lectura,
    estados de entrega, etc. Solo procesamos eventos de texto entrante.
    """
    body = await request.json()

    try:
        entry = body["entry"][0]["changes"][0]["value"]
        message = entry["messages"][0]

        # Solo procesar mensajes de texto
        if message.get("type") != "text":
            return {"status": "ok"}

        phone = message["from"]        # "573001234567"
        text  = message["text"]["body"].strip()

    except (KeyError, IndexError):
        # Meta envía delivery receipts y otros eventos sin campo "messages"
        return {"status": "ok"}

    # ── Pipeline principal ────────────────────────────────────────────────────
    intent   = detect_intent(text)
    response = await handle_intent(intent, text, phone)
    await send_whatsapp_message(phone, response)

    return {"status": "ok"}


# ── DETECCIÓN DE INTENCIÓN ────────────────────────────────────────────────────
INTENT_KEYWORDS = {
    "catalog":     ["busco", "quiero", "hay", "tienen", "disponible", "catálogo",
                    "vehículo", "carro", "coche", "auto", "camioneta", "suv",
                    "sedan", "pickup", "hatchback"],
    "negotiation": ["ofrezco", "oferto", "precio", "millones", "descuento",
                    "negoci", "rebaj", "cuánto", "cuanto", "vale", "cuesta"],
    "appointment": ["cita", "agendar", "visita", "test drive", "prueba",
                    "cuándo", "cuando", "horario", "disponibilidad"],
    "detail":      ["equipamiento", "características", "tiene", "incluye",
                    "motor", "cilindrada", "transmisión", "combustible",
                    "km", "kilometraje", "año", "color"],
    "greeting":    ["hola", "buenos", "buenas", "buen día", "saludo",
                    "ayuda", "información", "info"],
}

def detect_intent(text: str) -> str:
    text_lower = text.lower()
    scores = {intent: 0 for intent in INTENT_KEYWORDS}
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                scores[intent] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "catalog"


# ── ENRUTADOR DE INTENCIONES ──────────────────────────────────────────────────
async def handle_intent(intent: str, text: str, phone: str) -> str:
    if intent == "greeting":
        return (
            "👋 Hola, bienvenido a *Trébol Motors* en Manizales.\n\n"
            "Puedo ayudarte con:\n"
            "🚗 *Buscar vehículos* — escríbeme qué tipo de carro buscas\n"
            "💰 *Negociar precios* — dime tu oferta\n"
            "📅 *Agendar una cita* o test drive\n"
            "🔍 *Consultar detalles* de un vehículo específico\n\n"
            "¿Con qué te puedo ayudar?"
        )

    if intent == "negotiation":
        return await handle_negotiation(text, phone)

    if intent == "appointment":
        return (
            "📅 Para agendar tu cita, un asesor te contactará en breve.\n"
            "Puedes indicarme:\n"
            "• ¿Qué tipo de cita? (visita, test drive, evaluación de retoma)\n"
            "• ¿Qué vehículo te interesa?\n"
            "• ¿Qué días y horarios te vienen bien?\n\n"
            "Nuestro horario de atención es lunes a sábado 8am–6pm."
        )

    # Para catalog y detail: búsqueda RAG completa
    return await run_rag_pipeline(text)


# ── PIPELINE RAG PRINCIPAL ────────────────────────────────────────────────────
async def run_rag_pipeline(query: str) -> str:
    """
    1. Genera el embedding de la consulta con bge-m3
    2. Ejecuta búsqueda vectorial en chunk_resultado_experimento (estrategia semantic)
    3. Aplica filtros relacionales adicionales si se detectan en el texto
    4. Llama al LLM (Groq) para generar una respuesta en lenguaje natural
    """
    model: SentenceTransformer = state["model"]
    pool: psycopg2.pool.SimpleConnectionPool = state["pool"]

    # 1. Embedding de la consulta
    query_vector = model.encode(query).tolist()
    query_vector_str = json.dumps(query_vector)

    # 2. Filtros relacionales detectados en el texto
    sql_filters, params = extract_sql_filters(query)

    conn = pool.getconn()
    try:
        cur = conn.cursor()

        # 3a. Búsqueda vectorial sobre los chunks semánticos (estrategia 3, 1024 dim)
        #     Esto demuestra el uso real de pgvector con los embeddings del experimento
        cur.execute(f"""
            SELECT
                v.referencia,
                v.marca,
                v.linea,
                v.anio,
                v.carroceria,
                v.combustible,
                v.transmision,
                v.kilometraje,
                v.precio_venta,
                v.estado_vehiculo,
                cre.contenido_texto                              AS chunk,
                1 - (cre.vector_embedding <=> %s::vector)       AS similitud
            FROM chunk_resultado_experimento cre
            JOIN vehiculo v ON v.id_vehiculo = cre.id_vehiculo
            WHERE cre.id_experimento = 3          -- estrategia semantic (ficha completa)
              AND v.estado_vehiculo = 'disponible'
              {sql_filters}
            ORDER BY cre.vector_embedding <=> %s::vector
            LIMIT 4
        """, [query_vector_str] + params + [query_vector_str])

        results = cur.fetchall()

    finally:
        pool.putconn(conn)

    if not results:
        return (
            "Lo siento, no encontré vehículos disponibles con esas características en este momento.\n"
            "¿Quieres que registre una solicitud especial para buscarlo?"
        )

    # 4. Construir contexto para el LLM
    context_lines = []
    for r in results:
        ref, marca, linea, anio, carroceria, combustible, trans, km, precio, estado, chunk, sim = r
        context_lines.append(
            f"• {marca} {linea} {anio} | {carroceria.upper()} | {trans} | "
            f"{combustible} | {km:,} km | ${precio:,.0f} COP | [{ref}] (similitud: {sim:.2f})"
        )
    context = "\n".join(context_lines)

    # 5. Llamar al LLM
    prompt = f"""Eres el asistente virtual de Trébol Motors, concesionaria de vehículos en Manizales, Colombia.
Responde de forma amable, concisa y en español. Máximo 4 líneas. No uses markdown excesivo.
Usa SOLO los vehículos del catálogo proporcionado para hacer recomendaciones.

CATÁLOGO DISPONIBLE (ordenado por relevancia semántica a la consulta):
{context}

CONSULTA DEL CLIENTE:
{query}

RESPUESTA (máximo 4 líneas, menciona referencias de los vehículos recomendados):"""

    return await call_llm(prompt)


# ── DETECCIÓN DE FILTROS RELACIONALES ─────────────────────────────────────────
def extract_sql_filters(text: str) -> tuple[str, list]:
    """
    Detecta filtros estructurados en el texto del usuario:
    precios, kilometraje, marca, tipo de carrocería, combustible.
    Retorna (fragmento_sql, parámetros).
    """
    filters = []
    params = []
    text_lower = text.lower()

    # Filtro de kilometraje (< N km)
    km_match = re.search(r"menos de (\d[\d\.]*)\s*km", text_lower)
    if km_match:
        km_val = int(km_match.group(1).replace(".", ""))
        filters.append("AND v.kilometraje < %s")
        params.append(km_val)

    # Filtro de precio máximo (menos de / hasta N millones)
    price_match = re.search(r"(?:menos de|hasta|máximo)\s*(\d+)\s*(?:millones?)?", text_lower)
    if price_match:
        price_val = int(price_match.group(1)) * 1_000_000
        filters.append("AND v.precio_venta <= %s")
        params.append(price_val)

    # Filtro de marca
    for marca in ["mazda", "toyota", "chevrolet", "renault"]:
        if marca in text_lower:
            filters.append("AND LOWER(v.marca) = %s")
            params.append(marca)
            break

    # Filtro de carrocería
    for tipo in ["suv", "sedan", "pickup", "hatchback", "camioneta"]:
        if tipo in text_lower:
            filters.append("AND v.carroceria = %s")
            params.append(tipo)
            break

    # Filtro de combustible
    for comb in [("eléctrico", "electrico"), ("híbrido", "hibrido"),
                 ("diesel", "diesel"), ("gasolina", "gasolina")]:
        if comb[0] in text_lower or comb[1] in text_lower:
            filters.append("AND v.combustible = %s")
            params.append(comb[1])
            break

    return " ".join(filters), params


# ── MANEJO DE NEGOCIACIÓN ─────────────────────────────────────────────────────
async def handle_negotiation(text: str, phone: str) -> str:
    """
    Detecta montos de oferta en el mensaje y registra el turno de negociación.
    """
    amount_match = re.search(r"(\d[\d\.]*)\s*millones?", text.lower())
    if not amount_match:
        return (
            "Entendido. Para negociar el precio de un vehículo, dime:\n"
            "• ¿Qué vehículo te interesa? (puedes indicar la referencia REF-XXXX)\n"
            "• ¿Cuál es tu oferta en millones de pesos?"
        )

    monto = int(amount_match.group(1).replace(".", "")) * 1_000_000
    return (
        f"📋 Recibimos tu oferta de *${monto:,.0f} COP*.\n"
        "Un asesor revisará la propuesta y te responderá en breve.\n"
        "¿Hay algún otro detalle que quieras agregar a tu oferta?"
    )


# ── LLAMADA AL LLM (Groq — gratuito) ─────────────────────────────────────────
async def call_llm(prompt: str) -> str:
    """
    Llama a la API de Groq con el modelo llama-3.1-8b-instant.
    Si la llamada falla, devuelve una respuesta de plantilla.
    """
    if not GROQ_API_KEY:
        # Modo sin LLM: devolver el contexto directo
        return prompt.split("CATÁLOGO DISPONIBLE")[1].split("CONSULTA")[0].strip()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 400,
                    "temperature": 0.4,
                },
            )
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Error LLM: {e}")
        return (
            "Encontré estos vehículos disponibles para ti:\n\n"
            + prompt.split("CATÁLOGO DISPONIBLE\n")[1].split("\nCONSULTA")[0].strip()
        )


# ── ENVÍO DE MENSAJE DE WHATSAPP ──────────────────────────────────────────────
async def send_whatsapp_message(to: str, text: str):
    """
    Envía un mensaje de texto al número indicado usando la Graph API de Meta.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages",
            headers={
                "Authorization": f"Bearer {WA_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": text, "preview_url": False},
            },
        )
    if response.status_code != 200:
        print(f"Error enviando mensaje: {response.text}")


# ── Ruta de diagnóstico ───────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """
    Verifica que el servidor, el modelo y la BD estén listos.
    Abre https://TU-URL/health en el navegador para confirmar antes de configurar Meta.
    """
    pool: psycopg2.pool.SimpleConnectionPool = state.get("pool")
    if not pool:
        return {"status": "iniciando", "model": False, "db": False}

    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM chunk_resultado_experimento WHERE id_experimento = 3;")
        chunks_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM vehiculo WHERE estado_vehiculo = 'disponible';")
        vehiculos_count = cur.fetchone()[0]
    finally:
        pool.putconn(conn)

    return {
        "status": "ok",
        "model": "BAAI/bge-m3" if state.get("model") else "no cargado",
        "chunks_semanticos": chunks_count,
        "vehiculos_disponibles": vehiculos_count,
        "advertencia": (
            "EJECUTA pipeline_embeddings.py antes de usar el bot"
            if chunks_count == 0 else None
        ),
    }


# ── API REST para el frontend ─────────────────────────────────────────────────

@app.get("/api/vehiculos")
async def api_vehiculos(limit: int = 20, offset: int = 0):
    pool: psycopg2.pool.SimpleConnectionPool = state.get("pool")
    if not pool:
        return {"error": "servidor iniciando"}
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id_vehiculo, referencia, marca, linea, anio, carroceria,
                   combustible, transmision, kilometraje, precio_venta,
                   estado_vehiculo, color_exterior
            FROM vehiculo
            WHERE estado_vehiculo = 'disponible'
            ORDER BY id_vehiculo
            LIMIT %s OFFSET %s
        """, (limit, offset))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["precio_venta"] = int(r["precio_venta"]) if r["precio_venta"] else 0
            r["kilometraje"] = int(r["kilometraje"]) if r["kilometraje"] else 0
        return {"vehiculos": rows}
    finally:
        pool.putconn(conn)


@app.post("/api/buscar")
async def api_buscar(request: Request):
    body = await request.json()
    query = (body.get("query") or "").strip()
    if not query:
        return {"resultados": [], "query": ""}

    model: SentenceTransformer = state.get("model")
    pool: psycopg2.pool.SimpleConnectionPool = state.get("pool")
    if not model or not pool:
        return {"error": "servidor iniciando"}

    query_vector = json.dumps(model.encode(query).tolist())
    sql_filters, params = extract_sql_filters(query)

    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT
                v.id_vehiculo, v.referencia, v.marca, v.linea, v.anio,
                v.carroceria, v.combustible, v.transmision,
                v.kilometraje, v.precio_venta, v.estado_vehiculo,
                1 - (cre.vector_embedding <=> %s::vector) AS similitud
            FROM chunk_resultado_experimento cre
            JOIN vehiculo v ON v.id_vehiculo = cre.id_vehiculo
            WHERE cre.id_experimento = 3
              AND v.estado_vehiculo = 'disponible'
              {sql_filters}
            ORDER BY cre.vector_embedding <=> %s::vector
            LIMIT 8
        """, [query_vector] + params + [query_vector])
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["similitud"] = round(float(r["similitud"]), 4)
            r["precio_venta"] = int(r["precio_venta"]) if r["precio_venta"] else 0
            r["kilometraje"] = int(r["kilometraje"]) if r["kilometraje"] else 0
        return {"resultados": rows, "query": query}
    finally:
        pool.putconn(conn)


@app.get("/api/experimento")
async def api_experimento():
    pool: psycopg2.pool.SimpleConnectionPool = state.get("pool")
    if not pool:
        return {"error": "servidor iniciando"}
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM vw_resultados_experimento;")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            for k, v in r.items():
                if hasattr(v, "__float__"):
                    r[k] = float(v)
        return {"estrategias": rows}
    finally:
        pool.putconn(conn)


# ── Punto de entrada local ────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("chat_whatsapp:app", host="0.0.0.0", port=port, reload=False)
