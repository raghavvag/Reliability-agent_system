#!/usr/bin/env python3
"""
Test script to publish incident_ready messages to Redis

Usage:
    python tests/publish_incident_ready.py [incident_id]
    
Examples:
    python tests/publish_incident_ready.py 123
    python tests/publish_incident_ready.py  # prompts for incident_id
"""

import sys
import json
from pathlib import Path

# Add parent directory to path to import config
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.redis_client import get_redis_client
from app.config import REDIS_CHANNEL

def publish_incident(incident_id):
    """Publish incident_ready message to Redis"""
    try:
        # Validate incident_id
        incident_id = int(incident_id)
        if incident_id <= 0:
            print(f"Error: incident_id must be positive, got {incident_id}")
            return False
            
        # Get Redis client
        redis_client = get_redis_client()
        
        # Test connection
        if not redis_client.ping():
            print("Error: Cannot connect to Redis")
            return False
            
        # Prepare message
        message = {"incident_id": incident_id}
        message_json = json.dumps(message)
        
        # Publish message
        result = redis_client.publish(REDIS_CHANNEL, message_json)
        
        if result > 0:
            print(f"✅ Successfully published to Redis:")
            print(f"   Channel: {REDIS_CHANNEL}")
            print(f"   Message: {message_json}")
            print(f"   Subscribers: {result}")
            return True
        else:
            print(f"⚠️  Message published but no subscribers listening on {REDIS_CHANNEL}")
            print(f"   Message: {message_json}")
            return True
            
    except ValueError:
        print(f"Error: Invalid incident_id '{incident_id}', must be an integer")
        return False
    except Exception as e:
        print(f"Error connecting to Redis: {e}")
        return False

def main():
    print("🚀 Incident Ready Message Publisher")
    print("=" * 40)
    print(f"Channel: {REDIS_CHANNEL}")
    print()
    
    # Get incident_id from command line or prompt
    if len(sys.argv) > 1:
        incident_id = sys.argv[1]
    else:
        incident_id = input("Enter incident_id: ").strip()
    
    if not incident_id:
        print("Error: incident_id is required")
        sys.exit(1)
    
    # Publish the message
    success = publish_incident(incident_id)
    
    if success:
        print("\n💡 Next steps:")
        print("   1. Check your agent logs for processing")
        print("   2. Look for Slack notification")
        print("   3. Check database for status updates")
    else:
        print("\n❌ Failed to publish message")
        sys.exit(1)

if __name__ == "__main__":
    main()