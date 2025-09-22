import os, json
import psycopg
from psycopg_pool import ConnectionPool

# Handle both relative and absolute imports
try:
    from .config import DATABASE_URL
except ImportError:
    from config import DATABASE_URL

import logging

# Connection pool for better performance
connection_pool = None

def init_connection_pool():
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = ConnectionPool(
                DATABASE_URL,
                min_size=1, 
                max_size=20
            )
            print("Database connection pool initialized")
            
            # Create slack_messages table if it doesn't exist
            create_slack_messages_table()
            
        except Exception as e:
            print(f"Error creating connection pool: {e}")
            raise

def create_slack_messages_table():
    """Create the slack_messages table if it doesn't exist"""
    try:
        with connection_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS slack_messages (
                        id SERIAL PRIMARY KEY,
                        incident_id INTEGER NOT NULL,
                        message_ts VARCHAR(50),
                        channel_id VARCHAR(50),
                        channel_name VARCHAR(100),
                        team_name VARCHAR(100),
                        incident_type VARCHAR(50),
                        
                        message_blocks JSONB NOT NULL,
                        message_text TEXT,
                        
                        incident_summary TEXT,
                        incident_labels TEXT[],
                        incident_service VARCHAR(100),
                        similarity_data JSONB,
                        ai_analysis JSONB,
                        
                        sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        slack_response JSONB,
                        status VARCHAR(20) DEFAULT 'sent'
                    )
                """)
                
                # Create indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_slack_messages_incident_id ON slack_messages(incident_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_slack_messages_sent_at ON slack_messages(sent_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_slack_messages_incident_type ON slack_messages(incident_type)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_slack_messages_team ON slack_messages(team_name)")
                
                conn.commit()
                print("✅ Slack messages table ensured to exist")
                
    except Exception as e:
        print(f"⚠️ Error creating slack_messages table: {e}")

def close_connection_pool():
    global connection_pool
    if connection_pool is not None:
        try:
            connection_pool.close()
            connection_pool = None
            print("Database connection pool closed")
        except Exception as e:
            print(f"Error closing connection pool: {e}")

def get_conn():
    if connection_pool is None:
        init_connection_pool()
    try:
        return connection_pool.connection()
    except Exception as e:
        print(f"Error getting database connection: {e}")
        raise

def return_conn(conn):
    # psycopg-pool connections are context managers, no need to manually close
    pass

def get_incident(incident_id):
    if not incident_id or not isinstance(incident_id, int):
        print(f"Invalid incident_id: {incident_id}")
        return None
        
    try:
        with connection_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                  SELECT id, event_id, labels, summary_text, anomaly_score, confidence, evidence, status, created_at
                  FROM incidents WHERE id = %s
                """, (incident_id,))
                row = cur.fetchone()
                
                if not row:
                    return None
                return {
                    "id": row[0],
                    "event_id": row[1],
                    "labels": row[2] or [],
                    "summary_text": row[3],
                    "anomaly_score": row[4],
                    "confidence": row[5],
                    "evidence": row[6],
                    "status": row[7],
                    "created_at": row[8].isoformat() if row[8] else None
                }
    except Exception as e:
        print(f"Error fetching incident {incident_id}: {e}")
        return None

def update_incident_status(incident_id, status):
    if not incident_id or not isinstance(incident_id, int):
        print(f"Invalid incident_id: {incident_id}")
        return False
    if not status or not isinstance(status, str):
        print(f"Invalid status: {status}")
        return False
        
    try:
        with connection_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE incidents SET status = %s WHERE id = %s", (status, incident_id))
                conn.commit()
                return True
    except Exception as e:
        print(f"Error updating incident {incident_id} status: {e}")
        return False

def insert_audit_log(incident_id, who, action, details=None):
    if not incident_id or not isinstance(incident_id, int):
        print(f"Invalid incident_id: {incident_id}")
        return False
    if not who or not action:
        print(f"Invalid who/action: {who}/{action}")
        return False
        
    try:
        with connection_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                  INSERT INTO audit_logs (incident_id, who, action, details)
                  VALUES (%s, %s, %s, %s)
                """, (incident_id, who, action, json.dumps(details or {})))
                conn.commit()
                return True
    except Exception as e:
        print(f"Error inserting audit log: {e}")
        return False

def save_slack_message(
    incident_id: int,
    message_blocks: list,
    slack_response: dict,
    team_name: str = None,
    incident_type: str = None,
    incident_summary: str = None,
    incident_labels: list = None,
    incident_service: str = None,
    similarity_data: list = None,
    ai_analysis: dict = None
):
    """
    Save Slack message data to slack_messages table for frontend display
    
    Args:
        incident_id: ID of the incident
        message_blocks: Slack blocks structure
        slack_response: Full Slack API response
        team_name: Team that received the message
        incident_type: Classified incident type
        incident_summary: Incident summary text
        incident_labels: Incident labels array
        incident_service: Service name
        similarity_data: Similar incidents data
        ai_analysis: AI analysis results
    
    Returns:
        int|bool: Message ID if successful, False otherwise
    """
    try:
        # Validate required parameters
        if not incident_id or not message_blocks:
            print(f"⚠️ Missing required parameters for saving Slack message")
            return False
            
        with connection_pool.connection() as conn:
            with conn.cursor() as cur:
                # Extract message metadata from Slack response
                message_ts = slack_response.get('ts') if slack_response else None
                channel_id = slack_response.get('channel') if slack_response else None
                
                # Create plain text version of the message
                message_text = ""
                if message_blocks:
                    for block in message_blocks:
                        if block.get('type') == 'section' and block.get('text'):
                            text_content = block['text'].get('text', '')
                            # Remove Slack markdown formatting for plain text
                            import re
                            plain_text = re.sub(r'\*([^*]+)\*', r'\1', text_content)  # Remove bold
                            plain_text = re.sub(r'_([^_]+)_', r'\1', plain_text)      # Remove italic
                            plain_text = re.sub(r'`([^`]+)`', r'\1', plain_text)      # Remove code
                            message_text += plain_text + "\n"
                
                cur.execute("""
                    INSERT INTO slack_messages (
                        incident_id, message_ts, channel_id, team_name, incident_type,
                        message_blocks, message_text, incident_summary, incident_labels,
                        incident_service, similarity_data, ai_analysis, slack_response
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    incident_id,
                    message_ts,
                    channel_id,
                    team_name,
                    incident_type,
                    json.dumps(message_blocks),
                    message_text.strip(),
                    incident_summary,
                    incident_labels or [],
                    incident_service,
                    json.dumps(similarity_data) if similarity_data else None,
                    json.dumps(ai_analysis) if ai_analysis else None,
                    json.dumps(slack_response) if slack_response else None
                ))
                
                message_id = cur.fetchone()[0]
                conn.commit()
                print(f"✅ Saved Slack message to database with ID: {message_id} for incident {incident_id}")
                return message_id
                
    except Exception as e:
        print(f"❌ Error saving Slack message: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_slack_messages(incident_id: int = None, limit: int = 50, team_name: str = None):
    """
    Retrieve Slack messages for frontend display
    
    Args:
        incident_id: Filter by specific incident ID
        limit: Maximum number of messages to return
        team_name: Filter by team name
    
    Returns:
        list: List of Slack message records
    """
    try:
        with connection_pool.connection() as conn:
            with conn.cursor() as cur:
                where_conditions = []
                params = []
                
                if incident_id:
                    where_conditions.append("incident_id = %s")
                    params.append(incident_id)
                
                if team_name:
                    where_conditions.append("team_name = %s")
                    params.append(team_name)
                
                where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
                params.append(limit)
                
                cur.execute(f"""
                    SELECT 
                        id, incident_id, message_ts, channel_id, team_name, incident_type,
                        message_blocks, message_text, incident_summary, incident_labels,
                        incident_service, similarity_data, ai_analysis, sent_at, status
                    FROM slack_messages
                    {where_clause}
                    ORDER BY sent_at DESC
                    LIMIT %s
                """, params)
                
                rows = cur.fetchall()
                messages = []
                
                for row in rows:
                    messages.append({
                        'id': row[0],
                        'incident_id': row[1],
                        'message_ts': row[2],
                        'channel_id': row[3],
                        'team_name': row[4],
                        'incident_type': row[5],
                        'message_blocks': json.loads(row[6]) if row[6] else [],
                        'message_text': row[7],
                        'incident_summary': row[8],
                        'incident_labels': row[9] or [],
                        'incident_service': row[10],
                        'similarity_data': json.loads(row[11]) if row[11] else [],
                        'ai_analysis': json.loads(row[12]) if row[12] else {},
                        'sent_at': row[13].isoformat() if row[13] else None,
                        'status': row[14]
                    })
                
                return messages
                
    except Exception as e:
        print(f"❌ Error retrieving Slack messages: {e}")
        return []
