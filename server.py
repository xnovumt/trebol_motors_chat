#!/usr/bin/env python3
"""Servidor web mínimo para el RAG de Supabase — stdlib, cero dependencias.

Sirve index.html y expone POST /api/ask {"question": "..."} -> {answer, sources}.
Reusa rag_supabase.build_answer (mismo .env, mismo modelo bge-m3).

Correr con el Python que tiene psycopg (3.14):
  "C:/Users/xnovu/AppData/Local/Programs/Python/Python314/python.exe" server.py
  -> abre http://localhost:8000

ponytail: un proceso, conexión a Postgres por request (suficiente para demo).
          Añade pool si hay concurrencia real.
"""
import sys, os, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import rag_supabase as rag

HERE = os.path.dirname(os.path.abspath(__file__))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/ask":
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            n = int(self.headers.get("Content-Length", 0))
            q = json.loads(self.rfile.read(n) or b"{}").get("question", "").strip()
        except Exception:
            return self._send(400, json.dumps({"error": "JSON inválido"}, ensure_ascii=False))
        if not q:
            return self._send(400, json.dumps({"error": "Pregunta vacía"}, ensure_ascii=False))
        try:
            res = rag.build_answer(q)
            self._send(200, json.dumps(res, ensure_ascii=False, default=str))
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False, default=str))

    def log_message(self, *a):  # silencio: no spamear la terminal
        pass


if __name__ == "__main__":
    rag.load_env()  # carga DATABASE_URL + EMBED_MODEL una sola vez
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"RAG web en http://localhost:{port}   (Ctrl+C para parar)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
