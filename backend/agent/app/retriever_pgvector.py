from config import DATABASE_URL, EMBED_MODEL_NAME
import psycopg
from typing import List, Dict
import os
from pathlib import Path

# Get the local models directory
MODELS_DIR = Path(__file__).parent.parent / "models"

# lazy-load model and sentence transformers import
_model = None
def get_model():
    global _model
    if _model is None:
        print(f"🤖 Loading sentence transformer module...")
        from sentence_transformers import SentenceTransformer
        
        # Try to load from local models directory first
        if MODELS_DIR.exists():
            print(f"📁 Loading model from local cache: {MODELS_DIR}")
            _model = SentenceTransformer(EMBED_MODEL_NAME, cache_folder=str(MODELS_DIR))
        else:
            print(f"🌐 Loading model from HuggingFace: {EMBED_MODEL_NAME}")
            _model = SentenceTransformer(EMBED_MODEL_NAME)
        
        print("✅ Model loaded successfully")
    return _model

def embed_text(text: str) -> List[float]:
    model = get_model()
    emb = model.encode(text, show_progress_bar=False, normalize_embeddings=True)
    # convert to Python list of floats
    return emb.tolist() if hasattr(emb, "tolist") else list(emb)

def _to_pgvector_literal(emb: List[float]) -> str:
    return "[" + ",".join(map(str, emb)) + "]"

def search_similar(query_text: str, top_k: int = 3) -> List[Dict]:
    if not query_text or not isinstance(query_text, str):
        print("Invalid query_text for similarity search")
        return []
    
    if not isinstance(top_k, int) or top_k <= 0:
        top_k = 3
        
    try:
        q_emb = embed_text(query_text)
        conn = psycopg.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Use parameterized query to prevent SQL injection
        sql = """
          SELECT id, summary, labels, service, incident_type, model, dim, embedding <=> %s AS distance
          FROM memory_item
          ORDER BY embedding <=> %s
          LIMIT %s
        """
        cur.execute(sql, (q_emb, q_emb, top_k))
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
    except Exception as e:
        print(f"Error in similarity search: {e}")
        return []
