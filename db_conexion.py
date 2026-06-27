"""
db_conexion.py
==============
Conexión robusta a Supabase para Trébol Motors.

Problemas que resuelve:
1. La conexión directa db.*.supabase.co es SOLO IPv6 → se usa el
   pooler aws-1-us-west-2.pooler.supabase.com (IPv4).
2. El DNS del ISP es intermitente → si la resolución falla, se
   obtiene la IP vía DNS-over-HTTPS (Google, consultado directamente
   por IP 8.8.8.8, sin depender del DNS local) y se conecta con
   el parámetro hostaddr de libpq, que omite la resolución DNS.

Uso:
    from db_conexion import conectar
    conn = conectar()
"""

import json
import os
import time
import urllib.parse
import urllib.request

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Parámetros de conexión — leídos de DATABASE_URL en .env (ver .env.example)
_url = urllib.parse.urlparse(os.environ["DATABASE_URL"])
DB_HOST = _url.hostname
DB_PORT = _url.port or 5432
DB_USER = urllib.parse.unquote(_url.username or "")
DB_PASS = urllib.parse.unquote(_url.password or "")
DB_NAME = _url.path.lstrip("/") or "postgres"

REINTENTOS = 3


def _resolver_doh(hostname: str) -> str | None:
    """Resuelve un hostname a IPv4 usando DNS-over-HTTPS de Google.
    Se consulta 8.8.8.8 directamente por IP, así que funciona aunque
    el DNS local esté caído."""
    url = f"https://8.8.8.8/resolve?name={hostname}&type=A"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        for answer in data.get("Answer", []):
            if answer.get("type") == 1:  # registro A
                return answer["data"]
    except Exception as e:
        print(f"  (DoH también falló: {e})")
    return None


def conectar() -> psycopg2.extensions.connection:
    """Conecta a Supabase con reintentos y fallback de DNS."""
    ultimo_error = None

    for intento in range(1, REINTENTOS + 1):
        # Intento normal (DNS del sistema)
        try:
            return psycopg2.connect(
                host=DB_HOST, port=DB_PORT, user=DB_USER,
                password=DB_PASS, dbname=DB_NAME,
                connect_timeout=15, sslmode="require",
            )
        except psycopg2.OperationalError as e:
            ultimo_error = e
            es_dns = "translate host name" in str(e)
            print(f"  Intento {intento}/{REINTENTOS} falló"
                  + (" (DNS)" if es_dns else f": {str(e).splitlines()[0]}"))

            # Si es fallo de DNS: resolver via DoH y conectar por IP
            if es_dns:
                ip = _resolver_doh(DB_HOST)
                if ip:
                    print(f"  DNS alterno resolvió {DB_HOST} -> {ip}")
                    try:
                        return psycopg2.connect(
                            host=DB_HOST, hostaddr=ip, port=DB_PORT,
                            user=DB_USER, password=DB_PASS, dbname=DB_NAME,
                            connect_timeout=15, sslmode="require",
                        )
                    except psycopg2.OperationalError as e2:
                        ultimo_error = e2
                        print(f"  Conexión por IP falló: {str(e2).splitlines()[0]}")

        time.sleep(2 * intento)  # backoff: 2s, 4s, 6s

    raise ultimo_error
