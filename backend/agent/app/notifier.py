from slack_sdk import WebClient
from config import SLACK_BOT_TOKEN, SLACK_CHANNEL

slack = WebClient(token=SLACK_BOT_TOKEN)

def build_blocks(incident, ai_result):
    summary = ai_result.get("summary", "")
    root_causes = ai_result.get("root_causes", [])
    causes_md = "\n".join([f"*{i+1}.* {c.get('cause')} - fixes: {', '.join(c.get('fixes',[]))}" for i,c in enumerate(root_causes)]) or "No causes suggested."

    blocks = [
        {"type":"section", "text":{"type":"mrkdwn", "text": f"*Incident #{incident['id']}* — {incident.get('summary_text','')}" }},
        {"type":"section", "text":{"type":"mrkdwn", "text": f"*AI Summary:* {summary}"}},
        {"type":"section", "text":{"type":"mrkdwn", "text": f"*Root causes & fixes:*\n{causes_md}"}},
        {"type":"actions", "elements":[
            {"type":"button","text":{"type":"plain_text","text":"Acknowledge"},"value":str(incident["id"]),"action_id":"ack"},
            {"type":"button","text":{"type":"plain_text","text":"Request More Info"},"value":str(incident["id"]),"action_id":"info"},
            {"type":"button","text":{"type":"plain_text","text":"Mark as Resolved"},"value":str(incident["id"]),"action_id":"resolve"}
        ]}
    ]
    return blocks

def send_incident_message(channel: str, incident: dict, ai_result: dict):
    blocks = build_blocks(incident, ai_result)
    resp = slack.chat_postMessage(channel=channel, blocks=blocks, text=f"Incident {incident['id']} notification")
    return resp
