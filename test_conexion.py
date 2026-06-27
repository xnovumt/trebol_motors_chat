"""Prueba de conexión al pooler IPv4 de Supabase — sondea varios hosts."""
import psycopg2

HOSTS = [
    "aws-1-us-west-2.pooler.supabase.com",
    "aws-1-us-east-1.pooler.supabase.com",
    "aws-1-us-east-2.pooler.supabase.com",
    "aws-1-sa-east-1.pooler.supabase.com",
    "aws-0-us-east-1.pooler.supabase.com",
]

for host in HOSTS:
    uri = f"postgresql://postgres.nbviaqyuovdnualudvcg:GdSaS7pLpLCNxwZD@{host}:5432/postgres"
    try:
        conn = psycopg2.connect(uri, connect_timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vehiculo;")
        n_vehiculos = cur.fetchone()[0]
        print(f"EXITO en {host}")
        print(f"  vehiculos: {n_vehiculos}")
        print(f"\nURI CORRECTA:\n{uri}")
        conn.close()
        break
    except Exception as e:
        msg = str(e).split("\n")[0]
        print(f"fallo {host}: {msg}")
