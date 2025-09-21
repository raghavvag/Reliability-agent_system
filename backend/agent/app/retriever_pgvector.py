from config import DATABASE_URL, EMBED_MODEL_NAME
from sentence_transformers import SentenceTransformer
import psycopg2
from typing import List, Dict

# lazy-load model
_model = None
def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL_NAME)
    return _model

def embed_text(text: str) -> List[float]:
    model = get_model()
    emb = model.encode(text, show_progress_bar=False, normalize_embeddings=True)
    # convert to Python list of floats
    return emb.tolist() if hasattr(emb, "tolist") else list(emb)

def _to_pgvector_literal(emb: List[float]) -> str:
    return "[" + ",".join(map(str, emb)) + "]"

def search_similar(query_text: str, top_k: int = 3) -> List[Dict]:
    q_emb = embed_text(query_text)
    q_literal = _to_pgvector_literal(q_emb)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    sql = f"""
      SELECT id, summary, labels, service, incident_type, model, dim, embedding <=> %s AS distance
      FROM memory_item
      ORDER BY embedding <=> %s
      LIMIT %s
    """
    cur.execute(sql, (q_literal, q_literal, top_k))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    results = []
    for r in rows:
        results.append({
            "memory_id": r[0],
            "summary": r[1],
            "labels": r[2],
            "service": r[3],
            "incident_type": r[4],
            "model": r[5],
            "dim": r[6],
            "distance": float(r[7])
        })
    return results
