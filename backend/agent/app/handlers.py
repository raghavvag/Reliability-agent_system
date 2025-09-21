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
    if not verifier.is_valid(body=body, timestamp=x_slack_request_ts, signature=x_slack_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")
    form = await request.form()
    payload = json.loads(form.get("payload"))
    action = payload["actions"][0]
    action_id = action["action_id"]
    incident_id = int(action["value"])
    user = payload["user"].get("username") or payload["user"].get("id")
    if action_id == "ack":
        update_incident_status(incident_id, "acknowledged")
        insert_audit_log(incident_id, user, "acknowledged")
        return {"text": f"Incident {incident_id} acknowledged by {user}"}
    if action_id == "info":
        update_incident_status(incident_id, "needs_info")
        insert_audit_log(incident_id, user, "requested_info")
        return {"text": f"Requested more info for {incident_id}"}
    if action_id == "resolve":
        update_incident_status(incident_id, "resolved")
        insert_audit_log(incident_id, user, "resolved")
        return {"text": f"Incident {incident_id} marked resolved by {user}"}
    return {"text": "Unknown action"}
