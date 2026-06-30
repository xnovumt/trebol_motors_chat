#!/usr/bin/env python3
"""RAG sobre tu base de datos Supabase (pgvector) — lectura directa.

Variante de rag.py que en vez de leer rag_store.json, consulta TU Supabase.
Auto-descubre la tabla vectorial, su dimensión y las columnas de texto:
no tienes que decirle nombres de tablas/columnas.

Credenciales: pon la cadena de conexión Postgres de Supabase en un .env
LOCAL (junto a este archivo). El código la lee; nunca se pega en el chat.

  .env:
    DATABASE_URL=postgresql://postgres.<ref>:<password>@<host>.pooler.supabase.com:5432/postgres

  (Supabase Dashboard → Project Settings → Database → Connection string →
   "Session pooler" o "Direct connection". Marca "Display password".)

Requisitos:  pip install "psycopg[binary]"   (Ollama ya corriendo, modelos ya pulled)

Uso:
  python rag_supabase.py schema           # qué tabla/columna/dimensión detectó
  python rag_supabase.py ask "pregunta"   # recupera de Supabase + responde
  python rag_supabase.py selftest         # check offline (sin DB ni modelos)

ponytail: conexión directa (sin RLS) — eres el dueño leyendo tu propia DB.
          Para multi-tenant SaaS, mueve la query a una función RPC con RLS.
ponytail: la query usa el índice de pgvector si existe (HNSW/IVFFlat);
          si no, hace seq-scan. Crea el índice cuando el corpus crezca.
"""
import sys, os, json, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OLLAMA = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"   # 768 dimensiones
GEN_MODEL = "phi3-64k"
EXPECTED_DIM = 768
TOP_K = 4


def load_env():
    p = os.path.join(HERE, ".env")
    if not os.path.exists(p):
        sys.exit(f"Falta {p}. Crea un .env con DATABASE_URL=postgresql://... (ver docstring).")
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    if not os.environ.get("DATABASE_URL"):
        sys.exit("El .env no define DATABASE_URL.")
    # El modelo de embedding y su dimensión deben coincidir con los vectores ya
    # guardados en la DB. Se pueden override desde el .env sin tocar código.
    global EMBED_MODEL, EXPECTED_DIM
    EMBED_MODEL = os.environ.get("EMBED_MODEL", EMBED_MODEL)
    EXPECTED_DIM = int(os.environ.get("EXPECTED_DIM", EXPECTED_DIM))


def _post(path, payload, timeout=600):
    req = urllib.request.Request(OLLAMA + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def embed(text):
    return _post("/api/embeddings", {"model": EMBED_MODEL, "prompt": text})["embedding"]


def to_vector_literal(vec):
    # pgvector espera el literal '[0.1,0.2,...]' (sin espacios), casteado a ::vector
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _connect():
    import psycopg  # import perezoso: selftest no lo necesita
    return psycopg.connect(os.environ["DATABASE_URL"])


def discover(conn):
    """Devuelve (schema, tabla, col_vector, dimension, [cols_texto])."""
    with conn.cursor() as cur:
        cur.execute("""
            select table_schema, table_name, column_name
            from information_schema.columns
            where udt_name = 'vector'
              and table_schema not in ('pg_catalog','information_schema')
            order by table_schema, table_name
        """)
        rows = cur.fetchall()
        if not rows:
            sys.exit("No encontré ninguna columna tipo 'vector' en tu DB. "
                     "¿Está creada la extensión pgvector y poblada la tabla?")
        sch, tab, vcol = rows[0]
        if len(rows) > 1:
            print(f"(varias tablas vectoriales; uso la primera: {sch}.{tab}.{vcol})",
                  file=sys.stderr)
        cur.execute(f'select vector_dims("{vcol}") from "{sch}"."{tab}" '
                    f'where "{vcol}" is not null limit 1')
        got = cur.fetchone()
        dim = got[0] if got else None
        cur.execute("""
            select column_name from information_schema.columns
            where table_schema = %s and table_name = %s and udt_name <> 'vector'
            order by ordinal_position
        """, (sch, tab))
        text_cols = [r[0] for r in cur.fetchall()]
    return sch, tab, vcol, dim, text_cols


def cmd_schema():
    load_env()
    with _connect() as conn:
        sch, tab, vcol, dim, cols = discover(conn)
    print(f"Tabla vectorial : {sch}.{tab}")
    print(f"Columna vector  : {vcol}  (dimensión = {dim})")
    print(f"Otras columnas  : {', '.join(cols)}")
    if dim != EXPECTED_DIM:
        print(f"\n⚠  Tu vector es de {dim} dims pero '{EMBED_MODEL}' produce {EXPECTED_DIM}.")
        print("   La búsqueda NO funcionará si el modelo no coincide. En el .env, pon")
        print(f"   el modelo que generó estos vectores (dim {dim}), p.ej.:")
        print(f"       EMBED_MODEL=mxbai-embed-large")
        print(f"       EXPECTED_DIM={dim}")
        print("   o re-indexa contenido_texto con un modelo local conocido.")
    else:
        print(f"\n✓  Dimensión coincide con nomic-embed-text. Listo para 'ask'.")
        print("   (Confirma con una query que sepas que está en tus docs.)")


def retrieve(conn, question):
    """Devuelve (cols, rows) — cada row trae las columnas + 'dist' al final."""
    sch, tab, vcol, dim, cols = discover(conn)
    if dim != EXPECTED_DIM:
        sys.exit(f"Dimensión {dim} != {EXPECTED_DIM} ('{EMBED_MODEL}'). "
                 "Corre 'schema' para ver opciones.")
    qv = to_vector_literal(embed(question))
    col_list = ", ".join(f'"{c}"' for c in cols)
    with conn.cursor() as cur:
        cur.execute(
            f'select {col_list}, "{vcol}" <=> %s::vector as dist '
            f'from "{sch}"."{tab}" order by dist limit %s',
            (qv, TOP_K))
        return cols, cur.fetchall()


def cmd_probe(question):
    # diagnóstico: ¿el modelo coincide? dist baja + texto relevante = sí.
    load_env()
    with _connect() as conn:
        cols, rows = retrieve(conn, question)
    txt_col = "contenido_texto" if "contenido_texto" in cols else cols[-1]
    ti = cols.index(txt_col)
    for r in rows:
        dist = r[-1]
        snippet = str(r[ti])[:160].replace("\n", " ") if r[ti] is not None else ""
        print(f"dist={dist:.4f}  {txt_col}: {snippet}")


def build_answer(question):
    """RAG completo -> dict {answer, sources}. Asume load_env() ya llamado.
    Reutilizado por el CLI (cmd_ask) y por server.py (API web)."""
    with _connect() as conn:
        cols, rows = retrieve(conn, question)
    hits = []
    for r in rows:
        fields = {cols[i]: r[i] for i in range(len(cols))}
        dist = r[len(cols)]  # 'dist' viene tras las columnas
        text = "  ".join(f"{k}: {v}" for k, v in fields.items() if v is not None)
        hits.append((fields, text, dist))
    context = "\n\n".join(f"[{i+1}] {t}" for i, (_, t, _) in enumerate(hits))
    prompt = ("Responde la pregunta usando SOLO el contexto. Si no está, dilo. "
              "Cita las fuentes como [n].\n\n"
              f"Contexto:\n{context}\n\nPregunta: {question}\nRespuesta:")
    resp = _post("/api/generate", {"model": GEN_MODEL, "prompt": prompt, "stream": False})
    sources = []
    for i, (fields, _, dist) in enumerate(hits):
        ids = {k: fields[k] for k in fields
               if k.startswith("id") and fields[k] is not None}
        sources.append({"n": i + 1, "ids": ids,
                        "texto": fields.get("contenido_texto"),
                        "dist": round(float(dist), 4)})
    return {"answer": resp["response"].strip(), "sources": sources}


def cmd_ask(question):
    load_env()
    res = build_answer(question)
    print(res["answer"])
    print("\nFuentes:")
    for s in res["sources"]:
        ids = "  ".join(f"{k}={v}" for k, v in s["ids"].items())
        print(f"  [{s['n']}] {ids or 'fila'}")


def selftest():
    # check offline del único punto frágil: el literal de pgvector
    assert to_vector_literal([1, 2, 3]) == "[1.0,2.0,3.0]"
    assert to_vector_literal([0.5, -0.25]) == "[0.5,-0.25]"
    assert " " not in to_vector_literal([1.0, 2.0])  # sin espacios -> ::vector válido
    print("selftest OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "schema":
        cmd_schema()
    elif cmd == "probe" and len(sys.argv) >= 3:
        cmd_probe(" ".join(sys.argv[2:]))
    elif cmd == "ask" and len(sys.argv) >= 3:
        cmd_ask(" ".join(sys.argv[2:]))
    elif cmd == "selftest":
        selftest()
    else:
        sys.exit(__doc__)
