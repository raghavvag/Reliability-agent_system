from fastapi import FastAPI, Request, Header, HTTPException
from slack_sdk.signature import SignatureVerifier
import json
from config import SLACK_SIGNING_SECRET
from db import update_incident_status, insert_audit_log

app = FastAPI()
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
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action_id}")
            
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        print(f"Error processing Slack action: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
