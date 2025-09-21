import os, json
import psycopg
from psycopg import pool
from config import DATABASE_URL
import logging

# Connection pool for better performance
connection_pool = None

def init_connection_pool():
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = pool.ConnectionPool(
                DATABASE_URL,
                min_size=1, 
                max_size=20
            )
            print("Database connection pool initialized")
        except Exception as e:
            print(f"Error creating connection pool: {e}")
            raise

def get_conn():
    if connection_pool is None:
        init_connection_pool()
    try:
        return connection_pool.connection()
    except Exception as e:
        print(f"Error getting database connection: {e}")
        raise

def return_conn(conn):
    if conn:
        conn.close()

def get_incident(incident_id):
    if not incident_id or not isinstance(incident_id, int):
        print(f"Invalid incident_id: {incident_id}")
        return None
        
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
          SELECT id, event_id, labels, summary_text, anomaly_score, confidence, evidence, status, created_at
          FROM incidents WHERE id = %s
        """, (incident_id,))
        row = cur.fetchone()
        cur.close()
        
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
    finally:
        if conn:
            return_conn(conn)

def update_incident_status(incident_id, status):
    if not incident_id or not isinstance(incident_id, int):
        print(f"Invalid incident_id: {incident_id}")
        return False
    if not status or not isinstance(status, str):
        print(f"Invalid status: {status}")
        return False
        
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE incidents SET status = %s WHERE id = %s", (status, incident_id))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"Error updating incident {incident_id} status: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            return_conn(conn)

def insert_audit_log(incident_id, who, action, details=None):
    if not incident_id or not isinstance(incident_id, int):
        print(f"Invalid incident_id: {incident_id}")
        return False
    if not who or not action:
        print(f"Invalid who/action: {who}/{action}")
        return False
        
    conn = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
          INSERT INTO audit_logs (incident_id, who, action, details)
          VALUES (%s, %s, %s, %s)
        """, (incident_id, who, action, json.dumps(details or {})))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"Error inserting audit log: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            return_conn(conn)
