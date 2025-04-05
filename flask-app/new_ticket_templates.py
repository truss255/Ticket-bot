import os
import logging
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime
import pytz
import json

# Configuration
TIMEZONE = "America/New_York"  # Replace with your timezone
SYSTEM_ISSUES_CHANNEL = "C08JTKR1RPT"  # Replace with your channel ID
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")  # Ensure this is set in your environment

# Initialize Flask app
app = Flask(__name__)

# Initialize Slack client
client = WebClient(token=SLACK_BOT_TOKEN)

# In-memory database (replace with real database in production)
tickets_db = {}

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    """Construct the modal for submitting a new ticket with categorized issue types."""
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

    # Add action buttons with specified emojis
    blocks.append({
        "type": "actions",
        "block_id": f"ticket_update_actions_{ticket_id}",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🔁 Reassign", "emoji": True},
                "action_id": f"reassign_{ticket_id}",
                "value": str(ticket_id)
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🟢 Resolve", "emoji": True},
                "action_id": f"resolve_{ticket_id}",
                "value": str(ticket_id)
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "❌ Close", "emoji": True},
                "action_id": f"close_{ticket_id}",
                "value": str(ticket_id),
                "style": "danger"
            }
        ]
    })

    return blocks

def assign_to_me(ticket_id, user_id):
    """Assign the ticket to the user and update the Slack message."""
    if ticket_id not in tickets_db:
        logger.error(f"Ticket {ticket_id} not found")
        return

    ticket = tickets_db[ticket_id]
    if ticket["status"] != "Open":
        logger.warning(f"Ticket {ticket_id} is not open")
        return

    ticket["assigned_to"] = user_id
    ticket["status"] = "In Progress"
    ticket["updated_at"] = datetime.now(pytz.timezone(TIMEZONE))

    # Update Slack message
    updated_blocks = get_ticket_updated_blocks(
        ticket_id, ticket["priority"], ticket["issue_type"], user_id, "In Progress"
    )
    client.chat_update(
        channel=SYSTEM_ISSUES_CHANNEL,
        ts=ticket["message_ts"],
        blocks=updated_blocks
    )
    logger.info(f"Ticket {ticket_id} assigned to {user_id}")

def resolve_ticket(ticket_id):
    """Resolve the ticket and update the Slack message."""
    if ticket_id not in tickets_db:
        logger.error(f"Ticket {ticket_id} not found")
        return

    ticket = tickets_db[ticket_id]
    if ticket["status"] not in ["Open", "In Progress"]:
        logger.warning(f"Ticket {ticket_id} cannot be resolved from its current status")
        return

    ticket["status"] = "Resolved"
    ticket["updated_at"] = datetime.now(pytz.timezone(TIMEZONE))

    # Update Slack message
    updated_blocks = get_ticket_updated_blocks(
        ticket_id, ticket["priority"], ticket["issue_type"], ticket["assigned_to"], "Resolved"
    )
    client.chat_update(
        channel=SYSTEM_ISSUES_CHANNEL,
        ts=ticket["message_ts"],
        blocks=updated_blocks
    )
    logger.info(f"Ticket {ticket_id} resolved")

def close_ticket(ticket_id):
    """Close the ticket and update the Slack message."""
    if ticket_id not in tickets_db:
        logger.error(f"Ticket {ticket_id} not found")
        return

    ticket = tickets_db[ticket_id]
    if ticket["status"] not in ["Open", "In Progress", "Resolved"]:
        logger.warning(f"Ticket {ticket_id} cannot be closed from its current status")
        return

    ticket["status"] = "Closed"
    ticket["updated_at"] = datetime.now(pytz.timezone(TIMEZONE))

    # Update Slack message
    updated_blocks = get_ticket_updated_blocks(
        ticket_id, ticket["priority"], ticket["issue_type"], ticket["assigned_to"], "Closed"
    )
    client.chat_update(
        channel=SYSTEM_ISSUES_CHANNEL,
        ts=ticket["message_ts"],
        blocks=updated_blocks
    )
    logger.info(f"Ticket {ticket_id} closed")

@app.route('/new-ticket', methods=['POST'])
def new_ticket():
    """Handle the /new-ticket command to open the modal."""
    trigger_id = request.form.get('trigger_id')
    if not trigger_id:
        return jsonify({"text": "Error: No trigger_id"}), 200
    try:
        modal = build_new_ticket_modal()
        client.views_open(trigger_id=trigger_id, view=modal)
        return "", 200
    except SlackApiError as e:
        logger.error(f"Error opening modal: {e}")
        return jsonify({"text": "Error opening modal"}), 200

@app.route('/slack/interactivity', methods=['POST'])
def slack_interactivity():
    """Handle Slack interactivity (button clicks and modal submissions)."""
    payload = json.loads(request.form["payload"])
    if payload["type"] == "view_submission":
        # Handle modal submission
        handle_new_ticket_submission(payload)
        return {"response_action": "clear"}
    elif payload["type"] == "block_actions":
        # Handle button clicks
        action_id = payload["actions"][0]["action_id"]
        ticket_id = int(payload["actions"][0]["value"])
        user_id = payload["user"]["id"]
        if action_id.startswith("assign_to_me_"):
            assign_to_me(ticket_id, user_id)
        elif action_id.startswith("resolve_"):
            resolve_ticket(ticket_id)
        elif action_id.startswith("close_"):
            close_ticket(ticket_id)
        # Add more actions as needed (e.g., reassign)
        return "", 200
    return jsonify({"response_action": "clear"})

def handle_new_ticket_submission(payload):
    """Process the ticket submission, insert into database, post to system channel, and send confirmation DM."""
    state = payload["view"]["state"]["values"]
    user_id = payload["user"]["id"]
    campaign = state["campaign_block"]["campaign_select"]["selected_option"]["value"]
    issue_type = state["issue_type_block"]["issue_type_select"]["selected_option"]["value"]
    priority = state["priority_block"]["priority_select"]["selected_option"]["value"]
    details = state["details_block"]["details_input"]["value"]
    salesforce_link = state.get("salesforce_link_block", {}).get("salesforce_link_input", {}).get("value", "")
    file_url = state.get("file_upload_block", {}).get("file_upload_input", {}).get("value", "No file uploaded")
    now = datetime.now(pytz.timezone(TIMEZONE))

    # Generate ticket ID (for in-memory DB)
    ticket_id = len(tickets_db) + 1

    # Insert into database
    tickets_db[ticket_id] = {
        "created_by": user_id,
        "campaign": campaign,
        "issue_type": issue_type,
        "priority": priority,
        "status": "Open",
        "assigned_to": "Unassigned",
        "details": details,
        "salesforce_link": salesforce_link,
        "file_url": file_url,
        "created_at": now,
        "updated_at": now,
        "message_ts": None  # Will be updated after posting
    }

    # Post to system channel
    message_blocks = get_system_ticket_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url)
    response = client.chat_postMessage(channel=SYSTEM_ISSUES_CHANNEL, blocks=message_blocks, text=f"New Ticket T{ticket_id:03d}")
    tickets_db[ticket_id]["message_ts"] = response["ts"]

    # Send confirmation DM
    confirmation_blocks = get_agent_confirmation_blocks(ticket_id, campaign, issue_type, priority)
    send_dm(user_id, f":white_check_mark: Your ticket T{ticket_id:03d} has been submitted!", confirmation_blocks)

    logger.info(f"Ticket T{ticket_id:03d} submitted successfully by {user_id}")

def send_dm(user_id, text, blocks=None):
    """Send a direct message to the user."""
    try:
        dm_channel = client.conversations_open(users=user_id)["channel"]["id"]
        client.chat_postMessage(channel=dm_channel, text=text, blocks=blocks)
    except SlackApiError as e:
        logger.error(f"Error sending DM: {e}")

if __name__ == "__main__":
    app.run(debug=True)