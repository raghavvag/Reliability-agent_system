import json
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import REDIS_CHANNEL, SLACK_CHANNEL
from redis_client import get_redis_client, create_message_listener
from db import get_incident, update_incident_status, insert_audit_log, init_connection_pool
from retriever_pgvector import search_similar
from llm_client import ask_llm
from notifier import send_incident_message

redis_client = get_redis_client()

def handle_incident_message(data):
    try:
        print(f"📥 Raw message received: {type(data)} - {str(data)[:100]}...")
        
        if not isinstance(data, dict):
            print(f"⚠️ Invalid message format: expected dict, got {type(data)}")
            print(f"📄 Message content: {data}")
            return
            
        if "incident_id" not in data:
            print("Missing incident_id in message")
            return
            
        incident_id_raw = data.get("incident_id")
        try:
            incident_id = int(incident_id_raw)
        except (ValueError, TypeError):
            print(f"Invalid incident_id format: {incident_id_raw}")
            return
            
        if incident_id <= 0:
            print(f"Invalid incident_id value: {incident_id}")
            return
            
        print("Agent received incident:", incident_id)
        incident = get_incident(incident_id)
        if not incident:
            print("No incident row for id", incident_id)
            return

        print(f"📋 Processing incident {incident_id}: {incident.get('summary_text', '')[:100]}...")
        
        query_text = incident.get("summary_text") or (incident.get("evidence") or {}).get("payload", "")[:400] or ""
        if not query_text:
            print(f"No query text available for incident {incident_id}")
            query_text = f"incident {incident_id}"
        
        print(f"🔍 Starting semantic search...")
        related = search_similar(query_text, top_k=3)
        
        print(f"🤖 Starting LLM analysis...")
        ai_result = ask_llm(incident, related)
        
        if not ai_result:
            print(f"❌ Failed to get AI result for incident {incident_id}")
            return
            
        print(f"📤 Sending Slack notification...")
        send_incident_message(channel=SLACK_CHANNEL, incident=incident, ai_result=ai_result)
        
        print(f"💾 Updating incident status...")
        update_incident_status(incident_id, "notified")
        insert_audit_log(incident_id, "agent", "notified", {"ai_summary": ai_result.get("summary","")})
        
        print(f"✅ Successfully processed incident {incident_id}")
        
    except Exception as e:
        print(f"❌ Error handling incident message: {e}")
        import traceback
        traceback.print_exc()
        # Log the error but don't crash the entire service

def listen_loop():
    print("🚀 Starting reliability agent...")
    print("🔌 Initializing database connection pool...")
    init_connection_pool()
    
    # Pre-load the model to check for issues early
    print("🤖 Pre-loading sentence transformer model...")
    try:
        from retriever_pgvector import get_model
        get_model()
        print("✅ Model pre-loaded successfully")
    except Exception as e:
        print(f"⚠️ Model pre-loading failed: {e}")
        print("🔄 Continuing without model - semantic search will be disabled")
    
    print(f"📡 Creating message listener for channel: {REDIS_CHANNEL}")
    listener = create_message_listener(REDIS_CHANNEL)
    print("🎧 Starting to listen for messages...")
    
    try:
        listener.listen(handle_incident_message)
    except KeyboardInterrupt:
        print("\n🛑 Agent stopped by user")
    except Exception as e:
        print(f"❌ Listener error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🔧 Initializing agent...")
    listen_loop()
