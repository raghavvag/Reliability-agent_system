import os, json
import psycopg2
from config import DATABASE_URL

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def get_incident(incident_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT id, event_id, labels, summary_text, anomaly_score, confidence, evidence, status, created_at
      FROM incidents WHERE id = %s
    """, (incident_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
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

def update_incident_status(incident_id, status):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE incidents SET status = %s WHERE id = %s", (status, incident_id))
    conn.commit()
    cur.close()
    conn.close()

def insert_audit_log(incident_id, who, action, details=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO audit_logs (incident_id, who, action, details)
      VALUES (%s, %s, %s, %s)
    """, (incident_id, who, action, json.dumps(details or {})))
    conn.commit()
    cur.close()
    conn.close()
