from myapp.utils.slack_client import slack_client, verify_slack_connection
from myapp.services.ticket_service import create_ticket, fetch_all_tickets
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_slack_connection():
    """Test Slack connection"""
    result = verify_slack_connection()
    logger.info(f"Slack Connection Test: {'✅ Passed' if result else '❌ Failed'}")
    return result

def test_create_and_fetch_ticket():
    """Test creating and fetching a ticket"""
    try:
        # Create a test ticket
        test_ticket = {
            "ticket_id": "TEST-001",
            "issue": "Test Issue",
            "status": "Open",
            "campaign": "Test Campaign",
            "salesforce_link": "https://test.salesforce.com"
        }
        
        create_result = create_ticket(test_ticket)
        logger.info(f"Create Ticket Test: {'✅ Passed' if create_result else '❌ Failed'}")

        # Fetch tickets
        tickets = fetch_all_tickets()
        logger.info(f"Fetch Tickets Test: {'✅ Passed' if tickets else '❌ Failed'}")
        logger.info(f"Found {len(tickets)} tickets")
        
        return True
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting Slack Integration Tests")
    test_slack_connection()
    test_create_and_fetch_ticket()