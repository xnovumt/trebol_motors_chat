# 01 — Infraestructura y configuración de entorno

## Qué se hizo
Inicialización del repositorio Git y gestión segura de credenciales.

## Archivos clave

| Archivo | Propósito |
|---|---|
| `.gitignore` | Excluye `.env`, `__pycache__/`, PDFs y archivos de scratch |
| `.env.example` | Template con los nombres de las variables — sin valores reales |
| `.env` | Credenciales reales — **gitignoreado, nunca se sube** |
| `requirements.txt` | Dependencias para los scripts standalone (pipeline, evaluación) |

## Cómo replicar el entorno

```bash
# 1. Clonar el repo
git clone https://github.com/xnovumt/trebol_motors_chat.git
cd trebol_motors_chat

# 2. Crear entorno virtual (opcional pero recomendado)
python -m venv venv
source venv/Scripts/activate   # Windows
# source venv/bin/activate     # Mac/Linux

# 3. Instalar dependencias
pip install -r requirements.txt          # scripts standalone
pip install -r chatbot/requirements.txt  # bot FastAPI

# 4. Configurar credenciales
cp .env.example .env
# Editar .env con las credenciales reales de Supabase
```

## Variables de entorno requeridas

| Variable | Descripción | Dónde obtenerla |
|---|---|---|
| `DATABASE_URL` | Cadena de conexión PostgreSQL a Supabase (pooler IPv4) | Supabase Dashboard → Project Settings → Database → Connection String (Session mode) |
| `WA_TOKEN` | Token permanente de la app de Meta | Meta for Developers → WhatsApp → API Setup |
| `PHONE_NUMBER_ID` | ID del número de WhatsApp Business | Mismo panel de Meta |
| `VERIFY_TOKEN` | Token arbitrario para validar el webhook | Lo defines tú |
| `GROQ_API_KEY` | API key de Groq (LLM gratuito) | console.groq.com |

## Decisiones tomadas
- **Pooler IPv4**: la URL directa de Supabase (`db.*.supabase.co`) es solo IPv6. Se usa el pooler `aws-1-us-west-2.pooler.supabase.com` que acepta IPv4.
- **Fallback DNS-over-HTTPS**: el DNS del ISP local era intermitente durante desarrollo. `db_conexion.py` tiene un fallback que resuelve via `8.8.8.8` directamente si el DNS del sistema falla.
- **python-dotenv**: tanto los scripts standalone como el bot FastAPI leen el `.env` con `load_dotenv()` antes de cualquier conexión.
