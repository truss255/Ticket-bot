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
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

# Load environment variables from .env file (only for local testing)
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = RotatingFileHandler('app.log', maxBytes=1000000, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.info("Logging configured.")

# Environment variables
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#systems-issues")
SYSTEM_USERS = os.getenv("SYSTEM_USERS", "").split(",")
ADMIN_CHANNEL = os.getenv("ADMIN_CHANNEL", "#admin-notifications")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")

# Validate environment variables
if not SLACK_BOT_TOKEN:
    logger.error("SLACK_BOT_TOKEN not set.")
    raise ValueError("SLACK_BOT_TOKEN not set.")
if not DATABASE_URL:
    logger.error("DATABASE_URL not set.")
    raise ValueError("DATABASE_URL not set.")

# Initialize Slack client
client = WebClient(token=SLACK_BOT_TOKEN)
logger.info("Slack client initialized.")

# Initialize database connection pool
db_pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
logger.info("Database connection pool initialized.")

# Helper Functions
def is_system_user(user_id):
    logger.debug(f"Checking if user {user_id} is a system user")
    return user_id in SYSTEM_USERS

def find_ticket_by_id(ticket_id):
    conn = db_pool.getconn()
    try:
        pass  # Add your logic here
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
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
        {"text": {"type": "plain_text", "text": "LA Wildfire"}, "value": "LA Wildfire"},
        {"text": {"type": "plain_text", "text": "Depo-Provera"}, "value": "Depo-Provera"},
        {"text": {"type": "plain_text", "text": "CPP Sick and Family Leave"}, "value": "CPP Sick and Family Leave"}
    ]
    issue_type_options = [
        # 🖥️ System & Software Issues
        {"text": {"type": "plain_text", "text": "🖥️ System & Software - Salesforce Performance Issues (Freezing or Crashing)"}, "value": "Salesforce Performance Issues"},
        {"text": {"type": "plain_text", "text": "🖥️ System & Software - Vonage Dialer Functionality Issues"}, "value": "Vonage Dialer Functionality Issues"},
        {"text": {"type": "plain_text", "text": "🖥️ System & Software - Broken or Unresponsive Links (ARA, Co-Counsel, Claim Stage, File Upload, etc.)"}, "value": "Broken or Unresponsive Links"},
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
                        "text": f"*T{ticket[0]}* _({ticket[5]} {'🟢' if ticket[5] == "Open" else '🔵' if ticket[5] == "In Progress" else '🟡' if ticket[5] == "Resolved" else '🔴'})_\n\n"
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




web: python app.py
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "app.py"]