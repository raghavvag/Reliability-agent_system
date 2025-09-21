# AI-Powered Incident Management Assistant

## All repositories :
Ai Agent: https://github.com/raghavvag/Reliability-agent_system.git
Worker Service:https://github.com/VaniVerma16/ragent
Data Ingestion Pipeline:https://github.com/AaryanCode69/Ingestion-Pipeline

## Overview
This system processes incidents from raw events, performs AI-powered analysis, and sends interactive Slack notifications for incident management.

## Architecture
```
Raw Events → Postgres → Worker (Member B) → Redis → Agent (Member C) → Slack → FastAPI → Audit Logs
```

## Prerequisites

### Software Requirements
- Python 3.13+
- PostgreSQL with pgvector extension
- Redis server
- Slack workspace with bot permissions

### System Setup

1. **Install PostgreSQL with pgvector**
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

2. **Install Redis**
   ```bash
   # Ubuntu/Debian
   sudo apt install redis-server
   
   # macOS
   brew install redis
   
   # Windows
   # Download from https://redis.io/download
   ```

3. **Create Slack App**
   - Go to https://api.slack.com/apps
   - Create new app "Incident Manager"
   - Add bot token scopes: `chat:write`, `channels:read`
   - Enable interactivity and set request URL to your server
   - Install app to workspace

## Database Schema

The system uses the following PostgreSQL tables:

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Raw events (populated by external systems)
CREATE TABLE IF NOT EXISTS raw_events (
  id SERIAL PRIMARY KEY,
  source TEXT,
  type TEXT,             -- 'metric' or 'log'
  payload TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Incidents (created by Worker - Member B)
CREATE TABLE IF NOT EXISTS incidents (
  id SERIAL PRIMARY KEY,
  event_id INTEGER,
  labels TEXT[],
  summary_text TEXT,
  anomaly_score FLOAT,
  confidence FLOAT,
  evidence JSONB,
  status VARCHAR(50) DEFAULT 'open',
  created_at TIMESTAMP DEFAULT now()
);

-- Memory items for semantic search (populated by Worker - Member B)
CREATE TABLE IF NOT EXISTS memory_item (
  id TEXT PRIMARY KEY,
  summary TEXT,
  labels TEXT[],
  service TEXT,
  incident_type TEXT,
  model TEXT NOT NULL DEFAULT 'sentence-transformers/all-MiniLM-L6-v2',
  dim INT NOT NULL DEFAULT 384,
  embedding VECTOR(384)
);

-- Index for fast vector similarity search
CREATE INDEX IF NOT EXISTS memory_item_embedding_ivf
ON memory_item USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS memory_item_service_idx ON memory_item(service);

-- Audit logs (populated by this agent)
CREATE TABLE IF NOT EXISTS audit_logs (
  id SERIAL PRIMARY KEY,
  incident_id INTEGER,
  who TEXT,
  action TEXT,
  details JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

## Installation

1. **Clone and Setup Environment**
   ```bash
   cd backend/agent
   python -m venv .venv
   # Windows
   .\.venv\Scripts\Activate.ps1
   # Linux/macOS
   source .venv/bin/activate
   
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables**
   
   Create `.env` file in `backend/agent/` directory:
   ```env
   # Database
   DATABASE_URL=postgresql://user:password@localhost:5432/incidentdb
   
   # Redis
   REDIS_URL=redis://localhost:6379/0
   REDIS_CHANNEL=incident_ready
   
   # Slack
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_SIGNING_SECRET=your-signing-secret
   SLACK_CHANNEL=#incident-alerts
   
   # OpenAI
   OPENAI_API_KEY=sk-your-openai-api-key
   
   # Embeddings
   EMBED_MODEL_NAME=all-MiniLM-L6-v2
   VECTOR_DIM=384
   ```

3. **Verify Configuration**
   ```bash
   python -c "from app.config import *; print('Configuration OK')"
   ```

## Usage

### Running the System

#### 1. Start the Agent (Redis Listener)
```bash
cd backend/agent
python app/agent.py
```

Expected output:
```
Configuration loaded:
  DATABASE_URL: ********localhost:5432/incidentdb
  REDIS_URL: redis://localhost:6379/0
  REDIS_CHANNEL: incident_ready
  SLACK_CHANNEL: #incident-alerts
  EMBED_MODEL_NAME: all-MiniLM-L6-v2
  VECTOR_DIM: 384
  OPENAI_API_KEY: SET
  SLACK_BOT_TOKEN: SET
  SLACK_SIGNING_SECRET: SET
Database connection pool initialized
Agent listening on Redis channel incident_ready
```

#### 2. Start the FastAPI Server (Slack Webhook Handler)
```bash
cd backend/agent
uvicorn app.handlers:app --host 0.0.0.0 --port 8000
```

Expected output:
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Input Format

#### Redis Message Format
The agent listens for messages on the Redis channel `incident_ready`. The expected message format is:

```json
{
  "incident_id": 123
}
```

**Message Fields:**
- `incident_id` (integer, required): The ID of the incident in the `incidents` table

#### Publishing Test Messages
You can test the system by publishing messages to Redis:

```bash
# Using redis-cli
redis-cli PUBLISH incident_ready '{"incident_id": 101}'

# Using Python
import redis
import json
r = redis.Redis.from_url("redis://localhost:6379/0")
r.publish("incident_ready", json.dumps({"incident_id": 101}))
```

### Example Workflow

1. **Create Test Data**
   ```sql
   -- Insert a test incident
   INSERT INTO incidents (event_id, labels, summary_text, anomaly_score, confidence, evidence, status)
   VALUES (
     1,
     ARRAY['database', 'performance'],
     'High CPU usage detected on database server',
     0.85,
     0.9,
     '{"service": "postgres", "metric": "cpu_usage", "value": 95}',
     'open'
   );

   -- Insert related memory items for context
   INSERT INTO memory_item (id, summary, labels, service, incident_type, embedding)
   VALUES (
     'mem_001',
     'Database connection pool exhausted',
     ARRAY['database', 'connection'],
     'postgres',
     'performance',
     '[0.1, 0.2, 0.3, ...]'  -- 384-dimensional vector
   );
   ```

2. **Trigger Agent Processing**
   ```bash
   redis-cli PUBLISH incident_ready '{"incident_id": 1}'
   ```

3. **Expected Agent Behavior**
   - Fetches incident from database
   - Performs semantic search for related incidents
   - Calls OpenAI API for analysis
   - Sends Slack notification with interactive buttons
   - Updates incident status to "notified"
   - Logs action in audit_logs

### Output Examples

#### Slack Message Format
The agent sends rich Slack messages with the following structure:

```json
{
  "blocks": [
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Incident #123* — High CPU usage detected on database server"
      }
    },
    {
      "type": "section", 
      "text": {
        "type": "mrkdwn",
        "text": "*AI Summary:* Database experiencing high CPU load, likely due to resource-intensive queries"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn", 
        "text": "*Root causes & fixes:*\n*1.* Query optimization needed - fixes: Add database indexes, Optimize slow queries\n*2.* Connection pool exhaustion - fixes: Increase connection pool size, Add connection monitoring"
      }
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {"type": "plain_text", "text": "Acknowledge"},
          "value": "123",
          "action_id": "ack"
        },
        {
          "type": "button", 
          "text": {"type": "plain_text", "text": "Request More Info"},
          "value": "123",
          "action_id": "info"
        },
        {
          "type": "button",
          "text": {"type": "plain_text", "text": "Mark as Resolved"},
          "value": "123", 
          "action_id": "resolve"
        }
      ]
    }
  ]
}
```

#### LLM Response Format
The OpenAI API returns JSON responses in this format:

```json
{
  "summary": "Database experiencing high CPU load, likely due to resource-intensive queries",
  "root_causes": [
    {
      "cause": "Query optimization needed",
      "fixes": ["Add database indexes", "Optimize slow queries"],
      "rollback": "Remove new indexes if performance degrades"
    },
    {
      "cause": "Connection pool exhaustion", 
      "fixes": ["Increase connection pool size", "Add connection monitoring"],
      "rollback": "Revert connection pool settings to previous values"
    }
  ],
  "confidence": "high"
}
```

#### Database Updates
After processing, the system updates:

1. **Incident Status**
   ```sql
   UPDATE incidents SET status = 'notified' WHERE id = 123;
   ```

2. **Audit Log Entry**
   ```sql
   INSERT INTO audit_logs (incident_id, who, action, details)
   VALUES (123, 'agent', 'notified', '{"ai_summary": "Database experiencing high CPU load..."}');
   ```

### Slack Interactions

When users click buttons in Slack, the system processes the actions via `/slack/actions` endpoint:

#### Button Actions
- **Acknowledge**: Changes status to "acknowledged"
- **Request More Info**: Changes status to "needs_info"  
- **Mark as Resolved**: Changes status to "resolved"

#### Webhook Response Format
```json
{
  "text": "Incident 123 acknowledged by john.doe"
}
```

### Error Handling

#### Common Error Scenarios

1. **Invalid Redis Message**
   ```
   Invalid message format: expected dict
   Missing incident_id in message
   Invalid incident_id format: abc
   Invalid incident_id value: -1
   ```

2. **Database Errors**
   ```
   Error getting database connection: connection refused
   Error fetching incident 123: relation "incidents" does not exist
   ```

3. **OpenAI API Errors**
   ```
   Error calling OpenAI API: Invalid API key
   Error calling OpenAI API: Rate limit exceeded
   ```

4. **Slack API Errors**
   ```
   Error sending Slack message: invalid_auth
   Error sending Slack message: channel_not_found
   ```

### Monitoring and Logs

#### Agent Logs
```
Agent received incident: 123
Database connection pool initialized
Error handling incident message: Invalid incident_id format
```

#### FastAPI Logs  
```
INFO:     127.0.0.1:54321 - "POST /slack/actions HTTP/1.1" 200 OK
ERROR:    Invalid signature from Slack webhook
```

### Troubleshooting

#### Common Issues

1. **Agent not receiving messages**
   - Check Redis connection: `redis-cli ping`
   - Verify Redis channel name in config
   - Check if Redis server is running

2. **Database connection failures**
   - Verify DATABASE_URL format
   - Check PostgreSQL server status
   - Ensure pgvector extension is installed

3. **Slack notifications not appearing**
   - Verify SLACK_BOT_TOKEN has correct permissions
   - Check if bot is added to the target channel
   - Verify SLACK_CHANNEL name format (#channel-name)

4. **OpenAI API failures**
   - Check API key validity
   - Monitor usage limits and billing
   - Verify internet connectivity

#### Health Checks

```bash
# Test database connection
python -c "from app.db import get_conn; print('DB OK' if get_conn() else 'DB FAIL')"

# Test Redis connection  
python -c "import redis; r=redis.from_url('redis://localhost:6379/0'); print('Redis OK' if r.ping() else 'Redis FAIL')"

# Test OpenAI API
python -c "from app.llm_client import client; print('OpenAI OK' if client.models.list() else 'OpenAI FAIL')"
```

## Production Considerations

### Security
- Use environment variables for all secrets
- Enable Slack request verification
- Use HTTPS for webhook endpoints
- Implement rate limiting

### Performance
- Monitor database connection pool usage
- Set up Redis clustering for high availability
- Cache embedding model in memory
- Use async processing for high volume

### Monitoring
- Set up logging aggregation
- Monitor API usage and costs
- Track incident processing times
- Alert on system health metrics
