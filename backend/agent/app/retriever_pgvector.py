from config import DATABASE_URL, EMBED_MODEL_NAME
import psycopg
from typing import List, Dict
import os
from pathlib import Path

# Get the local models directory
MODELS_DIR = Path(__file__).parent.parent / "models"

# lazy-load model and sentence transformers import
_model = None
_model_loading_failed = False

def get_model():
    global _model, _model_loading_failed
    
    if _model_loading_failed:
        raise RuntimeError("Model loading previously failed")
    
    if _model is None:
        try:
            print(f"🤖 Loading sentence transformer module...")
            
            # Import with warnings suppressed for Windows numpy compatibility
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=RuntimeWarning)
                warnings.filterwarnings("ignore", message=".*MINGW-W64.*")
                warnings.filterwarnings("ignore", message=".*experimental.*")
                
                from sentence_transformers import SentenceTransformer
                
                # Try to load from local models directory first
                if MODELS_DIR.exists():
                    print(f"📁 Loading model from local cache: {MODELS_DIR}")
                    _model = SentenceTransformer(EMBED_MODEL_NAME, cache_folder=str(MODELS_DIR))
                else:
                    print(f"🌐 Loading model from HuggingFace: {EMBED_MODEL_NAME}")
                    _model = SentenceTransformer(EMBED_MODEL_NAME)
                
                print("✅ Model loaded successfully")
                
        except Exception as e:
            _model_loading_failed = True
            print(f"❌ Failed to load sentence transformer model: {e}")
            raise RuntimeError(f"Model loading failed: {e}")
    
    return _model

def embed_text(text: str) -> List[float]:
    try:
        model = get_model()
        
        # Import numpy warnings suppression
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            warnings.filterwarnings("ignore", message=".*MINGW-W64.*")
            
            emb = model.encode(text, show_progress_bar=False, normalize_embeddings=True)
            
        # convert to Python list of floats
        return emb.tolist() if hasattr(emb, "tolist") else list(emb)
        
    except Exception as e:
        print(f"❌ Error embedding text: {e}")
        # Return a dummy embedding to prevent total failure
        return [0.0] * 384

def _to_pgvector_literal(emb: List[float]) -> str:
    return "[" + ",".join(map(str, emb)) + "]"

def search_similar(query_text: str, top_k: int = 3) -> List[Dict]:
    if not query_text or not isinstance(query_text, str):
        print("Invalid query_text for similarity search")
        return []
    
    if not isinstance(top_k, int) or top_k <= 0:
        top_k = 3
        
    try:
        print(f"🔍 Searching for similar incidents: '{query_text[:50]}...'")
        q_emb = embed_text(query_text)
        
        # Check if we got a dummy embedding (all zeros)
        if all(x == 0.0 for x in q_emb):
            print("⚠️ Model loading failed, returning empty results")
            return []
        
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
        
        print(f"✅ Found {len(results)} similar incidents")
        return results
        
    except Exception as e:
        print(f"❌ Error in similarity search: {e}")
        return []
