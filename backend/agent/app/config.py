import os
import sys
from dotenv import load_dotenv
load_dotenv()

# Required environment variables
REQUIRED_VARS = [
    "DATABASE_URL",
    "OPENAI_API_KEY",
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET"
]

def validate_config():
    """Validate that all required environment variables are set"""
    missing_vars = []
    for var in REQUIRED_VARS:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file and ensure all required variables are set.")
        sys.exit(1)

# Validate configuration on import
validate_config()

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_CHANNEL = os.getenv("REDIS_CHANNEL", "incident_ready")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "all-MiniLM-L6-v2")
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "384"))
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#incident-alerts")

# Log configuration (excluding secrets)
print("Configuration loaded:")
print(f"  DATABASE_URL: {'*' * (len(DATABASE_URL) - 10) + DATABASE_URL[-10:] if DATABASE_URL else 'NOT SET'}")
print(f"  REDIS_URL: {REDIS_URL}")
print(f"  REDIS_CHANNEL: {REDIS_CHANNEL}")
print(f"  SLACK_CHANNEL: {SLACK_CHANNEL}")
print(f"  EMBED_MODEL_NAME: {EMBED_MODEL_NAME}")
print(f"  VECTOR_DIM: {VECTOR_DIM}")
print(f"  OPENAI_API_KEY: {'SET' if OPENAI_API_KEY else 'NOT SET'}")
print(f"  SLACK_BOT_TOKEN: {'SET' if SLACK_BOT_TOKEN else 'NOT SET'}")
print(f"  SLACK_SIGNING_SECRET: {'SET' if SLACK_SIGNING_SECRET else 'NOT SET'}")
