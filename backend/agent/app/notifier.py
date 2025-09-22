from slack_sdk import WebClient
import json
import os
# Handle both relative and absolute imports
try:
    from .config import SLACK_BOT_TOKEN, SLACK_CHANNEL
    from .db import insert_audit_log, save_slack_message
    from .email_notifier import load_routing_config, classify_incident_type
except ImportError:
    from config import SLACK_BOT_TOKEN, SLACK_CHANNEL
    from db import insert_audit_log, save_slack_message
    from email_notifier import load_routing_config, classify_incident_type

slack = WebClient(token=SLACK_BOT_TOKEN)

def build_blocks(incident, ai_result, similar_incidents=None):
    summary = ai_result.get("summary", "")
    root_causes = ai_result.get("root_causes", [])
    causes_md = "\n".join([f"*{i+1}.* {c.get('cause')} - fixes: {', '.join(c.get('fixes',[]))}" for i,c in enumerate(root_causes)]) or "No causes suggested."
    
    # Add team assignment info if available
    team_assigned = ai_result.get("team_assigned", "")
    incident_type = ai_result.get("incident_type", "")
    
    # Main incident header
    incident_header = f"*Incident #{incident.get('incident_id', incident.get('id', 'N/A'))}* — {incident.get('summary_text', incident.get('summary',''))}"
    if team_assigned:
        incident_header += f"\n👥 *Assigned to:* {team_assigned}"
    if incident_type:
        incident_header += f"\n🏷️ *Type:* {incident_type.replace('_', ' ').title()}"

    blocks = [
        {"type":"section", "text":{"type":"mrkdwn", "text": incident_header}},
        {"type":"section", "text":{"type":"mrkdwn", "text": f"*AI Summary:* {summary}"}},
        {"type":"section", "text":{"type":"mrkdwn", "text": f"*Root causes & fixes:*\n{causes_md}"}},
    ]
    
    # Add similar incidents section if available
    if similar_incidents and len(similar_incidents) > 0:
        similar_text = "*Previous Similar Incidents:*\n"
        for incident in similar_incidents[:3]:  # Show top 3
            similarity = incident.get('similarity', 0)
            incident_id = incident.get('memory_id', 'N/A')
            summary = incident.get('summary_text', incident.get('summary', ''))[:60] + "..." if len(incident.get('summary_text', incident.get('summary', ''))) > 60 else incident.get('summary_text', incident.get('summary', ''))
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
    
    try:
        resp = slack.chat_postMessage(channel=channel, blocks=blocks, text=f"Incident {incident_id} notification")
        
        # Save Slack message to database for frontend display
        try:
            save_slack_message(
                incident_id=incident_id,
                message_blocks=blocks,
                slack_response=resp.data if hasattr(resp, 'data') else dict(resp),
                team_name=ai_result.get('team_assigned'),
                incident_type=ai_result.get('incident_type'),
                incident_summary=incident.get('summary_text', incident.get('summary')),
                incident_labels=incident.get('labels'),
                incident_service=incident.get('service'),
                similarity_data=similar_incidents,
                ai_analysis=ai_result
            )
        except Exception as e:
            print(f"⚠️ Failed to save Slack message to database: {e}")
        
        # Log successful Slack notification
        try:
            insert_audit_log(
                incident_id, 
                "system", 
                "slack_sent", 
                {
                    "channel": channel,
                    "message_ts": resp.get('ts'),
                    "ok": resp.get('ok', False)
                }
            )
        except Exception as e:
            print(f"⚠️ Failed to log Slack audit: {e}")
        
        print(f"✅ Slack message sent to {channel} for incident {incident_id}")
        return resp
        
    except Exception as e:
        print(f"❌ Failed to send Slack message to {channel}: {e}")
        
        # Log failed Slack notification
        try:
            insert_audit_log(
                incident_id, 
                "system", 
                "slack_failed", 
                {
                    "channel": channel,
                    "error": str(e)
                }
            )
        except Exception as log_e:
            print(f"⚠️ Failed to log Slack failure: {log_e}")
        
        return None

def send_routed_slack_message(incident: dict, ai_result: dict, similar_incidents=None, incident_type: str = None):
    """
    Send Slack message to the appropriate channel based on incident type
    
    Args:
        incident: Incident dictionary
        ai_result: AI analysis result
        similar_incidents: List of similar incidents
        incident_type: Override incident type (optional)
        
    Returns:
        dict: Slack API response or None if failed
    """
    try:
        config = load_routing_config()
        
        # Classify incident type if not provided
        if not incident_type:
            incident_type = classify_incident_type(incident)
        
        # Get routing info
        routing_info = config['incident_routing'].get(incident_type, config['fallback'])
        channel = routing_info['slack_channel']
        team_name = routing_info['team_name']
        
        print(f"🎯 Routing {incident_type} incident to {channel} ({team_name})")
        
        # Add team info to the blocks
        enhanced_ai_result = ai_result.copy()
        enhanced_ai_result['team_assigned'] = team_name
        enhanced_ai_result['incident_type'] = incident_type
        
        return send_incident_message(channel, incident, enhanced_ai_result, similar_incidents)
        
    except Exception as e:
        print(f"❌ Failed to route Slack message: {e}")
        
        # Fallback to default channel
        try:
            config = load_routing_config()
            fallback_channel = config['fallback']['slack_channel']
            print(f"🔄 Falling back to {fallback_channel}")
            return send_incident_message(fallback_channel, incident, ai_result, similar_incidents)
        except Exception as fallback_e:
            print(f"❌ Fallback also failed: {fallback_e}")
            return None
