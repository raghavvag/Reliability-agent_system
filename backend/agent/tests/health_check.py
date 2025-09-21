#!/usr/bin/env python3
"""
Health check script for Incident Management System

This script verifies that all system components are working correctly.

Usage:
    python tests/health_check.py
"""

import sys
import json
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))

def check_config():
    """Check configuration loading"""
    try:
        from config import DATABASE_URL, REDIS_URL, OPENAI_API_KEY, SLACK_BOT_TOKEN
        print("✅ Configuration loaded successfully")
        
        # Check required variables are set
        if not DATABASE_URL:
            print("❌ DATABASE_URL not set")
            return False
        if not OPENAI_API_KEY:
            print("❌ OPENAI_API_KEY not set")
            return False
        if not SLACK_BOT_TOKEN:
            print("❌ SLACK_BOT_TOKEN not set")
            return False
            
        print("✅ All required environment variables are set")
        return True
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return False

def check_database():
    """Check database connectivity"""
    try:
        from db import connection_pool, init_connection_pool
        
        # Initialize connection pool if not already done
        if connection_pool is None:
            init_connection_pool()
        
        # Test basic connection
        with connection_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                result = cur.fetchone()
                if result[0] == 1:
                    print("✅ Database connection successful")
                else:
                    print("❌ Database query failed")
                    return False
        
        # Check if tables exist
        with connection_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name IN ('incidents', 'memory_item', 'audit_logs', 'raw_events');
                """)
                tables = [row[0] for row in cur.fetchall()]
                
                required_tables = ['incidents', 'memory_item', 'audit_logs', 'raw_events']
                missing_tables = [t for t in required_tables if t not in tables]
                
                if missing_tables:
                    print(f"❌ Missing database tables: {missing_tables}")
                    print("   Run: python tests/setup_database.py")
                    return False
                else:
                    print("✅ All required database tables exist")
        
        return True
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

def check_redis():
    """Check Redis connectivity"""
    try:
        from redis_client import get_redis_client
        
        redis_client = get_redis_client()
        
        if redis_client.ping():
            print("✅ Redis connection successful")
            print(f"   Using: {redis_client.client_type} Redis client")
            
            # Test pub/sub only for standard Redis
            if redis_client.client_type == "standard":
                pubsub = redis_client.subscribe('test_channel')
                redis_client.publish('test_channel', 'test_message')
                
                # Try to get the message (with timeout)
                message = pubsub.get_message(timeout=1)
                if message and message['type'] == 'subscribe':
                    # Get the actual message
                    message = pubsub.get_message(timeout=1)
                    if message and message['data'] == 'test_message':
                        print("✅ Redis pub/sub working")
                    else:
                        print("⚠️  Redis pub/sub may have issues")
                
                pubsub.close()
            else:
                # For Upstash, test basic operations
                test_key = "test_health_check"
                redis_client.set(test_key, "test_value", ex=10)
                value = redis_client.get(test_key)
                if value == "test_value":
                    print("✅ Redis REST API operations working")
                    redis_client.delete(test_key)
                else:
                    print("⚠️  Redis REST API may have issues")
            
            return True
        else:
            print("❌ Redis ping failed")
            return False
            
    except Exception as e:
        print(f"❌ Redis error: {e}")
        return False

def check_openai():
    """Check OpenAI API connectivity"""
    try:
        from llm_client import client
        
        # Try to list models (lightweight API call)
        models = client.models.list()
        if models:
            print("✅ OpenAI API connection successful")
            return True
        else:
            print("❌ OpenAI API returned no models")
            return False
            
    except Exception as e:
        print(f"❌ OpenAI API error: {e}")
        return False

def check_slack():
    """Check Slack API connectivity"""
    try:
        from slack_sdk import WebClient
        from config import SLACK_BOT_TOKEN
        
        client = WebClient(token=SLACK_BOT_TOKEN)
        
        # Test auth
        response = client.auth_test()
        if response["ok"]:
            print(f"✅ Slack API connection successful (bot: {response['user']})")
            return True
        else:
            print("❌ Slack API auth failed")
            return False
            
    except Exception as e:
        print(f"❌ Slack API error: {e}")
        return False

def check_embeddings():
    """Check embedding model loading"""
    try:
        from retriever_pgvector import get_model, embed_text
        
        # Load model
        model = get_model()
        print("✅ Embedding model loaded successfully")
        
        # Test embedding
        test_text = "test incident description"
        embedding = embed_text(test_text)
        
        if isinstance(embedding, list) and len(embedding) == 384:
            print("✅ Text embedding working correctly")
            return True
        else:
            print(f"❌ Unexpected embedding format: {type(embedding)}, length: {len(embedding) if hasattr(embedding, '__len__') else 'unknown'}")
            return False
            
    except Exception as e:
        print(f"❌ Embedding error: {e}")
        return False

def check_sample_data():
    """Check if sample data exists"""
    try:
        from db import connection_pool, init_connection_pool
        
        # Initialize connection pool if not already done
        if connection_pool is None:
            init_connection_pool()
        
        with connection_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM incidents;")
                incident_count = cur.fetchone()[0]
                
                cur.execute("SELECT COUNT(*) FROM memory_item;")
                memory_count = cur.fetchone()[0]
                
                if incident_count > 0 and memory_count > 0:
                    print(f"✅ Sample data exists ({incident_count} incidents, {memory_count} memory items)")
                elif incident_count == 0 and memory_count == 0:
                    print("ℹ️  No sample data found")
                    print("   Run: python tests/setup_database.py --sample-data")
                else:
                    print(f"⚠️  Partial sample data ({incident_count} incidents, {memory_count} memory items)")
        
        return True
        
    except Exception as e:
        print(f"❌ Sample data check error: {e}")
        return False

def main():
    print("🏥 Health Check for Incident Management System")
    print("=" * 50)
    
    checks = [
        ("Configuration", check_config),
        ("Database", check_database),
        ("Redis", check_redis),
        ("OpenAI API", check_openai),
        ("Slack API", check_slack),
        ("Embeddings", check_embeddings),
        ("Sample Data", check_sample_data),
    ]
    
    results = []
    
    for name, check_func in checks:
        print(f"\n🔍 Checking {name}...")
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} check failed with exception: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 50)
    print("📊 Health Check Summary")
    print("=" * 50)
    
    passed = 0
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{name:15} {status}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n🎉 All systems are healthy!")
        print("\n💡 Next steps:")
        print("   1. Start the agent: python app/agent.py")
        print("   2. Start the API server: uvicorn app.handlers:app --host 0.0.0.0 --port 8000")
        print("   3. Test with: python tests/publish_incident_ready.py 1")
    else:
        print(f"\n⚠️  {total - passed} issues found. Please fix the failing checks before running the system.")
        sys.exit(1)

if __name__ == "__main__":
    main()