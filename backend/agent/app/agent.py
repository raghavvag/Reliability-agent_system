import json
from redis import Redis
from config import REDIS_URL, REDIS_CHANNEL, SLACK_CHANNEL
from db import get_incident, update_incident_status, insert_audit_log
from retriever_pgvector import search_similar
from llm_client import ask_llm
from notifier import send_incident_message

r = Redis.from_url(REDIS_URL, decode_responses=True)

def handle_incident_message(data):
    try:
        if not isinstance(data, dict):
            print("Invalid message format: expected dict")
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

        query_text = incident.get("summary_text") or (incident.get("evidence") or {}).get("payload", "")[:400] or ""
        if not query_text:
            print(f"No query text available for incident {incident_id}")
            query_text = f"incident {incident_id}"
            
        related = search_similar(query_text, top_k=3)
        ai_result = ask_llm(incident, related)
        
        if not ai_result:
            print(f"Failed to get AI result for incident {incident_id}")
            return
            
        send_incident_message(channel=SLACK_CHANNEL, incident=incident, ai_result=ai_result)
        update_incident_status(incident_id, "notified")
        insert_audit_log(incident_id, "agent", "notified", {"ai_summary": ai_result.get("summary","")})
        
    except Exception as e:
        print(f"Error handling incident message: {e}")
        # Log the error but don't crash the entire service

def listen_loop():
    pubsub = r.pubsub()
    pubsub.subscribe(REDIS_CHANNEL)
    print("Agent listening on Redis channel", REDIS_CHANNEL)
    for item in pubsub.listen():
        if item["type"] != "message": continue
        try:
            data = json.loads(item["data"])
            handle_incident_message(data)
        except Exception as exc:
            print("Error handling incident message:", exc)

if __name__ == "__main__":
    listen_loop()
