import json
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import REDIS_CHANNEL, SLACK_CHANNEL
from redis_client import get_redis_client, create_message_listener
from db import get_incident, update_incident_status, insert_audit_log, init_connection_pool, close_connection_pool, get_conn, return_conn
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
        
        # Enable semantic search with pgvector via FastAPI
        print(f"🔍 Searching for similar incidents...")
        related = []
        try:
            query_text = incident.get('summary_text', '') or incident.get('summary', '')
            if query_text:
                # Use FastAPI semantic search endpoint for summary-based matching
                print(f"🔍 Running semantic search for: {query_text[:50]}...")
                
                try:
                    # Call FastAPI semantic search endpoint
                    import requests as req
                    
                    response = req.post(
                        "http://127.0.0.1:8001/semantic-search",
                        json={"query": query_text, "limit": 3, "similarity_threshold": 0.5},
                        headers={"Content-Type": "application/json"},
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        api_incidents = result.get('incidents', [])
                        
                        # Convert API response format to match expected format
                        for incident_data in api_incidents:
                            related.append({
                                'memory_id': incident_data.get('incident_id'),
                                'summary': incident_data.get('summary'),
                                'labels': incident_data.get('labels', []),
                                'service': incident_data.get('service'),
                                'incident_type': incident_data.get('incident_type'),
                                'solution': incident_data.get('solution'),
                                'similarity': incident_data.get('similarity', 0)
                            })
                        
                        print(f"🎯 FastAPI semantic search found {len(related)} similar incidents")
                    else:
                        print(f"❌ FastAPI semantic search failed: {response.status_code}")
                        print(f"Response: {response.text}")
                        
                except Exception as api_error:
                    print(f"⚠️ FastAPI call failed, falling back to basic search: {api_error}")
                    
                    # Fallback to basic similarity search - only show incidents with solutions
                    with get_conn() as conn:
                        with conn.cursor() as cursor:
                            service = incident.get('evidence', {}).get('service') if isinstance(incident.get('evidence'), dict) else 'unknown'
                            cursor.execute("""
                                SELECT id, summary, labels, service, incident_type, solution
                                FROM memory_item 
                                WHERE solution IS NOT NULL
                                AND (service = %s OR labels && %s)
                                ORDER BY id DESC
                                LIMIT 3
                            """, (service, incident.get('labels', [])))
                            
                            rows = cursor.fetchall()
                            for row in rows:
                                related.append({
                                    'memory_id': row[0],
                                    'summary': row[1],
                                    'labels': row[2] or [],
                                    'service': row[3],
                                    'incident_type': row[4],
                                    'solution': row[5],
                                    'similarity': 0.6  # Lower similarity for basic match
                                })
                        
                if related:
                    print(f"📚 Found {len(related)} similar incidents with solutions:")
                    for item in related:
                        solution_status = "✅ Has solution" if item.get('solution') else "⚠️ No solution"
                        similarity = item.get('similarity', 0)
                        print(f"  - ID: {item['memory_id']} | Similarity: {similarity} | {solution_status}")
                        print(f"    Summary: {item['summary'][:60]}...")
                        if item.get('solution'):
                            print(f"    Solution: {item['solution'][:80]}...")
                else:
                    print(f"📚 No similar incidents found")
            else:
                print(f"⚠️ No summary text for similarity search")
        except Exception as e:
            print(f"⚠️ Semantic search failed: {e}")
            related = []
        
        # Step 3: Get AI analysis with similar incidents context
        print(f"🤖 Starting LLM analysis with similar incidents context...")
        ai_result = ask_llm(incident, related)
        
        if not ai_result:
            print(f"❌ Failed to get AI result for incident {incident_id}")
            return
        
        print(f"✅ AI analysis completed with {len(related)} similar incidents")
        if related:
            print(f"📚 Similar incidents included in analysis:")
            for item in related:
                solution_info = f" (Solution: {item.get('solution', 'None')[:30]}...)" if item.get('solution') else " (No solution)"
                print(f"  - ID {item['memory_id']}: {item['summary'][:40]}...{solution_info}")
        else:
            print(f"📚 No similar incidents found for context")
        
        # Save incident to pgvector memory with analysis
        print(f"💾 Saving incident to vector memory...")
        try:
            # Save incident data to memory_item table
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    memory_id = str(incident_id)  # Convert to string for database
                    summary = incident.get('summary_text', incident.get('summary', ''))
                    service = incident.get('evidence', {}).get('service') if isinstance(incident.get('evidence'), dict) else 'unknown'
                    labels = incident.get('labels', [])
                    
                    # Check if incident already exists
                    cursor.execute("SELECT id FROM memory_item WHERE id = %s", (memory_id,))
                    if cursor.fetchone():
                        # Update existing (don't overwrite solution if it exists)
                        cursor.execute("""
                            UPDATE memory_item 
                            SET summary = %s, labels = %s, service = %s, incident_type = %s
                            WHERE id = %s
                        """, (summary, labels, service, 'incident', memory_id))
                        print(f"✅ Updated incident {incident_id} in memory")
                    else:
                        # Insert new (solution starts as null)
                        cursor.execute("""
                            INSERT INTO memory_item 
                            (id, summary, labels, service, incident_type, model, dim, solution)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (memory_id, summary, labels, service, 'incident',
                             'text-embedding-3-small', 1536, None))
                        print(f"✅ Saved incident {incident_id} to memory")
                    
                    conn.commit()
        except Exception as e:
            print(f"⚠️ Failed to save to vector memory: {e}")
            
        print(f"📤 Sending Slack notification...")
        send_incident_message(channel=SLACK_CHANNEL, incident=incident, ai_result=ai_result, similar_incidents=related)
        
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
    
    print("🔍 Semantic search enabled with pgvector")
    
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
