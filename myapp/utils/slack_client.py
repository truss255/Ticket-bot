from slack_sdk import WebClient
from myapp.config import Config
from myapp.utils.circuit_breaker import CircuitBreaker
import logging

logger = logging.getLogger(__name__)

# Initialize Slack WebClient with bot token
slack_client = WebClient(token=Config.SLACK_BOT_TOKEN) if Config.SLACK_BOT_TOKEN else None

@CircuitBreaker(failure_threshold=3, reset_timeout=300)
def verify_slack_connection():
    """Verify the Slack connection is working with circuit breaker."""
    if not slack_client:
        logger.warning("⚠️ Slack client not initialized")
        return False
        
    try:
        response = slack_client.auth_test()
        scopes = response.get('scope', '').split(',')
        missing_scopes = set(Config.SLACK_BOT_SCOPES) - set(scopes)
        
        if missing_scopes:
            logger.warning(f"⚠️ Missing Slack scopes: {missing_scopes}")
            return False
            
        logger.info(f"✅ Connected to Slack as {response['user']}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to connect to Slack: {e}")
        raise
