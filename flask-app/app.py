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
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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

# Environment variables
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHANNEL = os.getenv("ADMIN_CHANNEL", "#admin-notifications")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
SYSTEM_USERS = os.getenv("SYSTEM_USERS", "").split(",")

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

# Set Slack channel ID
SLACK_CHANNEL_ID = "C08JTKR1RPT"
logger.info(f"Using Slack channel ID: {SLACK_CHANNEL_ID}")

# Verify channel access directly
try:
    test_response = client.chat_postMessage(
        channel=SLACK_CHANNEL_ID,
        text="Bot connection test - please ignore",
        as_user=True
    )
    if test_response["ok"]:
        client.chat_delete(
            channel=SLACK_CHANNEL_ID,
            ts=test_response["ts"]
        )
        logger.info("Successfully connected to channel")
except SlackApiError as e:
    logger.error(f"Error accessing channel: {e}")
    if "missing_scope" in str(e):
        logger.error("Bot needs additional permissions. Please add the following scopes: groups:read")
    raise ValueError("Cannot access channel. Please verify bot permissions and channel access.")

# Initialize database connection pool
db_pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
logger.info("Database connection pool initialized.")

# Initialize the database schema
def init_db():
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id SERIAL PRIMARY KEY,
                created_by VARCHAR(255),
                campaign VARCHAR(255),
                issue_type VARCHAR(255),
                priority VARCHAR(50),
                status VARCHAR(50),
                assigned_to VARCHAR(255),
                details TEXT,
                salesforce_link VARCHAR(255),
                file_url VARCHAR(255),
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS comments (
                comment_id SERIAL PRIMARY KEY,
                ticket_id INTEGER REFERENCES tickets(ticket_id),
                user_id VARCHAR(255),
                comment_text TEXT,
                created_at TIMESTAMP
            );
        """)
        conn.commit()
        logger.info("Database schema initialized.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise
    finally:
        db_pool.putconn(conn)

# Call init_db after pool initialization
init_db()

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
            comments_str = "\n".join([f"<@{c[0]}>: {c[1]} ({c[2].strftime('%m/%d/%Y %H:%M:%S')})" for c in comments]) or "N/A"

            message_blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Updated", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":ticket: *Ticket Updated* | T{updated_ticket[0]} | {updated_ticket[4]} Priority {':fire:' if updated_ticket[4] == 'High' else ':hourglass_flowing_sand:' if updated_ticket[4] == 'Medium' else ''}\n\n"}},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"📂 *Campaign:* {updated_ticket[2]}\n\n"
                                f"📌 *Issue:* {updated_ticket[3]}\n\n"
                                f"⚡ *Priority:* {updated_ticket[4]} {' 🔴' if updated_ticket[4] == 'High' else ' 🟡' if updated_ticket[4] == 'Medium' else ' 🔵'}\n\n"
                                f"👤 *Assigned To:* <@{updated_ticket[6]}>\n\n"
                                f"🔄 *Status:* `{updated_ticket[5]}` {'🟢' if updated_ticket[5] == 'Open' else '🔵' if updated_ticket[5] == 'In Progress' else '🟡' if updated_ticket[5] == 'Resolved' else '🔴'}\n\n"
                    }
                },
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"✏️ *Details:* {updated_ticket[7]}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":link: *Salesforce Link:* {updated_ticket[8] or 'N/A'}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":camera: *Screenshot/Image:* {f'<{updated_ticket[9]}|View Image>' if updated_ticket[9] != 'No file uploaded' else 'No image uploaded'}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"📅 *Created:* {updated_ticket[10].strftime('%m/%d/%Y %I:%M %p')} ({updated_ticket[10].strftime('%A')})\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"💬 *Comments:* {comments_str}\n\n"}},
                {"type": "divider"},
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "🖐 Assign to Me", "emoji": True}, "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(action_user_id) and updated_ticket[5] == "Open" and updated_ticket[6] == "Unassigned" else None,
                        {"type": "button", "text": {"type": "plain_text", "text": "🔁 Reassign", "emoji": True}, "action_id": f"reassign_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(action_user_id) and updated_ticket[5] in ["Open", "In Progress"] else None,
                        {"type": "button", "text": {"type": "plain_text", "text": "❌ Close", "emoji": True}, "action_id": f"close_{ticket_id}", "value": str(ticket_id), "style": "danger"} if is_system_user(action_user_id) and updated_ticket[5] in ["Open", "In Progress"] else None,
                        {"type": "button", "text": {"type": "plain_text", "text": "🟢 Resolve", "emoji": True}, "action_id": f"resolve_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(action_user_id) and updated_ticket[5] in ["Open", "In Progress"] else None,
                        {"type": "button", "text": {"type": "plain_text", "text": "🔄 Reopen", "emoji": True}, "action_id": f"reopen_{ticket_id}", "value": str(ticket_id)} if is_system_user(action_user_id) and updated_ticket[5] in ["Closed", "Resolved"] else None
                    ]
                }
            ]
            message_blocks[-1]["elements"] = [elem for elem in message_blocks[-1]["elements"] if elem]
            client.chat_update(channel=SLACK_CHANNEL_ID, ts=message_ts, blocks=message_blocks)
            logger.info("Slack message updated")
        return True
    except Exception as e:
        logger.error(f"Error updating ticket: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Error updating ticket {ticket_id}: {e}")
        return False
    finally:
        db_pool.putconn(conn)

def build_new_ticket_modal():
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
                    "options": [
                        {"text": {"type": "plain_text", "text": "Camp Lejeune"}, "value": "Camp Lejeune"},
                        {"text": {"type": "plain_text", "text": "Maui Wildfires"}, "value": "Maui Wildfires"},
                        {"text": {"type": "plain_text", "text": "LA Wildfire"}, "value": "LA Wildfire"},
                        {"text": {"type": "plain_text", "text": "Depo-Provera"}, "value": "Depo-Provera"},
                        {"text": {"type": "plain_text", "text": "CPP Sick and Family Leave"}, "value": "CPP Sick and Family Leave"}
                    ]
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
                    "options": [
                        {"text": {"type": "plain_text", "text": "🖥️ Salesforce Issues (Freeze/Crash)"}, "value": "Salesforce Performance Issues"},
                        {"text": {"type": "plain_text", "text": "🖥️ Vonage Dialer Issues"}, "value": "Vonage Dialer Functionality Issues"},
                        {"text": {"type": "plain_text", "text": "🖥️ Broken Links (ARA, etc.)"}, "value": "Broken or Unresponsive Links"},
                        {"text": {"type": "plain_text", "text": "💻 Laptop Won’t Power On"}, "value": "Laptop Fails to Power On"},
                        {"text": {"type": "plain_text", "text": "💻 Slow/Freezing Laptop"}, "value": "Slow Performance or Freezing Laptop"},
                        {"text": {"type": "plain_text", "text": "💻 Unresponsive Keyboard/Mouse"}, "value": "Unresponsive Keyboard or Mouse"},
                        {"text": {"type": "plain_text", "text": "💻 Headset Mic Issues (No Sound)"}, "value": "Headset/Microphone Malfunction"},
                        {"text": {"type": "plain_text", "text": "💻 Charger/Battery Failure"}, "value": "Charger or Battery Failure"},
                        {"text": {"type": "plain_text", "text": "🔐 MFA Failure (Security Key)"}, "value": "MFA Failure"},
                        {"text": {"type": "plain_text", "text": "🔐 Account Lockout (Gmail/SF)"}, "value": "Account Lockout"},
                        {"text": {"type": "plain_text", "text": "📑 Paper Packet Errors"}, "value": "Paper Packet Errors"},
                        {"text": {"type": "plain_text", "text": "📑 Packet Mailing Status"}, "value": "Paper Packet Mailing Status"},
                        {"text": {"type": "plain_text", "text": "📑 Client Info Update"}, "value": "Client Information Update Request"},
                        {"text": {"type": "plain_text", "text": "📑 Client System Error"}, "value": "Client System Error"},
                        {"text": {"type": "plain_text", "text": "📊 Reports/Dashboards Fail"}, "value": "Reports or Dashboards Failing to Load"},
                        {"text": {"type": "plain_text", "text": "📊 Voicemail System Fail"}, "value": "Automated Voicemail System Malfunction"},
                        {"text": {"type": "plain_text", "text": "📊 Missing Call Recordings"}, "value": "Missing or Inaccessible Call Recordings"},
                        {"text": {"type": "plain_text", "text": "❓ Other"}, "value": "Other"}
                    ]
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
                    "options": [
                        {"text": {"type": "plain_text", "text": "🔵 Low"}, "value": "Low"},
                        {"text": {"type": "plain_text", "text": "🟡 Medium"}, "value": "Medium"},
                        {"text": {"type": "plain_text", "text": "🔴 High"}, "value": "High"}
                    ]
                },
                "optional": False
            },
            {
                "type": "input",
                "block_id": "details_block",
                "label": {"type": "plain_text", "text": "✏️ Details"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "details_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Describe the issue in detail"}
                },
                "optional": False
            },
            {
                "type": "input",
                "block_id": "salesforce_link_block",
                "label": {"type": "plain_text", "text": "📎 Salesforce Link"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "salesforce_link_input",
                    "placeholder": {"type": "plain_text", "text": "Paste Salesforce URL"}
                },
                "optional": True
            },
            {
                "type": "input",
                "block_id": "file_upload_block",
                "label": {"type": "plain_text", "text": "📷 Screenshot/Image Upload"},
                "element": {
                    "type": "file_input",
                    "action_id": "file_upload_input"
                },
                "optional": True
            }
        ]
    }

# Routes
@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "ok",
        "message": "Ticket Bot is running",
        "endpoints": [
            "/api/tickets/new-ticket",
            "/api/tickets/agent-tickets",
            "/api/tickets/system-tickets",
            "/api/tickets/ticket-summary",
            "/api/tickets/slack/interactivity",
            "/api/tickets/slack/events"
        ]
    })

@app.route('/api/tickets/agent-tickets', methods=['POST'])
def agent_tickets():
    logger.info("Received /api/tickets/agent-tickets request")
    try:
        # Log the request data for debugging
        logger.info(f"Request form data: {request.form}")

        user_id = request.form.get('user_id')
        if not user_id:
            return jsonify({"text": "Error: Could not identify user."}), 200

        # Fetch tickets submitted by this user
        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tickets WHERE created_by = %s ORDER BY created_at DESC", (user_id,))
            tickets = cur.fetchall()
        finally:
            db_pool.putconn(conn)

        if not tickets:
            return jsonify({"text": "You haven't submitted any tickets yet."}), 200

        # Build a modal to display the tickets
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🗂️ Your Submitted Tickets"}
            }
        ]

        for ticket in tickets:
            ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at = ticket

            # Define status emoji
            status_emoji = "🟢" if status == "Open" else "🔵" if status == "In Progress" else "🟡" if status == "Resolved" else "🔴"
            priority_emoji = "🔴" if priority == "High" else "🟡" if priority == "Medium" else "🔵"

            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":ticket: *T{ticket_id} - {status}* {status_emoji}"
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👀 View Progress", "emoji": True},
                    "value": str(ticket_id),
                    "action_id": f"view_ticket_progress_{ticket_id}"
                }
            })

            # Add ticket details in a more spaced out format
            blocks.append({
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f":file_folder: Campaign: {campaign}"},
                    {"type": "mrkdwn", "text": f":pushpin: Issue: {issue_type}"}
                ]
            })

            blocks.append({
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f":zap: Priority: {priority} {priority_emoji}"},
                    {"type": "mrkdwn", "text": f":bust_in_silhouette: Assigned To: {f'@{assigned_to}' if assigned_to != 'Unassigned' else ':x: Unassigned'}"},
                    {"type": "mrkdwn", "text": f":calendar: Created: {created_at.strftime('%m/%d/%Y')}"}
                ]
            })

        # Add status explanation footer
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "🔹 Updated Features", "emoji": True}
        })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": ":white_check_mark: Agents can track ticket progress by checking the status"}
            ]
        })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": ":white_check_mark: Statuses are color-coded:"}
            ]
        })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": ":large_green_circle: Open (Not yet assigned)"}
            ]
        })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": ":large_blue_circle: In Progress (A system user is working on it)"}
            ]
        })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": ":yellow_circle: Resolved (Issue fixed, but not yet closed)"}
            ]
        })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": ":red_circle: Closed (No further action needed)"}
            ]
        })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": ":white_check_mark: Clicking \"View Progress\" opens a detailed modal with updates"}
            ]
        })

        return jsonify({
            "response_type": "ephemeral",
            "blocks": blocks
        }), 200
    except Exception as e:
        logger.error(f"Error in /api/tickets/agent-tickets: {e}")
        return jsonify({"text": "❌ An error occurred. Please try again later."}), 200

@app.route('/api/tickets/system-tickets', methods=['POST'])
def system_tickets():
    logger.info("Received /api/tickets/system-tickets request")
    try:
        # Log the request data for debugging
        logger.info(f"Request form data: {request.form}")

        user_id = request.form.get('user_id')
        if not user_id:
            return jsonify({"text": "Error: Could not identify user."}), 200

        # Check if user is a system user
        if not is_system_user(user_id):
            return jsonify({"text": "❌ You do not have permission to view system tickets."}), 200

        # Fetch all tickets
        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tickets ORDER BY created_at DESC")
            tickets = cur.fetchall()
        finally:
            db_pool.putconn(conn)

        if not tickets:
            return jsonify({"text": "There are no tickets in the system."}), 200

        # Build a modal to display the tickets
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "All System Tickets"}
            }
        ]

        for ticket in tickets:
            ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at = ticket
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Ticket T{ticket_id}*\n" +
                            f"*Created By:* <@{created_by}>\n" +
                            f"*Campaign:* {campaign}\n" +
                            f"*Issue:* {issue_type}\n" +
                            f"*Priority:* {priority}\n" +
                            f"*Status:* {status}\n" +
                            f"*Assigned To:* {assigned_to if assigned_to != 'Unassigned' else 'Unassigned'}\n" +
                            f"*Created:* {created_at.strftime('%m/%d/%Y %H:%M')}\n"
                }
            })
            blocks.append({"type": "divider"})

        return jsonify({
            "response_type": "ephemeral",
            "blocks": blocks
        }), 200
    except Exception as e:
        logger.error(f"Error in /api/tickets/system-tickets: {e}")
        return jsonify({"text": "❌ An error occurred. Please try again later."}), 200

@app.route('/api/tickets/ticket-summary', methods=['POST'])
def ticket_summary():
    logger.info("Received /api/tickets/ticket-summary request")
    try:
        # Log the request data for debugging
        logger.info(f"Request form data: {request.form}")

        user_id = request.form.get('user_id')
        if not user_id:
            return jsonify({"text": "Error: Could not identify user."}), 200

        # Check if user is a system user
        if not is_system_user(user_id):
            return jsonify({"text": "❌ You do not have permission to view ticket summary."}), 200

        # Fetch ticket statistics
        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            # Total tickets
            cur.execute("SELECT COUNT(*) FROM tickets")
            total_tickets = cur.fetchone()[0]

            # Open tickets
            cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Open'")
            open_tickets = cur.fetchone()[0]

            # In Progress tickets
            cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'In Progress'")
            in_progress_tickets = cur.fetchone()[0]

            # Resolved tickets
            cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Resolved'")
            resolved_tickets = cur.fetchone()[0]

            # Closed tickets
            cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Closed'")
            closed_tickets = cur.fetchone()[0]

            # High priority tickets
            cur.execute("SELECT COUNT(*) FROM tickets WHERE priority = 'High'")
            high_priority = cur.fetchone()[0]

            # Unassigned tickets
            cur.execute("SELECT COUNT(*) FROM tickets WHERE assigned_to = 'Unassigned'")
            unassigned = cur.fetchone()[0]
        finally:
            db_pool.putconn(conn)

        # Build a response with the statistics
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Ticket Summary"}
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Total Tickets:* {total_tickets}\n" +
                            f"*Open:* {open_tickets}\n" +
                            f"*In Progress:* {in_progress_tickets}\n" +
                            f"*Resolved:* {resolved_tickets}\n" +
                            f"*Closed:* {closed_tickets}\n" +
                            f"*High Priority:* {high_priority}\n" +
                            f"*Unassigned:* {unassigned}\n"
                }
            }
        ]

        return jsonify({
            "response_type": "ephemeral",
            "blocks": blocks
        }), 200
    except Exception as e:
        logger.error(f"Error in /api/tickets/ticket-summary: {e}")
        return jsonify({"text": "❌ An error occurred. Please try again later."}), 200

@app.route('/api/tickets/new-ticket', methods=['POST'])
def slack_new_ticket_command():
    logger.info("Received /api/tickets/new-ticket request")
    try:
        # Log the request data for debugging
        logger.info(f"Request form data: {request.form}")
        logger.info(f"Request headers: {request.headers}")

        # Verify the command is from Slack
        if request.form.get('command') != '/new-ticket':
            logger.warning(f"Unexpected command: {request.form.get('command')}")

        trigger_id = request.form.get('trigger_id')
        logger.info(f"Trigger ID: {trigger_id}")

        if not trigger_id:
            logger.error("No trigger_id found in the request")
            return jsonify({"text": "Error: Could not process your request. Please try again."}), 200

        # Log the Slack token (first few characters for security)
        token_preview = SLACK_BOT_TOKEN[:10] + "..." if SLACK_BOT_TOKEN else "None"
        logger.info(f"Using Slack token: {token_preview}")

        modal = build_new_ticket_modal()
        logger.info("Built new ticket modal")

        response = client.views_open(trigger_id=trigger_id, view=modal)
        logger.info(f"Slack API response: {response}")

        return "", 200
    except Exception as e:
        logger.error(f"Error in /slack/commands/new-ticket: {e}")
        return jsonify({"text": "❌ An error occurred. Please try again later."}), 200

@app.route('/new-ticket', methods=['POST'])
def new_ticket():
    logger.info("Received /new-ticket request")
    try:
        # Log the request data for debugging
        logger.info(f"Request form data: {request.form}")
        logger.info(f"Request headers: {request.headers}")

        trigger_id = request.form.get('trigger_id')
        logger.info(f"Trigger ID: {trigger_id}")

        if not trigger_id:
            logger.error("No trigger_id found in the request")
            return jsonify({"error": "No trigger_id found"}), 400

        # Log the Slack token (first few characters for security)
        token_preview = SLACK_BOT_TOKEN[:10] + "..." if SLACK_BOT_TOKEN else "None"
        logger.info(f"Using Slack token: {token_preview}")

        modal = build_new_ticket_modal()
        logger.info("Built new ticket modal")

        response = requests.post(
            "https://slack.com/api/views.open",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            json={"trigger_id": trigger_id, "view": modal}
        )

        # Log the response from Slack
        logger.info(f"Slack API response: {response.status_code} - {response.text}")

        return jsonify(response.json())
    except Exception as e:
        logger.error(f"Error in /new-ticket: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/tickets/slack/interactivity', methods=['POST'])
def handle_interactivity():
    logger.info("Received /api/tickets/slack/interactivity request")
    try:
        payload = request.form.get('payload')
        data = json.loads(payload)
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
                            "element": {
                                "type": "plain_text_input",
                                "multiline": True,
                                "action_id": "comment_input",
                                "placeholder": {"type": "plain_text", "text": "Add a comment (optional)"}
                            },
                            "label": {"type": "plain_text", "text": "Comment"},
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
                            "element": {
                                "type": "plain_text_input",
                                "multiline": True,
                                "action_id": "comment_input",
                                "placeholder": {"type": "plain_text", "text": "Add a comment (optional)"}
                            },
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
            elif action_id.startswith("view_ticket_progress_"):
                # Get ticket details and comments
                conn = db_pool.getconn()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
                    ticket = cur.fetchone()
                    if not ticket:
                        return jsonify({"text": "Ticket not found"}), 200

                    # Get comments/updates for this ticket
                    cur.execute("SELECT user_id, comment_text, created_at FROM comments WHERE ticket_id = %s ORDER BY created_at", (ticket_id,))
                    comments = cur.fetchall()

                    # Get ticket history
                    ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at = ticket

                    # Define status emoji
                    status_emoji = "🟢" if status == "Open" else "🔵" if status == "In Progress" else "🟡" if status == "Resolved" else "🔴"
                    priority_emoji = "🔴" if priority == "High" else "🟡" if priority == "Medium" else "🔵"

                    # Build updates list
                    updates = [f"1️⃣ *{created_at.strftime('%m/%d/%Y %I:%M %p')}:* Ticket submitted by <@{created_by}>"]

                    # Add comments as updates
                    for i, (comment_user, comment_text, comment_date) in enumerate(comments, 2):
                        updates.append(f"{i}️⃣ *{comment_date.strftime('%m/%d/%Y %I:%M %p')}:* {comment_text} - <@{comment_user}>")

                    # If no comments, add a note about status
                    if not comments and status != "Open":
                        updates.append(f"2️⃣ *{updated_at.strftime('%m/%d/%Y %I:%M %p')}:* Status changed to {status}")

                    # Build the modal
                    blocks = [
                        {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Progress", "emoji": True}},
                        {"type": "divider"},
                        # Ticket ID and Status in a prominent section
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*T{ticket_id}* - `{status}` {status_emoji}"
                            }
                        },
                        # Campaign and Issue in a context block for cleaner appearance
                        {
                            "type": "context",
                            "elements": [
                                {"type": "mrkdwn", "text": f":file_folder: *Campaign:* {campaign}"},
                                {"type": "mrkdwn", "text": f":pushpin: *Issue:* {issue_type}"}
                            ]
                        },
                        # Priority and Assignment in a context block
                        {
                            "type": "context",
                            "elements": [
                                {"type": "mrkdwn", "text": f":zap: *Priority:* {priority} {priority_emoji}"},
                                {"type": "mrkdwn", "text": f":bust_in_silhouette: *Assigned To:* {f'@{assigned_to}' if assigned_to != 'Unassigned' else ':x: Unassigned'}"},
                                {"type": "mrkdwn", "text": f":calendar: *Created:* {created_at.strftime('%m/%d/%Y')}"}
                            ]
                        },
                        {"type": "divider"},
                        # Header for updates
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": "🔧 Recent Updates", "emoji": True}
                        }
                    ]

                    # Add each update as a separate context block for better spacing
                    for update in updates:
                        blocks.append({
                            "type": "context",
                            "elements": [
                                {"type": "mrkdwn", "text": update}
                            ]
                        })

                    # Add notification about updates
                    blocks.append({
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": ":bell: *You will receive updates when the status changes.*"}
                        ]
                    })

                    # Show the modal
                    modal = {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Ticket Progress"},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": blocks
                    }
                    client.views_open(trigger_id=trigger_id, view=modal)

                finally:
                    db_pool.putconn(conn)
                return "", 200

        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error in /slack/interactivity: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/tickets/slack/events', methods=['POST'])
def handle_slack_events():
    logger.info("Received Slack event")
    try:
        data = json.loads(request.form.get('payload'))

        # Handle ticket submission
        if data.get("type") == "view_submission" and data["view"]["callback_id"] == "new_ticket":
            try:
                state = data["view"]["state"]["values"]
                campaign = state["campaign_block"]["campaign_select"]["selected_option"]["value"]
                issue_type = state["issue_type_block"]["issue_type_select"]["selected_option"]["value"]
                priority = state["priority_block"]["priority_select"]["selected_option"]["value"]
                details = state["details_block"]["details_input"]["value"]
                salesforce_link = state.get("salesforce_link_block", {}).get("salesforce_link_input", {}).get("value", "N/A")
                user_id = data["user"]["id"]

                # Check for file upload
                file_url = "No file uploaded"
                if "file_upload_block" in state and "file_upload_input" in state["file_upload_block"]:
                    file_info = state["file_upload_block"]["file_upload_input"]
                    if file_info and "files" in file_info and len(file_info["files"]) > 0:
                        file_id = file_info["files"][0]["id"]
                        # Get file info from Slack API
                        try:
                            file_response = client.files_info(file=file_id)
                            if file_response and file_response["ok"]:
                                file_url = file_response["file"]["url_private"]
                                logger.info(f"File uploaded: {file_url}")
                        except Exception as file_err:
                            logger.error(f"Error getting file info: {file_err}")

                conn = db_pool.getconn()
                try:
                    cur = conn.cursor()
                    now = datetime.now(pytz.timezone(TIMEZONE))
                    cur.execute(
                        "INSERT INTO tickets (created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING ticket_id",
                        (user_id, campaign, issue_type, priority, "Open", "Unassigned", details, salesforce_link, file_url, now, now)
                    )
                    ticket_id = cur.fetchone()[0]
                    conn.commit()
                finally:
                    db_pool.putconn(conn)

                # Post the ticket details message to the channel
                message_blocks = [
                    {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Details", "emoji": True}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": f":ticket: *New Ticket Alert* | T{ticket_id} | {priority} Priority {':fire:' if priority == 'High' else ':hourglass_flowing_sand:' if priority == 'Medium' else ''}\n\n"}},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"📂 *Campaign:* {campaign}\n\n"
                                    f"📌 *Issue:* {issue_type}\n\n"
                                    f"⚡ *Priority:* {priority} {' 🔴' if priority == 'High' else ' 🟡' if priority == 'Medium' else ' 🔵'}\n\n"
                                    f"👤 *Submitted By:* <@{user_id}>\n\n"
                                    f"🔄 *Status:* `Open` 🟢\n\n"
                        }
                    },
                    {"type": "divider"},
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"✏️ *Details:* {details}\n\n"}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": f":link: *Salesforce Link:* {salesforce_link}\n\n"}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": f":camera: *Screenshot/Image:* {f'<{file_url}|View Image>' if file_url != 'No file uploaded' else 'No image uploaded'}\n\n"}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": f":calendar: *Created:* {now.strftime('%m/%d/%Y %I:%M %p')} ({now.strftime('%A')})\n\n"}},
                    {"type": "divider"},
                    {
                        "type": "actions",
                        "elements": [
                            {"type": "button", "text": {"type": "plain_text", "text": "🖐 Assign to Me", "emoji": True}, "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(user_id) else None
                        ]
                    }
                ]
                message_blocks[-1]["elements"] = [elem for elem in message_blocks[-1]["elements"] if elem]
                # Post ticket to main channel
                response = client.chat_postMessage(channel=SLACK_CHANNEL_ID, blocks=message_blocks)

                # Send notification to admin channel
                admin_notification = f":ticket: *New Ticket Alert* | T{ticket_id} | {priority} Priority\n" + \
                                    f">*Issue:* {issue_type}\n" + \
                                    f">*Submitted by:* <@{user_id}>\n" + \
                                    f">*Campaign:* {campaign}"
                try:
                    client.chat_postMessage(channel=ADMIN_CHANNEL, text=admin_notification)
                except Exception as admin_err:
                    logger.error(f"Error sending admin notification: {admin_err}")

                # Show confirmation modal to the agent
                confirmation_view = {
                    "type": "modal",
                    "callback_id": "ticket_confirmation",
                    "title": {"type": "plain_text", "text": "Ticket Submitted"},
                    "close": {"type": "plain_text", "text": "Close"},
                    "blocks": [
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": "🎉 Ticket Submitted Successfully!", "emoji": True}
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"✅ *Ticket ID:* T{ticket_id}\n"
                                        f"📂 *Campaign:* {campaign}\n"
                                        f"📌 *Issue Type:* {issue_type}\n"
                                        f"⚡ *Priority:* {priority} {' 🔴' if priority == 'High' else ' 🟡' if priority == 'Medium' else ' 🔵'}\n"
                                        f"👤 *Assigned To:* ❌ Unassigned\n"
                                        f"🔄 *Status:* Open 🟢\n"
                                        f"📅 *Created On:* {now.strftime('%m/%d/%Y')}"
                            }
                        },
                        {
                            "type": "divider"
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"🔔 Your ticket has been posted in <#{SLACK_CHANNEL_ID}>.\n"
                                        f"📩 You will receive updates as it progresses.\n"
                                        f"💡 To check ticket status anytime, run:\n"
                                        f"`/agent-tickets`"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": "🚀 *Thank you! The Systems Team will review your issue shortly.*"
                                }
                            ]
                        }
                    ]
                }

                # Add image preview if a file was uploaded
                if file_url != "No file uploaded":
                    confirmation_view["blocks"].insert(3, {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Attached Image:*"
                        },
                        "accessory": {
                            "type": "image",
                            "image_url": file_url,
                            "alt_text": "Uploaded image"
                        }
                    })
                client.views_open(trigger_id=data["trigger_id"], view=confirmation_view)
                return jsonify({"response_action": "clear"})
            except Exception as e:
                logger.error(f"Error in new_ticket submission: {e}")
                return jsonify({"text": "❌ Ticket submission failed"}), 500

        # Handle assign-to-me action submission
        elif data.get("type") == "view_submission" and data["view"]["callback_id"] == "assign_to_me_action":
            metadata = json.loads(data["view"]["private_metadata"])
            ticket_id = metadata["ticket_id"]
            user_id = metadata["user_id"]
            message_ts = metadata["message_ts"]
            comment = data["view"]["state"]["values"]["comment"]["comment_input"]["value"] if "comment" in data["view"]["state"]["values"] else None

            # Update the ticket status and assignee
            update_ticket_status(ticket_id, "In Progress", assigned_to=user_id, message_ts=message_ts, comment=comment, action_user_id=user_id)

            # Fetch updated ticket details and comments
            conn = db_pool.getconn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
                updated_ticket = cur.fetchone()
                cur.execute("SELECT user_id, comment_text, created_at FROM comments WHERE ticket_id = %s ORDER BY created_at", (ticket_id,))
                comments = cur.fetchall()
                comments_str = "\n".join([f"<@{c[0]}>: {c[1]} ({c[2].strftime('%m/%d/%Y %H:%M:%S')})" for c in comments]) or "N/A"
            finally:
                db_pool.putconn(conn)

            # Update the channel message with comments and all buttons
            message_blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Details", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":white_check_mark: *Ticket ID:* T{ticket_id}\n\n"}},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":file_folder: *Campaign:* {updated_ticket[2]}\n\n"
                                f":pushpin: *Issue:* {updated_ticket[3]}\n\n"
                                f":zap: *Priority:* {updated_ticket[4]} {' :red_circle:' if updated_ticket[4] == 'High' else ' :large_yellow_circle:' if updated_ticket[4] == 'Medium' else ' :large_blue_circle:'}\n\n"
                                f":bust_in_silhouette: *Assigned To:* <@{updated_ticket[6]}>\n\n"
                                f":gear: *Status:* {updated_ticket[5]} {' :green_circle:' if updated_ticket[5] == 'Open' else ' :blue_circle:' if updated_ticket[5] == 'In Progress' else ' :large_yellow_circle:' if updated_ticket[5] == 'Resolved' else ' :red_circle:'}\n\n"
                    }
                },
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":writing_hand: *Details:* {updated_ticket[7]}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":link: *Salesforce Link:* {updated_ticket[8] or 'N/A'}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":file_folder: *File Attachment:* {updated_ticket[9]}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":calendar: *Created Date:* {updated_ticket[10].strftime('%m/%d/%Y')}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":speech_balloon: *Comments:* {comments_str}\n\n"}},
                {"type": "divider"},
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "🔁 Reassign", "emoji": True}, "action_id": f"reassign_{ticket_id}", "value": str(ticket_id), "style": "primary"},
                        {"type": "button", "text": {"type": "plain_text", "text": "❌ Close", "emoji": True}, "action_id": f"close_{ticket_id}", "value": str(ticket_id), "style": "danger"},
                        {"type": "button", "text": {"type": "plain_text", "text": "🟢 Resolve", "emoji": True}, "action_id": f"resolve_{ticket_id}", "value": str(ticket_id), "style": "primary"},
                        {"type": "button", "text": {"type": "plain_text", "text": "🔄 Reopen", "emoji": True}, "action_id": f"reopen_{ticket_id}", "value": str(ticket_id)}
                    ]
                }
            ]
            client.chat_update(channel=SLACK_CHANNEL_ID, ts=message_ts, blocks=message_blocks)
            return jsonify({"response_action": "clear"})

    except Exception as e:
        logger.error(f"Error handling Slack event: {e}")
        return jsonify({"text": "❌ An error occurred while processing the event."}), 500

# Scheduled Tasks (Optional)
scheduler = BackgroundScheduler(timezone=pytz.timezone(TIMEZONE))

def check_overdue_tickets():
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        seven_days_ago = datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=7)
        cur.execute("SELECT ticket_id, assigned_to FROM tickets WHERE status IN ('Open', 'In Progress') AND created_at < %s", (seven_days_ago,))
        overdue_tickets = cur.fetchall()
        for ticket_id, assignee_id in overdue_tickets:
            if assignee_id and assignee_id != 'Unassigned':
                client.chat_postMessage(channel=assignee_id, text=f"⏰ Reminder: Ticket T{ticket_id} is overdue. Please review.")
                logger.info(f"Overdue reminder sent for T{ticket_id}")
    except Exception as e:
        logger.error(f"Error in overdue tickets check: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Overdue tickets check failed: {e}")
    finally:
        db_pool.putconn(conn)

# Check for tickets that have been open for too long without updates
def check_stale_tickets():
    logger.info("Checking for stale tickets...")
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        # Find tickets that have been open for more than 3 days without updates
        three_days_ago = datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=3)
        cur.execute(
            "SELECT ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, updated_at "
            "FROM tickets "
            "WHERE status IN ('Open', 'In Progress') AND updated_at < %s",
            (three_days_ago,)
        )
        stale_tickets = cur.fetchall()

        if stale_tickets:
            # Create a message with all stale tickets
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "⚠️ Stale Tickets Alert", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "The following tickets have had no updates for 3+ days:"}}
            ]

            for ticket in stale_tickets:
                ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, updated_at = ticket
                days_stale = (datetime.now(pytz.timezone(TIMEZONE)) - updated_at).days

                blocks.append({"type": "divider"})
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*T{ticket_id}* | {priority} Priority | {status} | {days_stale} days without updates\n"
                                f">*Issue:* {issue_type}\n"
                                f">*Assigned to:* {f'<@{assigned_to}>' if assigned_to != 'Unassigned' else 'Unassigned'}\n"
                                f">*Campaign:* {campaign}"
                    },
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Ticket", "emoji": True},
                        "value": f"view_{ticket_id}",
                        "action_id": f"view_ticket_{ticket_id}"
                    }
                })

            # Send the stale tickets report to the admin channel
            client.chat_postMessage(channel=ADMIN_CHANNEL, blocks=blocks)
            logger.info(f"Stale tickets report sent with {len(stale_tickets)} tickets")
    except Exception as e:
        logger.error(f"Error in stale tickets check: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Stale tickets check failed: {e}")
    finally:
        db_pool.putconn(conn)

# Schedule all jobs
scheduler.add_job(check_overdue_tickets, "interval", hours=24)
scheduler.add_job(check_stale_tickets, "interval", hours=24, start_date=datetime.now() + timedelta(minutes=30))
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

if __name__ == "__main__":
    logger.info("Starting Flask server...")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))