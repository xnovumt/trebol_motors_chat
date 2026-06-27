"""Ejecuta un archivo .sql en Supabase usando la conexión robusta.
Uso: python ejecutar_sql.py 04_multimodal.sql"""

import sys

from db_conexion import conectar

archivo = sys.argv[1]
with open(archivo, encoding="utf-8") as f:
    sql = f.read()

print(f"Conectando a Supabase para ejecutar {archivo}...")
conn = conectar()
cursor = conn.cursor()
cursor.execute(sql)
conn.commit()
print(f"[OK] {archivo} ejecutado correctamente")
cursor.close()
conn.close()
