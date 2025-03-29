import os
import json
import logging
from slack_sdk import WebClient

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configure logging for production
handler = logging.StreamHandler()  # Log to stdout for Railway
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

class Config:
    # Railway automatically provides PORT
    PORT = int(os.environ.get("PORT", 8080))
    
    # Required environment variables
    SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN')
    SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
    TICKET_STORAGE_CHANNEL = os.getenv("TICKET_STORAGE_CHANNEL")
    
    # Optional environment variables with defaults
    SYSTEM_USERS = os.getenv("SYSTEM_USERS", "").split(",")
    TIMEZONE = os.getenv('TIMEZONE', 'UTC')
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'production')
    
    # Validate required environment variables
    required_vars = ['SLACK_BOT_TOKEN', 'SLACK_CHANNEL', 'TICKET_STORAGE_CHANNEL']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(error_msg)
        raise ValueError(error_msg)

# ✅ Initialize Slack client
try:
    client = WebClient(token=Config.SLACK_BOT_TOKEN)
    logger.info("Slack client initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize Slack client: {e}")
    raise

