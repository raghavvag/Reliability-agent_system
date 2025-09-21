"""
Redis Client Wrapper for both Standard Redis and Upstash Redis REST API

This module provides a unified interface for Redis operations that can work with:
1. Standard Redis protocol (local or cloud Redis)
2. Upstash Redis REST API (serverless Redis)

The client automatically chooses the appropriate connection method based on 
available configuration.
"""

import json
import time
from typing import Optional, Dict, Any
from .config import REDIS_URL, UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN

# Try to import both Redis clients
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    from upstash_redis import Redis as UpstashRedis
    UPSTASH_AVAILABLE = True
except ImportError:
    UPSTASH_AVAILABLE = False

class UnifiedRedisClient:
    """
    Unified Redis client that can work with both standard Redis and Upstash Redis REST API
    """
    
    def __init__(self):
        self.client = None
        self.client_type = None
        self._connect()
    
    def _connect(self):
        """Establish connection using the best available method"""
        
        # Priority 1: Try Upstash Redis REST API if credentials are available
        if (UPSTASH_AVAILABLE and 
            UPSTASH_REDIS_REST_URL and 
            UPSTASH_REDIS_REST_TOKEN):
            try:
                self.client = UpstashRedis(
                    url=UPSTASH_REDIS_REST_URL,
                    token=UPSTASH_REDIS_REST_TOKEN
                )
                # Test connection
                self.client.ping()
                self.client_type = "upstash"
                print("✅ Connected to Upstash Redis REST API")
                return
            except Exception as e:
                print(f"⚠️  Failed to connect to Upstash Redis: {e}")
        
        # Priority 2: Fall back to standard Redis
        if REDIS_AVAILABLE and REDIS_URL:
            try:
                self.client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
                # Test connection
                self.client.ping()
                self.client_type = "standard"
                print("✅ Connected to standard Redis")
                return
            except Exception as e:
                print(f"⚠️  Failed to connect to standard Redis: {e}")
        
        # No connection available
        raise ConnectionError("Could not connect to any Redis instance")
    
    def ping(self) -> bool:
        """Test Redis connection"""
        try:
            if self.client_type == "upstash":
                result = self.client.ping()
                return result == "PONG"
            else:
                return self.client.ping()
        except Exception:
            return False
    
    def publish(self, channel: str, message: str) -> int:
        """Publish message to a channel"""
        try:
            if self.client_type == "upstash":
                # Upstash Redis REST API
                result = self.client.publish(channel, message)
                return int(result) if result is not None else 0
            else:
                # Standard Redis
                return self.client.publish(channel, message)
        except Exception as e:
            print(f"Error publishing to Redis: {e}")
            return 0
    
    def subscribe(self, channel: str):
        """Subscribe to a channel (only works with standard Redis)"""
        if self.client_type != "standard":
            raise NotImplementedError("Subscribe only available with standard Redis protocol")
        
        pubsub = self.client.pubsub()
        pubsub.subscribe(channel)
        return pubsub
    
    def get(self, key: str) -> Optional[str]:
        """Get value by key"""
        try:
            if self.client_type == "upstash":
                return self.client.get(key)
            else:
                return self.client.get(key)
        except Exception as e:
            print(f"Error getting from Redis: {e}")
            return None
    
    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Set key-value pair with optional expiration"""
        try:
            if self.client_type == "upstash":
                if ex:
                    result = self.client.setex(key, ex, value)
                else:
                    result = self.client.set(key, value)
                return result == "OK"
            else:
                return self.client.set(key, value, ex=ex)
        except Exception as e:
            print(f"Error setting in Redis: {e}")
            return False
    
    def delete(self, key: str) -> int:
        """Delete key"""
        try:
            if self.client_type == "upstash":
                return self.client.delete(key)
            else:
                return self.client.delete(key)
        except Exception as e:
            print(f"Error deleting from Redis: {e}")
            return 0

class RedisMessageListener:
    """
    Message listener that works with different Redis implementations
    For Upstash (REST API), we'll use polling since it doesn't support pub/sub
    For standard Redis, we'll use proper pub/sub
    """
    
    def __init__(self, redis_client: UnifiedRedisClient, channel: str):
        self.redis_client = redis_client
        self.channel = channel
        self.running = False
    
    def listen(self, callback_func):
        """Listen for messages and call callback_func for each message"""
        self.running = True
        
        if self.redis_client.client_type == "standard":
            # Use proper pub/sub for standard Redis
            self._listen_pubsub(callback_func)
        else:
            # Use polling for Upstash Redis REST API
            self._listen_polling(callback_func)
    
    def _listen_pubsub(self, callback_func):
        """Listen using Redis pub/sub (standard Redis only)"""
        pubsub = self.redis_client.subscribe(self.channel)
        print(f"Agent listening on Redis channel {self.channel} (pub/sub)")
        
        for item in pubsub.listen():
            if not self.running:
                break
            if item["type"] == "message":
                try:
                    data = json.loads(item["data"])
                    callback_func(data)
                except Exception as exc:
                    print("Error handling message:", exc)
    
    def _listen_polling(self, callback_func):
        """Listen using polling (for Upstash REST API)"""
        print(f"Agent listening on Redis channel {self.channel} (polling)")
        message_key = f"queue:{self.channel}"
        
        while self.running:
            try:
                # Poll for messages in a list/queue structure
                # Note: This is a simplified approach. In production, you might want
                # to use a more sophisticated queuing mechanism with Upstash
                message = self.redis_client.get(message_key)
                if message:
                    try:
                        data = json.loads(message)
                        # Remove the processed message
                        self.redis_client.delete(message_key)
                        callback_func(data)
                    except Exception as exc:
                        print("Error handling message:", exc)
                
                # Poll every second
                time.sleep(1)
                
            except Exception as e:
                print(f"Error in polling loop: {e}")
                time.sleep(5)  # Wait longer on error
    
    def stop(self):
        """Stop listening"""
        self.running = False

# Create global Redis client instance
redis_client = UnifiedRedisClient()

def get_redis_client() -> UnifiedRedisClient:
    """Get the global Redis client instance"""
    return redis_client

def publish_message(channel: str, data: Dict[str, Any]) -> int:
    """Convenience function to publish JSON messages"""
    message = json.dumps(data)
    return redis_client.publish(channel, message)

def create_message_listener(channel: str) -> RedisMessageListener:
    """Create a message listener for the specified channel"""
    return RedisMessageListener(redis_client, channel)