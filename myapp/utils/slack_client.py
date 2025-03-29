from slack_sdk import WebClient
from myapp.config import Config
import logging

logger = logging.getLogger(__name__)

# Initialize Slack WebClient with bot token
slack_client = WebClient(token=Config.SLACK_BOT_TOKEN)

def verify_slack_connection():
    """Verify the Slack connection is working."""
    try:
        response = slack_client.auth_test()
        logger.info(f"Connected to Slack as {response['user']}")
        return True
    except Exception as e:
        logger.error(f"Failed to connect to Slack: {e}")
        return False
