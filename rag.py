#!/usr/bin/env python3
"""Local RAG over documents — 100% local, $0 cost, runs on Ollama.

The shared backend for the monetizable projects in CONTEXTO_IA.md:
freelance RAG demo (#1) and vertical chat-with-docs SaaS (#2/#3).

Models (already pulled): nomic-embed-text (embeddings) + phi3-64k (answers).
Vector store is a local JSON file — no Supabase/cloud needed to demo.
Swap the store for Supabase pgvector later; the interface is just
embed() + cosine top-k.

Usage:
  python rag.py ingest <folder>          # index .txt/.md files
  python rag.py ask "your question"      # retrieve + answer
  python rag.py selftest                 # offline check (no models needed)

ponytail: .txt/.md only; add pypdf for PDFs when a real doc needs it.
ponytail: JSON store + linear scan, O(n) per query. Fine to thousands of
          chunks; move to Supabase pgvector/hnsw when corpus outgrows RAM.
"""
import sys, os, json, math, glob, urllib.request

OLLAMA = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
GEN_MODEL = "phi3-64k"
STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag_store.json")
CHUNK_WORDS = 220        # ~roughly a paragraph; small enough for precise retrieval
CHUNK_OVERLAP = 40       # carry context across chunk boundaries
TOP_K = 4


def _post(path, payload, timeout=600):
    req = urllib.request.Request(
        OLLAMA + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def embed(text):
    return _post("/api/embeddings", {"model": EMBED_MODEL, "prompt": text})["embedding"]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def chunk(text):
    words = text.split()
    step = CHUNK_WORDS - CHUNK_OVERLAP
    for i in range(0, len(words), step):
        piece = words[i:i + CHUNK_WORDS]
        if piece:
            yield " ".join(piece)
        if i + CHUNK_WORDS >= len(words):
            break


def ingest(folder):
    files = glob.glob(os.path.join(folder, "**", "*.txt"), recursive=True) + \
            glob.glob(os.path.join(folder, "**", "*.md"), recursive=True)
    if not files:
        sys.exit(f"No .txt/.md files found under {folder}")
    store = []
    for path in files:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        for c in chunk(text):
            store.append({"source": os.path.relpath(path, folder),
                          "text": c, "embedding": embed(c)})
            print(f"  embedded chunk from {os.path.basename(path)} "
                  f"({len(store)} total)", end="\r")
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(store, f)
    print(f"\nIndexed {len(store)} chunks from {len(files)} files -> {STORE}")


def ask(question):
    if not os.path.exists(STORE):
        sys.exit("No index yet. Run: python rag.py ingest <folder>")
    with open(STORE, encoding="utf-8") as f:
        store = json.load(f)
    qv = embed(question)
    ranked = sorted(store, key=lambda c: cosine(qv, c["embedding"]), reverse=True)
    hits = ranked[:TOP_K]
    context = "\n\n".join(f"[{i+1}] ({h['source']})\n{h['text']}"
                          for i, h in enumerate(hits))
    prompt = (
        "Answer the question using ONLY the context below. "
        "If the answer is not in the context, say you don't know. "
        "Cite sources as [n].\n\n"
        f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
    )
    resp = _post("/api/generate",
                 {"model": GEN_MODEL, "prompt": prompt, "stream": False})
    print(resp["response"].strip())
    print("\nSources:")
    for i, h in enumerate(hits):
        print(f"  [{i+1}] {h['source']}")


def selftest():
    # offline checks for the non-trivial logic: chunking + cosine
    words = " ".join(str(i) for i in range(500))
    chunks = list(chunk(words))
    assert len(chunks) > 1, "long text should split into multiple chunks"
    assert chunks[0].split()[-CHUNK_OVERLAP:] == chunks[1].split()[:CHUNK_OVERLAP], \
        "chunks must overlap"
    assert abs(cosine([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(cosine([1, 0], [0, 1])) < 1e-9
    assert cosine([1, 0], [0, 0]) == 0.0  # zero vector guard
    print("selftest OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "ingest" and len(sys.argv) == 3:
        ingest(sys.argv[2])
    elif cmd == "ask" and len(sys.argv) >= 3:
        ask(" ".join(sys.argv[2:]))
    elif cmd == "selftest":
        selftest()
    else:
        sys.exit(__doc__)
