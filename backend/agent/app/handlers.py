from fastapi import FastAPI, Request, Header, HTTPException
from slack_sdk.signature import SignatureVerifier
import json
from .config import SLACK_SIGNING_SECRET
from .db import update_incident_status, insert_audit_log, get_conn, return_conn, connection_pool, init_connection_pool

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """Initialize database connection pool on startup"""
    print("🚀 Initializing database connection pool...")
    try:
        init_connection_pool()
        print("✅ Database connection pool initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize database connection pool: {e}")
        raise

def _extract_diversity_key(summary, service):
    """Extract diversity key based on incident patterns."""
    if summary and service:
        # For SQL injection, look for different types
        if "sql" in summary.lower() or "injection" in summary.lower():
            if "union" in summary.lower():
                return f"{service}_sql_union"
            elif "blind" in summary.lower():
                return f"{service}_sql_blind"
            elif "time" in summary.lower() or "delay" in summary.lower():
                return f"{service}_sql_time"
            else:
                return f"{service}_sql_generic"
        
        # For other incidents, use service + key terms
        key_terms = ["auth", "permission", "timeout", "error", "crash", "memory", "performance"]
        for term in key_terms:
            if term in summary.lower():
                return f"{service}_{term}"
    
    return f"{service or 'unknown'}_general"

def _filter_diverse_results(incidents, max_per_key=1):
    """Filter incidents to ensure diversity in patterns."""
    diversity_map = {}
    filtered_results = []
    
    for incident in incidents:
        summary = incident.get('summary', '')
        service = incident.get('service', '')
        diversity_key = _extract_diversity_key(summary, service)
        
        if diversity_key not in diversity_map:
            diversity_map[diversity_key] = 0
        
        if diversity_map[diversity_key] < max_per_key:
            filtered_results.append(incident)
            diversity_map[diversity_key] += 1
    
    return filtered_results

verifier = SignatureVerifier(SLACK_SIGNING_SECRET)

@app.post("/slack/actions")
async def slack_actions(request: Request, x_slack_signature: str = Header(None), x_slack_request_ts: str = Header(None)):
    body = await request.body()
    
    # Validate required headers
    if not x_slack_signature or not x_slack_request_ts:
        raise HTTPException(status_code=400, detail="Missing required Slack headers")
    
    # Verify Slack signature
    if not verifier.is_valid(body=body, timestamp=x_slack_request_ts, signature=x_slack_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    try:
        form = await request.form()
        payload_raw = form.get("payload")
        if not payload_raw:
            raise HTTPException(status_code=400, detail="Missing payload")
            
        payload = json.loads(payload_raw)
        
        # Validate payload structure
        if "actions" not in payload or not payload["actions"]:
            raise HTTPException(status_code=400, detail="Missing actions in payload")
        
        if "user" not in payload:
            raise HTTPException(status_code=400, detail="Missing user in payload")
            
        action = payload["actions"][0]
        action_id = action.get("action_id")
        incident_id_raw = action.get("value")
        
        if not action_id or not incident_id_raw:
            raise HTTPException(status_code=400, detail="Missing action_id or value")
        
        # Validate incident_id
        try:
            incident_id = int(incident_id_raw)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid incident_id format")
        
        if incident_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid incident_id value")
        
        user = payload["user"].get("username") or payload["user"].get("id") or "unknown"
        
        # Process actions
        if action_id == "ack":
            success = update_incident_status(incident_id, "acknowledged")
            if success:
                insert_audit_log(incident_id, user, "acknowledged")
                return {"text": f"Incident {incident_id} acknowledged by {user}"}
            else:
                raise HTTPException(status_code=500, detail="Failed to update incident status")
                
        elif action_id == "info":
            success = update_incident_status(incident_id, "needs_info")
            if success:
                insert_audit_log(incident_id, user, "requested_info")
                return {"text": f"Requested more info for {incident_id}"}
            else:
                raise HTTPException(status_code=500, detail="Failed to update incident status")
                
        elif action_id == "resolve":
            success = update_incident_status(incident_id, "resolved")
            if success:
                insert_audit_log(incident_id, user, "resolved")
                return {"text": f"Incident {incident_id} marked resolved by {user}"}
            else:
                raise HTTPException(status_code=500, detail="Failed to update incident status")
                
        elif action_id == "add_solution":
            # Handle solution updates
            solution_text = action.get("selected_option", {}).get("text", {}).get("text", "")
            if not solution_text:
                raise HTTPException(status_code=400, detail="No solution text provided")
            
            # Update solution in memory_item table
            conn = get_conn()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE memory_item 
                        SET solution = %s
                        WHERE id = %s
                    """, (solution_text, str(incident_id)))
                    
                    if cursor.rowcount > 0:
                        conn.commit()
                        insert_audit_log(incident_id, user, "added_solution", {"solution": solution_text})
                        return {"text": f"Solution added to incident {incident_id} by {user}"}
                    else:
                        raise HTTPException(status_code=404, detail="Incident not found in memory")
                finally:
                    cursor.close()
                    return_conn(conn)
            else:
                raise HTTPException(status_code=500, detail="Database connection failed")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action_id}")
            
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        print(f"Error processing Slack action: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/incidents/{incident_id}/solution")
async def update_solution(incident_id: int, request: Request):
    """Update solution for a specific incident"""
    try:
        body = await request.json()
        solution = body.get("solution", "").strip()
        user = body.get("user", "unknown")
        
        if not solution:
            raise HTTPException(status_code=400, detail="Solution text is required")
        
        # Update solution in memory_item table
        conn = get_conn()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE memory_item 
                SET solution = %s
                WHERE id = %s
            """, (solution, str(incident_id)))
            
            if cursor.rowcount > 0:
                conn.commit()
                insert_audit_log(incident_id, user, "added_solution", {"solution": solution})
                return {"message": f"Solution updated for incident {incident_id}", "success": True}
            else:
                raise HTTPException(status_code=404, detail="Incident not found in memory")
        finally:
            cursor.close()
            return_conn(conn)
            
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        print(f"Error updating solution: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/incidents/similar")
async def get_similar_incidents(service: str = None, labels: str = None, limit: int = 3):
    """Get similar incidents with their solutions for frontend display"""
    try:
        conn = get_conn()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        try:
            cursor = conn.cursor()
            
            # Build query based on parameters
            if service and labels:
                # Parse labels from comma-separated string
                label_list = [label.strip() for label in labels.split(',') if label.strip()]
                cursor.execute("""
                    SELECT id, summary, labels, service, incident_type, solution
                    FROM memory_item 
                    WHERE service = %s OR labels && %s
                    ORDER BY id DESC
                    LIMIT %s
                """, (service, label_list, limit))
            elif service:
                cursor.execute("""
                    SELECT id, summary, labels, service, incident_type, solution
                    FROM memory_item 
                    WHERE service = %s
                    ORDER BY id DESC
                    LIMIT %s
                """, (service, limit))
            elif labels:
                label_list = [label.strip() for label in labels.split(',') if label.strip()]
                cursor.execute("""
                    SELECT id, summary, labels, service, incident_type, solution
                    FROM memory_item 
                    WHERE labels && %s
                    ORDER BY id DESC
                    LIMIT %s
                """, (label_list, limit))
            else:
                # Get recent incidents if no filters
                cursor.execute("""
                    SELECT id, summary, labels, service, incident_type, solution
                    FROM memory_item 
                    ORDER BY id DESC
                    LIMIT %s
                """, (limit,))
            
            rows = cursor.fetchall()
            results = []
            
            for row in rows:
                results.append({
                    'incident_id': row[0],
                    'summary': row[1],
                    'labels': row[2] or [],
                    'service': row[3],
                    'incident_type': row[4],
                    'solution': row[5],
                    'has_solution': bool(row[5])
                })
            
            return {
                "similar_incidents": results,
                "count": len(results),
                "filters": {
                    "service": service,
                    "labels": labels.split(',') if labels else None,
                    "limit": limit
                }
            }
            
        finally:
            cursor.close()
            return_conn(conn)
            
    except Exception as e:
        print(f"Error fetching similar incidents: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    """Health check endpoint that also tests database connectivity"""
    try:
        if connection_pool is None:
            return {"status": "error", "message": "Database connection pool not initialized"}
            
        with connection_pool.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                
        return {
            "status": "healthy", 
            "database": "connected",
            "message": "API and database are operational"
        }
    except Exception as e:
        return {
            "status": "error", 
            "database": "disconnected",
            "message": f"Database connection failed: {str(e)}"
        }

@app.post("/semantic-search")
async def semantic_search(request: Request):
    """
    Semantic search endpoint that:
    1. Takes incident query text
    2. Converts to embeddings using OpenAI
    3. Finds similar incidents using pgvector based on summary similarity
    4. Returns top results with solutions
    """
    try:
        body = await request.json()
        query_text = body.get("query", body.get("summary", "")).strip()
        limit = body.get("limit", 3)
        similarity_threshold = body.get("similarity_threshold", body.get("threshold", 0.7))
        
        if not query_text:
            raise HTTPException(status_code=400, detail="Query text is required")

        # Get OpenAI embedding for the query
        from .llm_client import get_openai_client
        import requests as req
        
        client = get_openai_client()
        if not hasattr(client, 'api_key'):
            raise HTTPException(status_code=500, detail="OpenAI client not properly configured")
        
        # Get embedding
        headers = {
            "Authorization": f"Bearer {client.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "input": query_text,
            "model": "text-embedding-3-small"
        }
        
        response = req.post(
            "https://api.openai.com/v1/embeddings",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Embedding API error: {response.text}")
        
        embedding_result = response.json()
        query_embedding = embedding_result['data'][0]['embedding']
        
        # Search similar incidents using pgvector based on summary similarity
        from .db import connection_pool
        
        if connection_pool is None:
            raise HTTPException(status_code=500, detail="Database connection pool not initialized")
            
        with connection_pool.connection() as conn:
            with conn.cursor() as cursor:
                # Get more results initially to enable diversity filtering
                initial_limit = limit * 3  # Get three times as many results for diversity
                
                cursor.execute("""
                    SELECT id, summary, labels, service, incident_type, solution,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM memory_item 
                    WHERE embedding IS NOT NULL
                    AND 1 - (embedding <=> %s::vector) > %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (query_embedding, query_embedding, similarity_threshold, query_embedding, initial_limit))
                
                all_rows = cursor.fetchall()
                
                # Apply diversity filtering to get varied results
                results = []
                used_patterns = set()
                
                for row in all_rows:
                    if len(results) >= limit:
                        break
                        
                    summary = row[1] or ""
                    service = row[3] or "unknown"
                    
                    # Create a diversity key based on service and summary patterns
                    diversity_key = _extract_diversity_key(summary, service)
                    
                    # If we haven't seen this pattern type yet, or if we have few results, include it
                    if diversity_key not in used_patterns or len(results) < limit // 2:
                        results.append({
                            'incident_id': row[0],
                            'summary': summary,
                            'labels': row[2] or [],
                            'service': service,
                            'incident_type': row[4] or "incident",
                            'solution': row[5],
                            'similarity': round(row[6], 3),
                            'has_solution': bool(row[5] and row[5].strip())
                        })
                        used_patterns.add(diversity_key)
                
                return {
                    "status": "success",
                    "query": query_text,
                    "incidents": results,
                    "total_found": len(results),
                    "query_embedding_generated": True,
                    "search_threshold": similarity_threshold,
                    "diversity_filtering_applied": True,
                    "search_params": {
                        "similarity_threshold": similarity_threshold,
                        "limit": limit,
                        "embedding_model": "text-embedding-3-small",
                        "diversity_enabled": True
                    }
                }
            
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        print(f"❌ Error in semantic search: {e}")
        print(f"🔍 Query: {body.get('query', 'No query') if 'body' in locals() else 'Failed to parse request'}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/slack/actions")
async def slack_actions(request: Request, x_slack_signature: str = Header(None), x_slack_request_timestamp: str = Header(None)):
    """
    Handle Slack button interactions from incident notifications
    Processes: Acknowledge, Request More Info, Mark as Resolved
    """
    try:
        # Get request body
        body = await request.body()
        body_str = body.decode('utf-8')
        
        # Verify Slack signature for security
        if SLACK_SIGNING_SECRET and x_slack_signature and x_slack_request_timestamp:
            verifier = SignatureVerifier(SLACK_SIGNING_SECRET)
            if not verifier.is_valid(body=body_str, timestamp=x_slack_request_timestamp, signature=x_slack_signature):
                raise HTTPException(status_code=401, detail="Invalid Slack signature")
        
        # Parse form data from Slack
        import urllib.parse
        parsed_data = urllib.parse.parse_qs(body_str)
        payload_str = parsed_data.get('payload', [''])[0]
        
        if not payload_str:
            raise HTTPException(status_code=400, detail="No payload found")
        
        payload = json.loads(payload_str)
        
        # Extract action information
        action = payload.get('actions', [{}])[0]
        action_id = action.get('action_id')
        incident_id_str = action.get('value')
        user_id = payload.get('user', {}).get('id')
        user_name = payload.get('user', {}).get('name', 'Unknown')
        channel_id = payload.get('channel', {}).get('id')
        message_ts = payload.get('message', {}).get('ts')
        
        # Convert incident_id to integer
        try:
            incident_id = int(incident_id_str) if incident_id_str != 'N/A' else None
        except (ValueError, TypeError):
            incident_id = None
            
        if not incident_id:
            raise HTTPException(status_code=400, detail=f"Invalid incident ID: {incident_id_str}")
        
        print(f"🎯 Slack action received: {action_id} for incident {incident_id} by user {user_name}")
        
        # Process different actions
        response_text = ""
        
        if action_id == "ack":
            # Acknowledge incident
            update_incident_status(incident_id, "ack")
            insert_audit_log(incident_id, user_name, "acknowledged", f"Acknowledged by {user_name}")
            response_text = f"✅ Incident {incident_id} acknowledged by {user_name}"
            
        elif action_id == "info":
            # Request more information - keep as 'open' since we need more info
            update_incident_status(incident_id, "open")
            insert_audit_log(incident_id, user_name, "info_requested", f"More info requested by {user_name}")
            response_text = f"ℹ️ More information requested for incident {incident_id} by {user_name}"
            
        elif action_id == "resolve":
            # Mark as resolved
            update_incident_status(incident_id, "resolved")
            insert_audit_log(incident_id, user_name, "resolved", f"Resolved by {user_name}")
            response_text = f"🎉 Incident {incident_id} marked as resolved by {user_name}"
            
        else:
            response_text = f"❓ Unknown action: {action_id}"
        
        # Return response to update Slack message
        return {
            "response_type": "in_channel",
            "replace_original": False,
            "text": response_text,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": response_text
                    }
                }
            ]
        }
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        print(f"Error in slack actions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/test/notifications")
async def test_notifications_endpoint(request: Request):
    """
    Test endpoint for the notification routing system
    """
    try:
        body = await request.json()
        incident_type = body.get("incident_type", "xss")
        
        # Import the test function
        from .incident_router import test_notifications
        
        # Run the test
        results = test_notifications(incident_type)
        
        return {
            "status": "test_completed",
            "incident_type": incident_type,
            "results": results
        }
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        print(f"Error in test notifications: {e}")
        raise HTTPException(status_code=500, detail=f"Test failed: {str(e)}")


@app.get("/routing/info")
async def get_routing_info():
    """
    Get routing configuration information
    """
    try:
        from .incident_router import get_routing_info
        
        return {
            "status": "success",
            "routing_info": get_routing_info()
        }
        
    except Exception as e:
        print(f"Error getting routing info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get routing info: {str(e)}")


@app.get("/routing/info/{incident_type}")
async def get_specific_routing_info(incident_type: str):
    """
    Get routing information for a specific incident type
    """
    try:
        from .incident_router import get_routing_info
        
        return {
            "status": "success",
            "incident_type": incident_type,
            "routing_info": get_routing_info(incident_type)
        }
        
    except Exception as e:
        print(f"Error getting routing info for {incident_type}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get routing info: {str(e)}")