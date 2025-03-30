import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import psycopg2
from psycopg2 import pool
import csv
import io
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import pytz

# Initialize Flask app
app = Flask(__name__)

# Configure logging to stdout for Railway
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.info("Logging configured.")

# Environment variables (unchanged)
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#systems-issues")
SYSTEM_USERS = os.getenv("SYSTEM_USERS", "").split(",")
ADMIN_CHANNEL = os.getenv("ADMIN_CHANNEL", "#admin-notifications")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")

# Validate environment variables (unchanged)
if not SLACK_BOT_TOKEN:
    logger.error("SLACK_BOT_TOKEN not set.")
    raise ValueError("SLACK_BOT_TOKEN not set.")
if not DATABASE_URL:
    logger.error("DATABASE_URL not set.")
    raise ValueError("DATABASE_URL not set.")

# Initialize Slack client (unchanged)
client = WebClient(token=SLACK_BOT_TOKEN)
logger.info("Slack client initialized.")

def get_channel_id(channel_name):
    """Convert channel name to channel ID"""
    try:
        # Remove the '#' if present
        channel_name = channel_name.lstrip('#')
        
        # Get channel list
        result = client.conversations_list()
        for channel in result["channels"]:
            if channel["name"] == channel_name:
                return channel["id"]
        raise ValueError(f"Channel '{channel_name}' not found")
    except SlackApiError as e:
        logger.error(f"Error getting channel ID: {e}")
        raise

SLACK_CHANNEL_ID = None
try:
    SLACK_CHANNEL_ID = get_channel_id(SLACK_CHANNEL)
    logger.info(f"Successfully resolved channel ID for {SLACK_CHANNEL}")
except Exception as e:
    logger.error(f"Failed to get channel ID for {SLACK_CHANNEL}: {e}")
    raise

# Verify channel exists and bot has access
try:
    channel_info = client.conversations_info(channel=SLACK_CHANNEL.lstrip('#'))
    logger.info(f"Successfully connected to channel {SLACK_CHANNEL}")
except SlackApiError as e:
    logger.error(f"Error accessing channel {SLACK_CHANNEL}: {e}")
    raise ValueError(f"Cannot access channel {SLACK_CHANNEL}. Please verify channel exists and bot is invited.")

# Initialize database connection pool (unchanged)
db_pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
logger.info("Database connection pool initialized.")

# Helper Functions
def is_system_user(user_id):
    logger.debug(f"Checking if user {user_id} is a system user")
    return user_id in SYSTEM_USERS

def find_ticket_by_id(ticket_id):
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
        ticket = cur.fetchone()
        if ticket:
            logger.debug(f"Ticket {ticket_id} found")
            return ticket
        logger.debug(f"Ticket {ticket_id} not found")
        return None
    finally:
        db_pool.putconn(conn)

def update_ticket_status(ticket_id, status, assigned_to=None, message_ts=None, comment=None, action_user_id=None):
    logger.info(f"Updating ticket {ticket_id}: Status={status}, Assigned To={assigned_to}")
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        ticket = find_ticket_by_id(ticket_id)
        if not ticket:
            logger.error("Ticket not found")
            return False

        new_assigned_to = assigned_to if assigned_to else ticket[6]  # assigned_to column
        cur.execute(
            "UPDATE tickets SET status = %s, assigned_to = %s, updated_at = %s WHERE ticket_id = %s",
            (status, new_assigned_to, datetime.now(pytz.timezone(TIMEZONE)), ticket_id)
        )
        if comment:
            cur.execute(
                "INSERT INTO comments (ticket_id, user_id, comment_text, created_at) VALUES (%s, %s, %s, %s)",
                (ticket_id, action_user_id, comment, datetime.now(pytz.timezone(TIMEZONE)))
            )
        conn.commit()
        logger.info("Ticket updated in database")

        if message_ts:
            cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
            updated_ticket = cur.fetchone()
            cur.execute("SELECT user_id, comment_text, created_at FROM comments WHERE ticket_id = %s ORDER BY created_at", (ticket_id,))
            comments = cur.fetchall()
            comments_str = "\n".join([f"<@{c[0]}>: {c[1]} ({c[2]})" for c in comments]) or "N/A"

            message_blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Details"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"✅ *Ticket ID:* T{updated_ticket[0]}\n\n"}},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"📂 *Campaign:* {updated_ticket[2]}\n\n"
                                f"📌 *Issue:* {updated_ticket[3]}\n\n"
                                f"⚡ *Priority:* {updated_ticket[4]} {'🔴' if updated_ticket[4] == 'High' else '🟡' if updated_ticket[4] == 'Medium' else '🔵'}\n\n"
                                f"👤 *Assigned To:* {updated_ticket[6] if updated_ticket[6] != 'Unassigned' else '❌ Unassigned'}\n\n"
                                f"🔄 *Status:* {updated_ticket[5]} {'🟢' if updated_ticket[5] == 'Open' else '🔵' if updated_ticket[5] == 'In Progress' else '🟡' if updated_ticket[5] == 'Resolved' else '🔴'}\n\n"
                    }
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"🖋️ *Details:* {updated_ticket[7]}\n\n🔗 *Salesforce Link:* {updated_ticket[8] or 'N/A'}\n\n"}
                },
                {"type": "section", "text": {"type": "mrkdwn", "text": f"📂 *File Attachment:* {updated_ticket[9]}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"📅 *Created Date:* {updated_ticket[10]}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"💬 *Comments:* {comments_str}\n\n"}},
                {"type": "divider"},
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "🖐 Assign to Me"}, "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(action_user_id) and updated_ticket[5] == "Open" and updated_ticket[6] == "Unassigned" else None,
                        {"type": "button", "text": {"type": "plain_text", "text": "🔁 Reassign"}, "action_id": f"reassign_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(action_user_id) and updated_ticket[5] in ["Open", "In Progress"] else None,
                        {"type": "button", "text": {"type": "plain_text", "text": "❌ Close"}, "action_id": f"close_{ticket_id}", "value": str(ticket_id), "style": "danger"} if is_system_user(action_user_id) and updated_ticket[5] in ["Open", "In Progress"] else None,
                        {"type": "button", "text": {"type": "plain_text", "text": "🟢 Resolve"}, "action_id": f"resolve_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(action_user_id) and updated_ticket[5] in ["Open", "In Progress"] else None,
                        {"type": "button", "text": {"type": "plain_text", "text": "🔄 Reopen"}, "action_id": f"reopen_{ticket_id}", "value": str(ticket_id)} if is_system_user(action_user_id) and updated_ticket[5] in ["Closed", "Resolved"] else None
                    ]
                }
            ]
            message_blocks[-1]["elements"] = [elem for elem in message_blocks[-1]["elements"] if elem]
            client.chat_update(channel=SLACK_CHANNEL, ts=message_ts, blocks=message_blocks)
            logger.info("Slack message updated")
        return True
    except Exception as e:
        logger.error(f"Error updating ticket: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Error updating ticket {ticket_id}: {e}")
        return False
    finally:
        db_pool.putconn(conn)

def generate_ticket_id():
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(ticket_id) FROM tickets")
        max_id = cur.fetchone()[0]
        return max_id + 1 if max_id else 1
    finally:
        db_pool.putconn(conn)

def send_direct_message(user_id, message):
    try:
        client.chat_postMessage(channel=user_id, text=message)
        logger.info(f"DM sent to {user_id}")
    except Exception as e:
        logger.error(f"Error sending DM: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Error sending DM to {user_id}: {e}")

def build_new_ticket_modal():
    campaign_options = [
        {"text": {"type": "plain_text", "text": "Camp Lejeune"}, "value": "Camp Lejeune"},
        {"text": {"type": "plain_text", "text": "Maui Wildfires"}, "value": "Maui Wildfires"},
        {"text": {"type": "plain_text", "text": "LA Wildfire"}, "value": "LA Wildfire"},  # Fixed typo: "personally" to "type"
        {"text": {"type": "plain_text", "text": "Depo-Provera"}, "value": "Depo-Provera"},
        {"text": {"type": "plain_text", "text": "CPP Sick and Family Leave"}, "value": "CPP Sick and Family Leave"}
    ]
    issue_type_options = [
        # 🖥️ System & Software Issues
        {"text": {"type": "plain_text", "text": "🖥️ Salesforce Performance Issues"}, "value": "Salesforce Performance Issues"},
        {"text": {"type": "plain_text", "text": "🖥️ Vonage Dialer Issues"}, "value": "Vonage Dialer Functionality Issues"},
        {"text": {"type": "plain_text", "text": "🖥️ Broken Links (ARA, Co-Counsel, etc.)"}, "value": "Broken or Unresponsive Links"},
        # 💻 Equipment & Hardware Issues
        {"text": {"type": "plain_text", "text": "💻 Equipment & Hardware - Laptop Fails to Power On"}, "value": "Laptop Fails to Power On"},
        {"text": {"type": "plain_text", "text": "💻 Equipment & Hardware - Slow Performance or Freezing Laptop"}, "value": "Slow Performance or Freezing Laptop"},
        {"text": {"type": "plain_text", "text": "💻 Equipment & Hardware - Unresponsive Keyboard or Mouse"}, "value": "Unresponsive Keyboard or Mouse"},
        {"text": {"type": "plain_text", "text": "💻 Equipment & Hardware - Headset/Microphone Malfunction (No Sound, Static, etc.)"}, "value": "Headset/Microphone Malfunction"},
        {"text": {"type": "plain_text", "text": "💻 Equipment & Hardware - Charger or Battery Failure"}, "value": "Charger or Battery Failure"},
        # 🔐 Security & Account Issues
        {"text": {"type": "plain_text", "text": "🔐 Security & Account - Multi-Factor Authentication (MFA) Failure (Security Key)"}, "value": "MFA Failure"},
        {"text": {"type": "plain_text", "text": "🔐 Security & Account - Account Lockout (Gmail or Salesforce)"}, "value": "Account Lockout"},
        # 📑 Client & Document Issues
        {"text": {"type": "plain_text", "text": "📑 Client & Document - Paper Packet Contains Errors or Missing Information"}, "value": "Paper Packet Errors"},
        {"text": {"type": "plain_text", "text": "📑 Client & Document - Paper Packet Mailing Status"}, "value": "Paper Packet Mailing Status"},
        {"text": {"type": "plain_text", "text": "📑 Client & Document - Client Information Update Request"}, "value": "Client Information Update Request"},
        {"text": {"type": "plain_text", "text": "📑 Client & Document - Client System Error (Missing Document Request, Form Submission Failure, Broken or Unresponsive Link)"}, "value": "Client System Error"},
        # 📊 Management-Specific System Issues
        {"text": {"type": "plain_text", "text": "📊 Management Systems - Reports or Dashboards Failing to Load"}, "value": "Reports or Dashboards Failing to Load"},
        {"text": {"type": "plain_text", "text": "📊 Management Systems - Automated Voicemail System Malfunction"}, "value": "Automated Voicemail System Malfunction"},
        {"text": {"type": "plain_text", "text": "📊 Management Systems - Missing or Inaccessible Call Recordings"}, "value": "Missing or Inaccessible Call Recordings"},
        # ❓ Other
        {"text": {"type": "plain_text", "text": "❓ Other (Not Listed Above)"}, "value": "Other"}
    ]
    priority_options = [
        {"text": {"type": "plain_text", "text": "🔵 Low"}, "value": "Low"},
        {"text": {"type": "plain_text", "text": "🟡 Medium"}, "value": "Medium"},
        {"text": {"type": "plain_text", "text": "🔴 High"}, "value": "High"}
    ]
    return {
        "type": "modal",
        "callback_id": "new_ticket",
        "title": {"type": "plain_text", "text": "Submit a New Ticket"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "campaign_block",
                "label": {"type": "plain_text", "text": "📂 Campaign"},
                "element": {
                    "type": "static_select",
                    "action_id": "campaign_select",
                    "placeholder": {"type": "plain_text", "text": "Select a campaign"},
                    "options": campaign_options
                },
                "optional": False
            },
            {
                "type": "input",
                "block_id": "issue_type_block",
                "label": {"type": "plain_text", "text": "📌 Issue Type"},
                "element": {
                    "type": "static_select",
                    "action_id": "issue_type_select",
                    "placeholder": {"type": "plain_text", "text": "Select an issue type"},
                    "options": issue_type_options
                },
                "optional": False
            },
            {
                "type": "input",
                "block_id": "priority_block",
                "label": {"type": "plain_text", "text": "⚡ Priority"},
                "element": {
                    "type": "static_select",
                    "action_id": "priority_select",
                    "placeholder": {"type": "plain_text", "text": "Select priority"},
                    "options": priority_options
                },
                "optional": False
            },
            {
                "type": "input",
                "block_id": "details_block",
                "label": {"type": "plain_text", "text": "🗂 Details"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "details_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Describe the issue"}
                },
                "optional": False
            },
            {
                "type": "input",
                "block_id": "salesforce_link_block",
                "label": {"type": "plain_text", "text": "📎 Salesforce Link (Optional)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "salesforce_link_input",
                    "placeholder": {"type": "plain_text", "text": "Paste Salesforce URL"}
                },
                "optional": True
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "📂 *File Upload:* (Optional) Upload the file to Slack and include the URL in the details field."}
            }
        ]
    }

def build_export_filter_modal():
    return {
        "type": "modal",
        "callback_id": "export_tickets_filter",
        "title": {"type": "plain_text", "text": "Export Tickets"},
        "submit": {"type": "plain_text", "text": "Export"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Select filters for exporting tickets:"}},
            {
                "type": "input",
                "block_id": "status_filter",
                "label": {"type": "plain_text", "text": "Status"},
                "element": {
                    "type": "multi_static_select",
                    "action_id": "status_select",
                    "placeholder": {"type": "plain_text", "text": "Select statuses"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Open"}, "value": "Open"},
                        {"text": {"type": "plain_text", "text": "In Progress"}, "value": "In Progress"},
                        {"text": {"type": "plain_text", "text": "Resolved"}, "value": "Resolved"},
                        {"text": {"type": "plain_text", "text": "Closed"}, "value": "Closed"}
                    ]
                },
                "optional": True
            },
            {
                "type": "input",
                "block_id": "date_range",
                "label": {"type": "plain_text", "text": "Start Date"},
                "element": {
                    "type": "datepicker",
                    "action_id": "start_date",
                    "placeholder": {"type": "plain_text", "text": "Select start date"}
                },
                "optional": True
            },
            {
                "type": "input",
                "block_id": "date_range_end",
                "label": {"type": "plain_text", "text": "End Date"},
                "element": {
                    "type": "datepicker",
                    "action_id": "end_date",
                    "placeholder": {"type": "plain_text", "text": "Select end date"}
                },
                "optional": True
            },
            {
                "type": "input",
                "block_id": "assignee_filter",
                "label": {"type": "plain_text", "text": "Assignee"},
                "element": {
                    "type": "users_select",
                    "action_id": "assignee_select",
                    "placeholder": {"type": "plain_text", "text": "Select an assignee"}
                },
                "optional": True
            }
        ]
    }

# Routes
@app.route("/api/tickets/new-ticket", methods=["POST"])
def new_ticket():
    logger.info("Received /new-ticket request")
    try:
        data = request.form
        trigger_id = data.get("trigger_id")
        modal = build_new_ticket_modal()
        client.views_open(trigger_id=trigger_id, view=modal)
        return "", 200
    except Exception as e:
        logger.error(f"Error in /new-ticket: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Error in /new-ticket: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tickets/agent-tickets", methods=["POST"])
def agent_tickets():
    logger.info("Received /agent-tickets request")
    try:
        data = request.form
        trigger_id = data.get("trigger_id")
        user_id = data.get("user_id")

        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tickets WHERE created_by = %s", (user_id,))
            tickets = cur.fetchall()
        finally:
            db_pool.putconn(conn)

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "🔍 Your Submitted Tickets"}},
            {
                "type": "input",
                "block_id": "status_filter_block",
                "label": {"type": "plain_text", "text": "Filter by Status"},
                "element": {
                    "type": "static_select",
                    "action_id": "status_filter_select",
                    "placeholder": {"type": "plain_text", "text": "Choose a status"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "All"}, "value": "all"},
                        {"text": {"type": "plain_text", "text": "Open"}, "value": "Open"},
                        {"text": {"type": "plain_text", "text": "In Progress"}, "value": "In Progress"},
                        {"text": {"type": "plain_text", "text": "Resolved"}, "value": "Resolved"},
                        {"text": {"type": "plain_text", "text": "Closed"}, "value": "Closed"}
                    ],
                    "initial_option": {"text": {"type": "plain_text", "text": "All"}, "value": "all"}
                }
            },
            {"type": "divider"}
        ]

        if not tickets:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "🎉 You have no submitted tickets.\n\n"}})
        else:
            for ticket in tickets:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*T{ticket[0]}* _({ticket[5]} {'🟢' if ticket[5] == 'Open' else '🔵' if ticket[5] == 'In Progress' else '🟡' if ticket[5] == 'Resolved' else '🔴'})_\n\n"
                                f"*Campaign:* {ticket[2]}\n\n"
                                f"*Issue:* {ticket[3]}\n\n"
                                f"*Date:* {ticket[10]}\n\n"
                    }
                })
                blocks.append({"type": "divider"})

        modal = {
            "type": "modal",
            "callback_id": "agent_tickets_view",
            "title": {"type": "plain_text", "text": "Your Tickets"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": blocks
        }
        client.views_open(trigger_id=trigger_id, view=modal)
        return "", 200
    except Exception as e:
        logger.error(f"Error in /agent-tickets: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Error in /agent-tickets: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tickets/system-tickets", methods=["POST"])
def system_tickets():
    logger.info("Received /system-tickets request")
    try:
        data = request.form
        user_id = data.get("user_id")
        if not is_system_user(user_id):
            return jsonify({"text": "❌ You do not have permission to access system tickets."}), 403

        trigger_id = data.get("trigger_id")

        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tickets WHERE assigned_to = %s", (user_id,))
            assigned_tickets = cur.fetchall()
        finally:
            db_pool.putconn(conn)

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "🎫 System Tickets Dashboard"}},
            {
                "type": "input",
                "block_id": "view_type_block",
                "label": {"type": "plain_text", "text": "Select View"},
                "element": {
                    "type": "static_select",
                    "action_id": "view_type_select",
                    "placeholder": {"type": "plain_text", "text": "Choose a view"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "My Assigned Tickets"}, "value": "my_assigned_tickets"},
                        {"text": {"type": "plain_text", "text": "All Tickets"}, "value": "all_tickets"},
                        {"text": {"type": "plain_text", "text": "Open Tickets"}, "value": "open_tickets"}
                    ],
                    "initial_option": {"text": {"type": "plain_text", "text": "My Assigned Tickets"}, "value": "my_assigned_tickets"}
                }
            },
            {"type": "divider"}
        ]

        if not assigned_tickets:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "🎉 You have no assigned tickets.\n\n"}})
        else:
            for ticket in assigned_tickets:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*T{ticket[0]}* _({ticket[5]} {'🟢' if ticket[5] == 'Open' else '🔵' if ticket[5] == 'In Progress' else '🟡' if ticket[5] == 'Resolved' else '🔴'})_\n\n"
                                f"*Campaign:* {ticket[2]}\n\n"
                                f"*Issue:* {ticket[3]}\n\n"
                                f"*Date:* {ticket[10]}\n\n"
                    },
                    "accessory": {
                        "type": "overflow",
                        "action_id": f"actions_{ticket[0]}",
                        "options": [
                            {"text": {"type": "plain_text", "text": "🔁 Reassign"}, "value": f"reassign_{ticket[0]}"},
                            {"text": {"type": "plain_text", "text": "❌ Close"}, "value": f"close_{ticket[0]}"},
                            {"text": {"type": "plain_text", "text": "🟢 Resolve"}, "value": f"resolve_{ticket[0]}"}
                        ]
                    }
                })
                blocks.append({"type": "divider"})

        blocks.append({
            "type": "actions",
            "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Refine View or Manage More"}, "action_id": "refine_view", "style": "primary"}]
        })

        modal = {
            "type": "modal",
            "callback_id": "system_tickets_view",
            "title": {"type": "plain_text", "text": "System Tickets"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": blocks
        }
        client.views_open(trigger_id=trigger_id, view=modal)
        return "", 200
    except Exception as e:
        logger.error(f"Error in /system-tickets: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Error in /system-tickets: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tickets/ticket-summary", methods=["POST"])
def ticket_summary():
    logger.info("Received /ticket-summary request")
    try:
        data = request.form
        trigger_id = data.get("trigger_id")

        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT status, COUNT(*) FROM tickets GROUP BY status")
            status_counts = cur.fetchall()
            status_dict = {row[0]: row[1] for row in status_counts}
            total_tickets = sum(status_dict.values())
        finally:
            db_pool.putconn(conn)

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "📊 Ticket Summary"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"📋 *Total Tickets:* {total_tickets}\n"
                            f"🟢 *Open:* {status_dict.get('Open', 0)}\n"
                            f"🔵 *In Progress:* {status_dict.get('In Progress', 0)}\n"
                            f"🟡 *Resolved:* {status_dict.get('Resolved', 0)}\n"
                            f"🔴 *Closed:* {status_dict.get('Closed', 0)}\n"
                }
            }
        ]

        modal = {
            "type": "modal",
            "callback_id": "ticket_summary_view",
            "title": {"type": "plain_text", "text": "Ticket Summary"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": blocks
        }
        client.views_open(trigger_id=trigger_id, view=modal)
        return "", 200
    except Exception as e:
        logger.error(f"Error in /ticket-summary: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Error in /ticket-summary: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tickets/export", methods=["POST"])
def export_tickets():
    logger.info("Received export request")
    try:
        data = request.form
        trigger_id = data.get("trigger_id")
        payload = data.get("payload")
        if not payload:
            raise ValueError("No payload provided in request")

        payload_data = json.loads(payload)
        state = payload_data.get("view", {}).get("state", {}).get("values", {})

        # Extract filter options with defaults
        statuses = [opt["value"] for opt in state.get("status_filter", {}).get("status_select", {}).get("selected_options", [])] or []
        start_date_str = state.get("date_range", {}).get("start_date", {}).get("selected_date", None)
        end_date_str = state.get("date_range_end", {}).get("end_date", {}).get("selected_date", None)
        assignee = state.get("assignee_filter", {}).get("assignee_select", {}).get("selected_user", None)

        # Build query
        query = "SELECT * FROM tickets"
        params = []
        conditions = []

        if statuses:
            conditions.append("status IN %s")
            params.append(tuple(statuses))
        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            conditions.append("created_at >= %s")
            params.append(start_date)
        if end_date_str:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)
            conditions.append("created_at <= %s")
            params.append(end_date)
        if assignee:
            conditions.append("assigned_to = %s")
            params.append(assignee)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        # Fetch tickets from DB
        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(query, params if params else None)
            tickets = cur.fetchall()
        finally:
            db_pool.putconn(conn)

        # Handle no results case
        if not tickets:
            client.chat_postMessage(channel=SLACK_CHANNEL, text="❌ No tickets match the selected filters.")
            return jsonify({"response_action": "clear"})

        # Create CSV in memory
        output = io.BytesIO()
        writer = csv.writer(output)
        writer.writerow(["Ticket ID", "Created By", "Campaign", "Issue Type", "Priority", "Status", "Assigned To", "Details", "Salesforce Link", "File URL", "Created At", "Updated At", "Comments"])

        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            for ticket in tickets:
                cur.execute("SELECT user_id, comment_text, created_at FROM comments WHERE ticket_id = %s ORDER BY created_at", (ticket[0],))
                comments = cur.fetchall()
                comments_str = "\n".join([f"{c[0]}: {c[1]} ({c[2]})" for c in comments]) or "N/A"

                writer.writerow([
                    f"T{ticket[0]}",
                    ticket[1],
                    ticket[2],
                    ticket[3],
                    ticket[4],
                    ticket[5],
                    ticket[6],
                    ticket[7],
                    ticket[8] or "N/A",
                    ticket[9] or "N/A",
                    ticket[10],
                    ticket[11],
                    comments_str
                ])
        finally:
            db_pool.putconn(conn)

        # Reset file pointer and send to Slack
        output.seek(0)
        client.files_upload(
            channels=SLACK_CHANNEL_ID,
            file=output,
            filename="tickets_export.csv",
            title="Filtered Tickets Export"
        )
        return jsonify({"response_action": "clear"})

    except Exception as e:
        logger.error(f"Error in ticket export: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Error exporting tickets: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tickets/slack/events", methods=["POST"])
def slack_events():
    logger.info("Received /slack/events request")
    if request.content_type == "application/json":
        data = request.get_json()
        if data.get("type") == "url_verification":
            return data.get("challenge"), 200

    elif request.content_type == "application/x-www-form-urlencoded":
        payload = request.form.get("payload")
        if payload:
            data = json.loads(payload)

            # New ticket submission
            if data.get("type") == "view_submission" and data["view"]["callback_id"] == "new_ticket":
                try:
                    state = data["view"]["state"]["values"]
                    campaign = state["campaign_block"]["campaign_select"]["selected_option"]["value"]
                    issue_type = state["issue_type_block"]["issue_type_select"]["selected_option"]["value"]
                    priority = state["priority_block"]["priority_select"]["selected_option"]["value"]
                    details = state["details_block"]["details_input"]["value"]
                    salesforce_link = state.get("salesforce_link_block", {}).get("salesforce_link_input", {}).get("value", "N/A")
                    user_id = data["user"]["id"]

                    conn = db_pool.getconn()
                    try:
                        cur = conn.cursor()
                        now = datetime.now(pytz.timezone(TIMEZONE))
                        cur.execute(
                            "INSERT INTO tickets (created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING ticket_id",
                            (user_id, campaign, issue_type, priority, "Open", "Unassigned", details, salesforce_link, "No file uploaded", now, now)
                        )
                        ticket_id = cur.fetchone()[0]
                        conn.commit()
                    finally:
                        db_pool.putconn(conn)

                    message_blocks = [
                        {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Details"}},
                        {"type": "section", "text": {"type": "mrkdwn", "text": f"✅ *Ticket ID:* T{ticket_id}\n\n"}},
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"📂 *Campaign:* {campaign}\n\n"
                                        f"📌 *Issue:* {issue_type}\n\n"
                                        f"⚡ *Priority:* {priority} {'🔴' if priority == 'High' else '🟡' if priority == 'Medium' else '🔵'}\n\n"
                                        f"👤 *Assigned To:* ❌ Unassigned\n\n"
                                        f"🔄 *Status:* Open 🟢\n\n"
                            }
                        },
                        {"type": "divider"},
                        {"type": "section", "text": {"type": "mrkdwn", "text": f"🖋️ *Details:* {details}\n\n🔗 *Salesforce Link:* {salesforce_link}\n\n"}},
                        {"type": "section", "text": {"type": "mrkdwn", "text": "📂 *File Attachment:* No file uploaded\n\n"}},
                        {"type": "section", "text": {"type": "mrkdwn", "text": f"📅 *Created Date:* {now}\n\n"}},
                        {"type": "section", "text": {"type": "mrkdwn", "text": "💬 *Comments:* N/A\n\n"}},
                        {"type": "divider"},
                        {
                            "type": "actions",
                            "elements": [
                                {"type": "button", "text": {"type": "plain_text", "text": "🖐 Assign to Me"}, "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(user_id) else None,
                                {"type": "button", "text": {"type": "plain_text", "text": "🔁 Reassign"}, "action_id": f"reassign_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(user_id) else None,
                                {"type": "button", "text": {"type": "plain_text", "text": "❌ Close"}, "action_id": f"close_{ticket_id}", "value": str(ticket_id), "style": "danger"} if is_system_user(user_id) else None,
                                {"type": "button", "text": {"type": "plain_text", "text": "🟢 Resolve"}, "action_id": f"resolve_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(user_id) else None
                            ]
                        }
                    ]
                    message_blocks[-1]["elements"] = [elem for elem in message_blocks[-1]["elements"] if elem]
                    response = client.chat_postMessage(channel=SLACK_CHANNEL_ID, blocks=message_blocks)
                    return jsonify({"response_action": "clear"})
                except Exception as e:
                    logger.error(f"Error in new_ticket submission: {e}")
                    return jsonify({"text": "❌ Ticket submission failed"}), 500

            # Handle block actions
            if data.get("type") == "block_actions":
                action = data["actions"][0]
                action_id = action["action_id"]
                user_id = data["user"]["id"]
                trigger_id = data["trigger_id"]
                message_ts = data["message"]["ts"] if "message" in data else None

                if action_id == "export_all_tickets":
                    if not is_system_user(user_id):
                        return jsonify({"text": "❌ You do not have permission to export tickets."}), 403
                    modal = build_export_filter_modal()
                    client.views_open(trigger_id=trigger_id, view=modal)
                    return "", 200

                ticket_id = int(action["value"]) if action["value"].isdigit() else None
                if ticket_id:
                    if action_id.startswith("assign_to_me_"):
                        modal = {
                            "type": "modal",
                            "callback_id": "assign_to_me_action",
                            "title": {"type": "plain_text", "text": f"Assign T{ticket_id}"},
                            "submit": {"type": "plain_text", "text": "Confirm"},
                            "close": {"type": "plain_text", "text": "Cancel"},
                            "blocks": [
                                {
                                    "type": "input",
                                    "block_id": "comment",
                                    "element": {"type": "plain_text_input", "multiline": True, "action_id": "comment_input", "placeholder": {"type": "plain_text", "text": "Add a comment (optional)"}},
                                    "label": {"type": "plain_text", "text": "Details/Comment"},
                                    "optional": True
                                }
                            ],
                            "private_metadata": json.dumps({"ticket_id": ticket_id, "user_id": user_id, "message_ts": message_ts})
                        }
                        client.views_open(trigger_id=trigger_id, view=modal)
                        return "", 200

                    elif action_id.startswith("reassign_"):
                        modal = {
                            "type": "modal",
                            "callback_id": "reassign_action",
                            "title": {"type": "plain_text", "text": f"Reassign T{ticket_id}"},
                            "submit": {"type": "plain_text", "text": "Confirm"},
                            "close": {"type": "plain_text", "text": "Cancel"},
                            "blocks": [
                                {
                                    "type": "input",
                                    "block_id": "assignee",
                                    "label": {"type": "plain_text", "text": "New Assignee"},
                                    "element": {"type": "users_select", "action_id": "assignee_select"}
                                },
                                {
                                    "type": "input",
                                    "block_id": "comment",
                                    "element": {"type": "plain_text_input", "multiline": True, "action_id": "comment_input", "placeholder": {"type": "plain_text", "text": "Add a comment (optional)"}},
                                    "label": {"type": "plain_text", "text": "Comment"},
                                    "optional": True
                                }
                            ],
                            "private_metadata": json.dumps({"ticket_id": ticket_id, "message_ts": message_ts})
                        }
                        client.views_open(trigger_id=trigger_id, view=modal)
                        return "", 200

                    elif action_id.startswith("close_"):
                        update_ticket_status(ticket_id, "Closed", message_ts=message_ts, action_user_id=user_id)
                        return "", 200

                    elif action_id.startswith("resolve_"):
                        update_ticket_status(ticket_id, "Resolved", message_ts=message_ts, action_user_id=user_id)
                        return "", 200

                    elif action_id.startswith("reopen_"):
                        update_ticket_status(ticket_id, "Open", message_ts=message_ts, action_user_id=user_id)
                        return "", 200

            # Export tickets filter submission
            if data.get("type") == "view_submission" and data["view"]["callback_id"] == "export_tickets_filter":
                state = data["view"]["state"]["values"]
                statuses = [opt["value"] for opt in state.get("status_filter", {}).get("status_select", {}).get("selected_options", [])]
                start_date_str = state.get("date_range", {}).get("start_date", {}).get("selected_date")
                end_date_str = state.get("date_range_end", {}).get("end_date", {}).get("selected_date")
                assignee = state.get("assignee_filter", {}).get("assignee_select", {}).get("selected_user")

                query = "SELECT * FROM tickets"
                params = []
                conditions = []

                if statuses:
                    conditions.append("status IN %s")
                    params.append(tuple(statuses))
                if start_date_str:
                    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
                    conditions.append("created_at >= %s")
                    params.append(start_date)
                if end_date_str:
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)
                    conditions.append("created_at <= %s")
                    params.append(end_date)
                if assignee:
                    conditions.append("assigned_to = %s")
                    params.append(assignee)

                if conditions:
                    query += " WHERE " + " AND ".join(conditions)

                conn = db_pool.getconn()
                try:
                    cur = conn.cursor()
                    cur.execute(query, params)
                    tickets = cur.fetchall()

                    if not tickets:
                        client.chat_postMessage(channel=SLACK_CHANNEL, text="No tickets match the selected filters.")
                        return jsonify({"response_action": "clear"})

                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerow(["Ticket ID", "Created By", "Campaign", "Issue Type", "Priority", "Status", "Assigned To", "Details", "Salesforce Link", "File URL", "Created At", "Updated At", "Comments"])

                    for ticket in tickets:
                        cur.execute("SELECT user_id, comment_text, created_at FROM comments WHERE ticket_id = %s ORDER BY created_at", (ticket[0],))
                        comments = cur.fetchall()
                        comments_str = "\n".join([f"{c[0]}: {c[1]} ({c[2]})" for c in comments]) or "N/A"
                        writer.writerow([f"T{ticket[0]}", ticket[1], ticket[2], ticket[3], ticket[4], ticket[5], ticket[6], ticket[7], ticket[8], ticket[9], ticket[10], ticket[11], comments_str])

                    csv_content = output.getvalue()
                    client.files_upload(channels=SLACK_CHANNEL, content=csv_content, filename="tickets_export.csv", title="Filtered Tickets Export")
                    return jsonify({"response_action": "clear"})
                finally:
                    db_pool.putconn(conn)

            # Assign to me action
            if data.get("type") == "view_submission" and data["view"]["callback_id"] == "assign_to_me_action":
                metadata = json.loads(data["view"]["private_metadata"])
                ticket_id = metadata["ticket_id"]
                user_id = metadata["user_id"]
                message_ts = metadata["message_ts"]
                comment = data["view"]["state"]["values"]["comment"]["comment_input"]["value"] if "comment" in data["view"]["state"]["values"] else None
                update_ticket_status(ticket_id, "In Progress", assigned_to=user_id, message_ts=message_ts, comment=comment, action_user_id=user_id)
                return jsonify({"response_action": "clear"})

            # Reassign action
            if data.get("type") == "view_submission" and data["view"]["callback_id"] == "reassign_action":
                metadata = json.loads(data["view"]["private_metadata"])
                ticket_id = metadata["ticket_id"]
                message_ts = metadata["message_ts"]
                assignee = data["view"]["state"]["values"]["assignee"]["assignee_select"]["selected_user"]
                comment = data["view"]["state"]["values"]["comment"]["comment_input"]["value"] if "comment" in data["view"]["state"]["values"] else None
                update_ticket_status(ticket_id, "In Progress", assigned_to=assignee, message_ts=message_ts, comment=comment, action_user_id=data["user"]["id"])
                return jsonify({"response_action": "clear"})

    return jsonify({"status": "success"}), 200

# Scheduled Tasks
scheduler = BackgroundScheduler(timezone=pytz.timezone(TIMEZONE))

def generate_weekly_summary():
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) FROM tickets GROUP BY status")
        status_counts = cur.fetchall()
        status_dict = {row[0]: row[1] for row in status_counts}
        total_tickets = sum(status_dict.values())

        summary = (
            f"📊 *Weekly Ticket Summary*\n\n"
            f"📋 *Total Tickets:* {total_tickets}\n"
            f"🟢 *Open:* {status_dict.get('Open', 0)}\n"
            f"🔵 *In Progress:* {status_dict.get('In Progress', 0)}\n"
            f"🟡 *Resolved:* {status_dict.get('Resolved', 0)}\n"
            f"🔴 *Closed:* {status_dict.get('Closed', 0)}\n"
        )
        client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=summary)
        logger.info("Weekly summary posted")
    finally:
        db_pool.putconn(conn)

def check_overdue_tickets():
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        seven_days_ago = datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=7)
        cur.execute("SELECT ticket_id, assigned_to FROM tickets WHERE status IN ('Open', 'In Progress') AND created_at < %s", (seven_days_ago,))
        overdue_tickets = cur.fetchall()

        for ticket_id, assignee_id in overdue_tickets:
            if assignee_id and assignee_id != "Unassigned":
                client.chat_postMessage(channel=assignee_id, text=f"⏰ Reminder: Ticket T{ticket_id} is overdue. Please review.")
                logger.info(f"Overdue reminder sent for T{ticket_id}")
    finally:
        db_pool.putconn(conn)

def pin_high_priority_unassigned_tickets():
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT ticket_id, issue_type FROM tickets WHERE priority = 'High' AND assigned_to = 'Unassigned' AND status IN ('Open', 'In Progress')")
        high_priority_unassigned = cur.fetchall()

        if high_priority_unassigned:
            ticket_list = "\n".join([f"- *T{ticket[0]}*: {ticket[1]}" for ticket in high_priority_unassigned])
            message = f"🚨 *High-Priority Unassigned Tickets*\n\n{ticket_list}\n\nPlease assign these tickets ASAP."
            pins = client.pins_list(channel=SLACK_CHANNEL)
            for pin in pins["items"]:
                if pin["type"] == "message" and "High-Priority Unassigned Tickets" in pin["message"]["text"]:
                    client.pins_remove(channel=SLACK_CHANNEL, timestamp=pin["message"]["ts"])
            response = client.chat_postMessage(channel=SLACK_CHANNEL, text=message)
            client.pins_add(channel=SLACK_CHANNEL, timestamp=response["ts"])
            logger.info(f"Pinned {len(high_priority_unassigned)} high-priority unassigned tickets")
    finally:
        db_pool.putconn(conn)

scheduler.add_job(generate_weekly_summary, "cron", day_of_week="mon", hour=9, minute=0)
scheduler.add_job(check_overdue_tickets, "cron", day_of_week="mon", hour=9, minute=0)
scheduler.add_job(pin_high_priority_unassigned_tickets, "interval", hours=1)
scheduler.start()
logger.info("Scheduler started")

atexit.register(lambda: scheduler.shutdown())

if __name__ == "__main__":
    logger.info("Starting Flask server...")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
