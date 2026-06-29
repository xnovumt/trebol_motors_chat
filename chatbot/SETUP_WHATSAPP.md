# Configuración del Bot de WhatsApp — Trébol Motors

## OPCIÓN A — Demo local con ngrok (recomendada para sustentación)
*Tiempo de configuración: ~10 minutos. No requiere despliegue en la nube.*

### Paso 1 — Instalar dependencias
```bash
cd chatbot
pip install -r requirements.txt
```

### Paso 2 — Configurar variables de entorno
```bash
# Copiar el archivo de ejemplo
cp .env.example .env

# Editar .env con tus valores reales:
# DATABASE_URL  → tu URI de Supabase (ya la tienes)
# WA_TOKEN      → el token de acceso de tu app en Meta
# PHONE_NUMBER_ID → el ID del número en Meta → WhatsApp → API Setup
# VERIFY_TOKEN  → escribe cualquier string, ej: "trebol2026"
# GROQ_API_KEY  → créalo gratis en https://console.groq.com
```

### Paso 3 — Instalar y autenticar ngrok
1. Descarga ngrok en https://ngrok.com/download
2. Crea una cuenta gratuita en ngrok.com
3. Ejecuta: `ngrok config add-authtoken TU_TOKEN_DE_NGROK`

### Paso 4 — Levantar el servidor y el túnel
Abre **dos terminales**:

**Terminal 1:**
```bash
cd chatbot
python chat_whatsapp.py
```
Espera a ver: `✓ Modelo listo` y `✓ Pool listo` (puede tomar ~30s la primera vez)

**Terminal 2:**
```bash
ngrok http 8000
```
Ngrok mostrará algo como:
```
Forwarding  https://abc123def456.ngrok-free.app  →  http://localhost:8000
```
Copia esa URL HTTPS.

### Paso 5 — Configurar el webhook en Meta
1. Ve a https://developers.facebook.com → tu app → WhatsApp → Configuración
2. En la sección **Webhook**, haz clic en **Editar**
3. **URL de devolución de llamada**: `https://abc123def456.ngrok-free.app/webhook`
4. **Token de verificación**: el mismo valor que pusiste en `VERIFY_TOKEN` de tu `.env`
5. Haz clic en **Verificar y guardar**

Si la verificación es exitosa, Meta mostrará un check verde ✓

### Paso 6 — Suscribir al evento de mensajes
En la misma pantalla de Webhook, activa la suscripción a:
- `messages` ✓

### Paso 7 — Probar
Envía un mensaje de WhatsApp al número de prueba de tu app. Deberías ver:
- En Terminal 1: el log del mensaje recibido y procesado
- En tu WhatsApp: la respuesta del bot

---

## OPCIÓN B — Despliegue en Render (producción)
*Úsala después de que la demo local funcione.*

### Problema que tuviste con Render
La razón más común por la que el webhook falla en Render:

| Causa | Fix |
|---|---|
| El servidor no escucha en `0.0.0.0:$PORT` | ✓ Ya corregido en `chat_whatsapp.py` |
| El webhook GET devuelve JSON en lugar de texto plano | ✓ Ya corregido con `PlainTextResponse` |
| Render free tier duerme después de 15 min | El primer mensaje puede demorar 30-60s |
| El modelo bge-m3 excede la RAM del free tier | Ver alternativa abajo |

### Pasos para Render

1. **Subir el código a GitHub** (solo la carpeta `chatbot/`):
   ```bash
   git init
   git add .
   git commit -m "Trébol Motors WhatsApp bot"
   git remote add origin https://github.com/TU_USUARIO/trebol-motors-bot.git
   git push -u origin main
   ```

2. En https://render.com → New → Web Service → conecta el repo

3. Configuración del servicio:
   - **Root Directory**: `chatbot`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn chat_whatsapp:app --host 0.0.0.0 --port $PORT`

4. En **Environment Variables**, agrega las 5 variables de tu `.env`

5. Haz Deploy. La URL de Render será: `https://trebol-motors-bot.onrender.com`

6. Configura ese URL + `/webhook` en Meta igual que el Paso 5 de ngrok

### Si Render free tier no alcanza la RAM para bge-m3
Render free = 512 MB. bge-m3 requiere ~600 MB en RAM.

**Alternativa sin costo**: usar la API de Hugging Face para generar embeddings remotamente:

```python
# En lugar de: state["model"] = SentenceTransformer("BAAI/bge-m3")
# Usar:
import requests

def get_embedding_hf(text: str) -> list:
    HF_TOKEN = os.getenv("HF_TOKEN")  # Token gratuito de huggingface.co
    r = requests.post(
        "https://api-inference.huggingface.co/models/BAAI/bge-m3",
        headers={"Authorization": f"Bearer {HF_TOKEN}"},
        json={"inputs": text}
    )
    return r.json()[0]  # vector de 1024 dimensiones
```

Esto elimina la carga del modelo en el servidor y funciona dentro de los 512 MB de Render free.

---

## Variables de entorno — dónde obtenerlas

| Variable | Dónde la encuentras |
|---|---|
| `DATABASE_URL` | **Usar el pooler IPv4** (la conexión directa `db.*.supabase.co` es solo IPv6 y falla en esta red): `postgresql://postgres.nbviaqyuovdnualudvcg:PASSWORD@aws-1-us-west-2.pooler.supabase.com:5432/postgres` |
| `WA_TOKEN` | Meta Developers → tu app → WhatsApp → API Setup → sección "Temporary access token" o usa un token permanente del sistema |
| `PHONE_NUMBER_ID` | Meta Developers → tu app → WhatsApp → API Setup → sección "Phone Number ID" |
| `VERIFY_TOKEN` | Tú lo inventas (cualquier string sin espacios) |
| `GROQ_API_KEY` | https://console.groq.com → API Keys → Create API Key (gratis) |
| `HF_TOKEN` (opcional) | https://huggingface.co → Settings → Access Tokens (gratis) |

---

## Flujo de una consulta en el bot (para la sustentación)

```
Cliente escribe: "busco un SUV automático de menos de 30 millones"
                              ↓
              detect_intent() → "catalog"
                              ↓
           run_rag_pipeline(text)
             ├─ embed con bge-m3: [0.12, -0.05, ...] (1024 dim)
             ├─ extract_sql_filters: carroceria='suv', precio <= 30M
             ├─ SELECT ... FROM chunk_resultado_experimento
             │   WHERE id_experimento = 3   ← Estrategia semántica
             │   ORDER BY embedding <=> query_vector  ← pgvector
             │   LIMIT 4
             └─ resultado: Chevrolet Tracker, Mazda CX-5, Renault Duster...
                              ↓
               call_llm(contexto + consulta)
               → Groq/Llama-3 genera respuesta en español
                              ↓
         send_whatsapp_message(phone, respuesta)
```

Esto demuestra en vivo:
- Búsqueda vectorial con pgvector (embeddings reales de bge-m3)
- Combinación con filtros SQL relacionales
- RAG completo (Retrieval → contexto → Generation)
