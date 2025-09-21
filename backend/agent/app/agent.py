import json
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import REDIS_CHANNEL, SLACK_CHANNEL
from redis_client import get_redis_client, create_message_listener
from db import get_incident, update_incident_status, insert_audit_log, init_connection_pool, close_connection_pool
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
        
        # Skip semantic search for Windows compatibility
        print(f"ℹ️ Semantic search disabled (Windows compatibility)")
        related = []
        
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
    
    print("ℹ️ Production mode - semantic search disabled for Windows compatibility")
    
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
    finally:
        # Clean up database connections
        try:
            close_connection_pool()
        except Exception as e:
            print(f"⚠️ Error closing database pool: {e}")

if __name__ == "__main__":
    print("🔧 Initializing reliability agent...")
    try:
        listen_loop()
    except KeyboardInterrupt:
        print("\n🛑 Agent stopped")
