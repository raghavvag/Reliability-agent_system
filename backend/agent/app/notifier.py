from slack_sdk import WebClient
# Handle both relative and absolute imports
try:
    from .config import SLACK_BOT_TOKEN, SLACK_CHANNEL
except ImportError:
    from config import SLACK_BOT_TOKEN, SLACK_CHANNEL

slack = WebClient(token=SLACK_BOT_TOKEN)

def build_blocks(incident, ai_result, similar_incidents=None):
    summary = ai_result.get("summary", "")
    root_causes = ai_result.get("root_causes", [])
    causes_md = "\n".join([f"*{i+1}.* {c.get('cause')} - fixes: {', '.join(c.get('fixes',[]))}" for i,c in enumerate(root_causes)]) or "No causes suggested."

    blocks = [
        {"type":"section", "text":{"type":"mrkdwn", "text": f"*Incident #{incident.get('incident_id', incident.get('id', 'N/A'))}* — {incident.get('summary_text','')}" }},
        {"type":"section", "text":{"type":"mrkdwn", "text": f"*AI Summary:* {summary}"}},
        {"type":"section", "text":{"type":"mrkdwn", "text": f"*Root causes & fixes:*\n{causes_md}"}},
    ]
    
    # Add similar incidents section if available
    if similar_incidents and len(similar_incidents) > 0:
        similar_text = "*Previous Similar Incidents:*\n"
        for incident in similar_incidents[:3]:  # Show top 3
            similarity = incident.get('similarity', 0)
            incident_id = incident.get('memory_id', 'N/A')
            summary = incident.get('summary', '')[:60] + "..." if len(incident.get('summary', '')) > 60 else incident.get('summary', '')
            solution = incident.get('solution', '')
            
            similar_text += f"• *ID {incident_id}* (similarity: {similarity}) - {summary}\n"
            if solution:
                solution_preview = solution[:100] + "..." if len(solution) > 100 else solution
                similar_text += f"  ✅ *Solution:* {solution_preview}\n"
            else:
                similar_text += f"  ⚠️ *No solution available*\n"
            similar_text += "\n"
        
        blocks.append({"type":"section", "text":{"type":"mrkdwn", "text": similar_text}})
    
    blocks.append({
        "type":"actions", "elements":[
            {"type":"button","text":{"type":"plain_text","text":"Acknowledge"},"value":str(incident.get('incident_id', incident.get('id', 'N/A'))),"action_id":"ack"},
            {"type":"button","text":{"type":"plain_text","text":"Request More Info"},"value":str(incident.get('incident_id', incident.get('id', 'N/A'))),"action_id":"info"},
            {"type":"button","text":{"type":"plain_text","text":"Mark as Resolved"},"value":str(incident.get('incident_id', incident.get('id', 'N/A'))),"action_id":"resolve"}
        ]
    })
    return blocks

def send_incident_message(channel: str, incident: dict, ai_result: dict, similar_incidents=None):
    blocks = build_blocks(incident, ai_result, similar_incidents)
    incident_id = incident.get('incident_id', incident.get('id', 'N/A'))
    resp = slack.chat_postMessage(channel=channel, blocks=blocks, text=f"Incident {incident_id} notification")
    return resp
