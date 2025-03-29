from myapp.utils.slack_client import slack_client
from myapp.config import Config
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def fetch_all_tickets():
    """Retrieves all tickets from Slack storage."""
    try:
        messages = fetch_messages()
        tickets = []
        for msg in messages:
            if "🎫" in msg.get("text", ""):  # Only include messages that are tickets
                tickets.append({
                    "ts": msg.get("ts"),
                    "text": msg.get("text"),
                    "is_system_ticket": is_system_user(msg.get("user", "")),
                    "status": extract_status(msg.get("text", ""))
                })
        return tickets
    except Exception as e:
        logger.error(f"Error fetching all tickets: {e}")
        return []

def extract_status(text):
    """Extract status from ticket text."""
    try:
        status_line = [line for line in text.split("\n") if "Status:" in line]
        if status_line:
            return status_line[0].split("Status:")[1].strip()
        return "Unknown"
    except Exception:
        return "Unknown"

def is_system_user(user_id):
    """Check if a user is a system user."""
    return user_id in Config.SYSTEM_USERS

def fetch_messages():
    """Retrieves ticket data stored as messages in Slack."""
    try:
        response = slack_client.conversations_history(
            channel=Config.TICKET_STORAGE_CHANNEL,
            limit=100
        )
        return response.get("messages", [])
    except Exception as e:
        logger.error(f"Error retrieving Slack messages: {e}")
        return []

def create_ticket(ticket_info):
    """Posts a new ticket as a message in Slack."""
    try:
        return slack_client.chat_postMessage(
            channel=Config.TICKET_STORAGE_CHANNEL,
            text=f"🎫 *New Ticket Created*\n"
                 f"🆔 Ticket ID: {ticket_info['ticket_id']}\n"
                 f"📌 Issue: {ticket_info['issue']}\n"
                 f"🔄 Status: {ticket_info['status']}\n"
                 f"🗂 Campaign: {ticket_info['campaign']}\n"
                 f"🔗 Salesforce: {ticket_info['salesforce_link'] or 'N/A'}\n"
        )
    except Exception as e:
        logger.error(f"Error posting ticket to Slack: {e}")
        raise

def update_ticket_status(ticket_id, status, assigned_to=None, message_ts=None):
    """Update the status of a ticket in Slack."""
    try:
        ticket = find_ticket_by_id(ticket_id)
        if not ticket:
            logger.error(f"Ticket {ticket_id} not found")
            return False

        updated_text = ticket["text"].replace(
            f"Status: {ticket['status']}", 
            f"Status: {status}"
        )
        
        slack_client.chat_update(
            channel=Config.TICKET_STORAGE_CHANNEL,
            ts=ticket["ts"],
            text=updated_text
        )
        
        logger.info(f"Updated status of ticket {ticket_id} to {status}")
        return True
    except Exception as e:
        logger.error(f"Error updating ticket status: {e}")
        return False

def find_ticket_by_id(ticket_id):
    """Find a ticket by its ID in the messages."""
    try:
        messages = fetch_messages()
        for msg in messages:
            if ticket_id in msg.get("text", ""):
                return msg
        return None
    except Exception as e:
        logger.error(f"Error finding ticket: {e}")
        return None

def fetch_agent_tickets(user_id):
    """Fetch tickets submitted by a specific agent."""
    try:
        all_tickets = fetch_all_tickets()
        return [t for t in all_tickets if t.get('user_id') == user_id]
    except Exception as e:
        logger.error(f"Error fetching agent tickets: {e}")
        return []

def fetch_system_tickets():
    """Fetch tickets marked as system tickets."""
    try:
        all_tickets = fetch_all_tickets()
        return [t for t in all_tickets if t.get('is_system_ticket', False)]
    except Exception as e:
        logger.error(f"Error fetching system tickets: {e}")
        return []

def get_ticket_summary():
    """Get summary statistics of tickets."""
    try:
        tickets = fetch_all_tickets()
        open_tickets = [t for t in tickets if t['status'].lower() == 'open']
        closed_tickets = [t for t in tickets if t['status'].lower() == 'closed']
        high_priority = [t for t in tickets if 'high priority' in t.get('text', '').lower()]
        
        # Calculate average resolution time (dummy calculation)
        avg_time = "24 hours"  # Replace with actual calculation
        
        return {
            "open": len(open_tickets),
            "closed": len(closed_tickets),
            "high_priority": len(high_priority),
            "avg_resolution_time": avg_time
        }
    except Exception as e:
        logger.error(f"Error getting ticket summary: {e}")
        return {
            "open": 0,
            "closed": 0,
            "high_priority": 0,
            "avg_resolution_time": "N/A"
        }

