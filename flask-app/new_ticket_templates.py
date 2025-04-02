import logging
from flask import jsonify
from slack_sdk.errors import SlackApiError
from datetime import datetime
import pytz

# Configuration (replace with your actual values)
TIMEZONE = "UTC"
SYSTEM_ISSUES_CHANNEL = "#systems-issues"
logger = logging.getLogger(__name__)

# Mock database and Slack client for demonstration (replace with actual implementations)
class MockDB:
    def __init__(self):
        self.tickets = {}
    def getconn(self):
        return self
    def putconn(self, conn):
        pass
    def cursor(self):
        return self
    def execute(self, query, params):
        if "INSERT" in query:
            ticket_id = len(self.tickets) + 1
            self.tickets[ticket_id] = {
                "created_by": params[0], "campaign": params[1], "issue_type": params[2],
                "priority": params[3], "status": params[4], "assigned_to": params[5],
                "details": params[6], "created_at": params[9], "updated_at": params[10]
            }
            return ticket_id
        elif "UPDATE" in query:
            ticket_id = params[2]
            self.tickets[ticket_id]["assigned_to"] = params[0]
            self.tickets[ticket_id]["status"] = params[1]
    def fetchone(self):
        return [max(self.tickets.keys()) if self.tickets else 1]
    def commit(self):
        pass

db_pool = MockDB()

class MockSlackClient:
    def chat_postMessage(self, channel, blocks, text):
        return {"ts": "mock_timestamp"}
    def chat_update(self, channel, ts, blocks):
        pass
    def views_open(self, trigger_id, view):
        pass

client = MockSlackClient()

def send_dm(user_id, text, blocks=None):
    """Mock function to send a DM (replace with actual Slack API call)."""
    logger.info(f"DM sent to {user_id}: {text}")

# Define issue types with categories
issue_types = {
    "🖥️ System & Software Issues": [
        "Salesforce Performance Issues (Freezing or Crashing)",
        "Vonage Dialer Functionality Issues",
        "Broken or Unresponsive Links (ARA, Co-Counsel, Claim Stage, File Upload, etc.)"
    ],
    "💻 Equipment & Hardware Issues": [
        "Laptop Fails to Power On",
        "Slow Performance or Freezing Laptop",
        "Unresponsive Keyboard or Mouse",
        "Headset/Microphone Malfunction (No Sound, Static, etc.)",
        "Charger or Battery Failure"
    ],
    "🔒 Security & Account Issues": [
        "Multi-Factor Authentication (MFA) Failure (Security Key)",
        "Account Lockout (Gmail or Salesforce)"
    ],
    "📄 Client & Document Issues": [
        "Paper Packet Contains Errors or Missing Information",
        "Client System Error (Missing Document Request, Form Submission Failure, Broken or Unresponsive Link)"
    ],
    "📊 Management-Specific System Issues": [
        "Reports or Dashboards Failing to Load",
        "Automated Voicemail System Malfunction",
        "Missing or Inaccessible Call Recordings"
    ]
}

def build_new_ticket_modal():
    """
    Construct the modal for submitting a new ticket with categorized issue types.
    """
    options = []
    for category, sub_issues in issue_types.items():
        for issue in sub_issues:
            options.append({"text": {"type": "plain_text", "text": f"{category} - {issue}"}, "value": issue})
    return {
        "type": "modal",
        "callback_id": "new_ticket",
        "title": {"type": "plain_text", "text": "Submit a New Ticket"},
        "submit": {"type": "plain_text", "text": "Submit ✅"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Please fill out the details below to submit your ticket.*"}},
            {"type": "divider"},
            {"type": "input", "block_id": "campaign_block", "label": {"type": "plain_text", "text": "📂 Campaign"}, "element": {
                "type": "static_select", "action_id": "campaign_select", "placeholder": {"type": "plain_text", "text": "Select a campaign"},
                "options": [
                    {"text": {"type": "plain_text", "text": "Camp Lejeune"}, "value": "Camp Lejeune"},
                    {"text": {"type": "plain_text", "text": "Maui Wildfires"}, "value": "Maui Wildfires"},
                    {"text": {"type": "plain_text", "text": "LA Wildfire"}, "value": "LA Wildfire"},
                    {"text": {"type": "plain_text", "text": "Depo-Provera"}, "value": "Depo-Provera"},
                    {"text": {"type": "plain_text", "text": "CPP Sick and Family Leave"}, "value": "CPP Sick and Family Leave"}
                ]
            }},
            {"type": "input", "block_id": "issue_type_block", "label": {"type": "plain_text", "text": "📌 Issue Type"}, "element": {
                "type": "static_select", "action_id": "issue_type_select", "placeholder": {"type": "plain_text", "text": "Select an issue type"},
                "options": options
            }},
            {"type": "input", "block_id": "priority_block", "label": {"type": "plain_text", "text": "⚡ Priority"}, "element": {
                "type": "static_select", "action_id": "priority_select", "placeholder": {"type": "plain_text", "text": "Select priority"},
                "options": [
                    {"text": {"type": "plain_text", "text": "Low"}, "value": "Low"},
                    {"text": {"type": "plain_text", "text": "Medium"}, "value": "Medium"},
                    {"text": {"type": "plain_text", "text": "High"}, "value": "High"}
                ]
            }},
            {"type": "divider"},
            {"type": "input", "block_id": "details_block", "label": {"type": "plain_text", "text": "✏️ Details"}, "element": {
                "type": "plain_text_input", "action_id": "details_input", "multiline": True, "placeholder": {"type": "plain_text", "text": "Describe the issue in detail"}
            }},
            {"type": "divider"},
            {"type": "input", "block_id": "salesforce_link_block", "label": {"type": "plain_text", "text": "📎 Salesforce Link"}, "element": {
                "type": "plain_text_input", "action_id": "salesforce_link_input", "placeholder": {"type": "plain_text", "text": "Paste Salesforce URL"}
            }, "optional": True},
            {"type": "input", "block_id": "file_upload_block", "label": {"type": "plain_text", "text": "🖼️ Attach Screenshot URL"}, "element": {
                "type": "plain_text_input", "action_id": "file_upload_input", "placeholder": {"type": "plain_text", "text": "Paste URL from DM"}
            }, "optional": True}
        ]
    }

def get_system_ticket_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url):
    """Returns the blocks for posting a new ticket to the systems channel"""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🎟️ *New Ticket Submitted!* (T{ticket_id:03d})"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"👤 *Submitted By:* <@{user_id}>"},
                {"type": "mrkdwn", "text": f"📂 *Campaign:* {campaign}"}
            ]
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"📌 *Issue Type:* {issue_type}"},
                {"type": "mrkdwn", "text": f"⚡ *Priority:* {'🔴 High' if priority == 'High' else '🟡 Medium' if priority == 'Medium' else '🔵 Low'}"}
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"✏️ *Details:* {details}"}
        }
    ]

    # Add Salesforce link if provided
    if salesforce_link:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"📎 *Salesforce Link:* <{salesforce_link}|Click Here>"}
        })

    # Add file URL if provided and not default
    if file_url and file_url != "No file uploaded":
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"🖼️ *Screenshot:* <{file_url}|View Screenshot>"}
        })

    # Add divider before actions
    blocks.append({"type": "divider"})

    # Add Assign to Me button with the specified emoji
    blocks.append({
        "type": "actions",
        "block_id": f"ticket_actions_{ticket_id}",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🔘 Assign to Me", "emoji": True},
                "action_id": f"assign_to_me_{ticket_id}",
                "value": str(ticket_id),
                "style": "primary"
            }
        ]
    })

    return blocks

def get_agent_confirmation_blocks(ticket_id, campaign, issue_type, priority):
    """Returns the blocks for the agent confirmation message"""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "✅ *Ticket Submitted Successfully!*"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"🎟️ *Ticket ID:* T{ticket_id:03d}"},
                {"type": "mrkdwn", "text": f"📂 *Campaign:* {campaign}"}
            ]
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"📌 *Issue Type:* {issue_type}"},
                {"type": "mrkdwn", "text": f"⚡ *Priority:* {'🔴 High' if priority == 'High' else '🟡 Medium' if priority == 'Medium' else '🔵 Low'}"}
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "📣 Your ticket has been posted in `#systems-issues`.\n👀 The systems team has been notified and will review it shortly.\n📊 You can check your ticket status anytime using: `/agent-tickets`"
            }
        }
    ]

def get_ticket_updated_blocks(ticket_id, priority, issue_type, assigned_to, status, comment=None):
    """Returns the blocks for an updated ticket message"""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🎟️ *Ticket Updated!* (T{ticket_id:03d})"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"👤 *Assigned To:* @{assigned_to}"},
                {"type": "mrkdwn", "text": f"🔄 *Status:* {'🟢 Open' if status == 'Open' else '🔵 In Progress' if status == 'In Progress' else '🟡 Resolved' if status == 'Resolved' else '❌ Closed'}"}
            ]
        }
    ]

    # Add comment if provided
    if comment:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"💬 *Comment:* \"{comment}\""}
        })

    # Add divider before actions
    blocks.append({"type": "divider"})

    # Add action buttons
    blocks.append({
        "type": "actions",
        "block_id": f"ticket_update_actions_{ticket_id}",
        "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "🔁 Reassign", "emoji": True},
             "action_id": f"reassign_{ticket_id}", "value": str(ticket_id)},
            {"type": "button", "text": {"type": "plain_text", "text": "🟢 Resolve", "emoji": True},
             "action_id": f"resolve_{ticket_id}", "value": str(ticket_id)},
            {"type": "button", "text": {"type": "plain_text", "text": "❌ Close", "emoji": True},
             "action_id": f"close_{ticket_id}", "value": str(ticket_id), "style": "danger"}
        ]
    })

    return blocks

def new_ticket_command(request, client, db_pool):
    """
    Handle the /new-ticket command to open the ticket submission modal.
    """
    logger.info("Received /api/tickets/new-ticket request")
    trigger_id = request.form.get('trigger_id')
    if not trigger_id:
        logger.error("No trigger_id found")
        return jsonify({"text": "Error: No trigger_id"}), 200
    try:
        modal = build_new_ticket_modal()
        client.views_open(trigger_id=trigger_id, view=modal)
        return "", 200
    except SlackApiError as e:
        logger.error(f"Error opening modal: {e}")
        return jsonify({"text": "Error opening modal"}), 200

def handle_new_ticket_submission(payload, client, db_pool):
    """
    Process the ticket submission, insert into database, post to system channel, and send confirmation DM.
    """
    try:
        state = payload["view"]["state"]["values"]
        user_id = payload["user"]["id"]
        campaign = state["campaign_block"]["campaign_select"]["selected_option"]["value"]
        issue_type = state["issue_type_block"]["issue_type_select"]["selected_option"]["value"]
        priority = state["priority_block"]["priority_select"]["selected_option"]["value"]
        details = state["details_block"]["details_input"]["value"]
        salesforce_link = state.get("salesforce_link_block", {}).get("salesforce_link_input", {}).get("value", "")
        file_url = state.get("file_upload_block", {}).get("file_upload_input", {}).get("value", "No file uploaded")
        now = datetime.now(pytz.timezone(TIMEZONE))

        # Input validation (optional but recommended)
        if not details.strip():
            raise ValueError("Details cannot be empty")

        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tickets (created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING ticket_id",
                (user_id, campaign, issue_type, priority, "Open", "Unassigned", details, salesforce_link, file_url, now, now)
            )
            ticket_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"Ticket T{ticket_id:03d} inserted into database by {user_id}")
        except Exception as db_err:
            logger.error(f"Database error: {db_err}")
            raise
        finally:
            db_pool.putconn(conn)

        message_blocks = get_system_ticket_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url)
        client.chat_postMessage(channel=SYSTEM_ISSUES_CHANNEL, blocks=message_blocks, text=f"New Ticket T{ticket_id:03d}")

        confirmation_blocks = get_agent_confirmation_blocks(ticket_id, campaign, issue_type, priority)
        send_dm(user_id, f":white_check_mark: Your ticket T{ticket_id:03d} has been submitted!", confirmation_blocks)

        logger.info(f"Ticket T{ticket_id:03d} submitted successfully by {user_id}")
        return {"response_action": "clear"}
    except Exception as e:
        logger.error(f"Error processing submission: {e}")
        return {"response_action": "clear"}