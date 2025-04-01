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
import time
from check_db_route import add_db_check_route
from ticket_templates import get_ticket_submission_blocks, get_agent_confirmation_blocks, get_ticket_updated_blocks, build_export_filter_modal

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.start_time = time.time()  # Track application start time

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

# Check Slack API version
try:
    api_test = client.api_test()
    logger.info(f"Slack API Test: {api_test}")
    auth_test = client.auth_test()
    logger.info(f"Slack Auth Test: {auth_test}")
    logger.info(f"Connected as: {auth_test.get('user')} to workspace: {auth_test.get('team')}")
    available_methods = [method for method in dir(client) if not method.startswith('_')]
    logger.info(f"Available Slack client methods: {', '.join(available_methods[:20])}...")
    logger.info("Slack client initialized successfully.")
except Exception as e:
    logger.error(f"Error initializing Slack client: {e}")

# Set Slack channel ID or name
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "#systems-issues")
logger.info(f"Using Slack channel: {SLACK_CHANNEL_ID}")

# Add # prefix if it's a channel name and doesn't already have it
if not SLACK_CHANNEL_ID.startswith("C") and not SLACK_CHANNEL_ID.startswith("#"):
    SLACK_CHANNEL_ID = f"#{SLACK_CHANNEL_ID}"
    logger.info(f"Updated channel name to: {SLACK_CHANNEL_ID}")

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

# Add database check route
app = add_db_check_route(app, db_pool)

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
                {"type": "section", "text": {"type": "mrkdwn", "text": f":ticket: *Ticket Updated* | T{updated_ticket[0]:03d} | {updated_ticket[4]} Priority {':fire:' if updated_ticket[4] == 'High' else ':hourglass_flowing_sand:' if updated_ticket[4] == 'Medium' else ''}\n\n"}},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"📂 *Campaign:* {updated_ticket[2]}\n\n"
                                f"📌 *Issue:* {updated_ticket[3]}\n\n"
                                f"⚡ *Priority:* {updated_ticket[4]} {' 🔴' if updated_ticket[4] == 'High' else ' 🟡' if updated_ticket[4] == 'Medium' else ' 🔵'}\n\n"
                                f"👤 *Assigned To:* {f'<@{updated_ticket[6]}>' if updated_ticket[6] != 'Unassigned' else 'Unassigned'}\n\n"
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
                    "elements": []
                }
            ]

            if updated_ticket[5] == "Open" and updated_ticket[6] == "Unassigned":
                message_blocks[-1]["elements"].append(
                    {"type": "button", "text": {"type": "plain_text", "text": "🖐 Assign to Me", "emoji": True}, "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"}
                )
            elif updated_ticket[5] in ["Open", "In Progress"] and updated_ticket[6] != "Unassigned":
                message_blocks[-1]["elements"].extend([
                    {"type": "button", "text": {"type": "plain_text", "text": "🔁 Reassign", "emoji": True}, "action_id": f"reassign_{ticket_id}", "value": str(ticket_id), "style": "primary"},
                    {"type": "button", "text": {"type": "plain_text", "text": "❌ Close", "emoji": True}, "action_id": f"close_{ticket_id}", "value": str(ticket_id), "style": "danger"},
                    {"type": "button", "text": {"type": "plain_text", "text": "🟢 Resolve", "emoji": True}, "action_id": f"resolve_{ticket_id}", "value": str(ticket_id), "style": "primary"}
                ])
            elif updated_ticket[5] in ["Closed", "Resolved"]:
                message_blocks[-1]["elements"].append(
                    {"type": "button", "text": {"type": "plain_text", "text": "🔄 Reopen", "emoji": True}, "action_id": f"reopen_{ticket_id}", "value": str(ticket_id)}
                )

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
                "optional": True,
                "hint": {"type": "plain_text", "text": "Accepted formats: PNG, JPG, GIF. Max size: 10MB"}
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
            "/api/tickets/slack/events",
            "/api/tickets/slack/url-verification",
            "/api/tickets/slack/event-subscriptions",
            "/api/check-db",
            "/health"
        ],
        "version": "1.1.0",
        "last_updated": "2025-03-31"
    })

@app.route('/api/tickets/slack/event-subscriptions', methods=['POST'])
def slack_event_subscriptions():
    """Handle Slack event subscriptions"""
    logger.info("Received Slack event subscription")
    try:
        if not request.is_json:
            logger.warning("Request is not JSON")
            return jsonify({"error": "Expected JSON"}), 400

        data = request.json
        if data and data.get('type') == 'url_verification':
            challenge = data.get('challenge')
            logger.info(f"Returning challenge: {challenge}")
            return jsonify({"challenge": challenge})

        if data and 'event' in data:
            event = data.get('event', {})
            event_type = event.get('type')
            logger.info(f"Received event type: {event_type}")
            if event_type == 'message':
                channel = event.get('channel')
                user = event.get('user')
                text = event.get('text')
                logger.info(f"Message from {user} in {channel}: {text}")
            return jsonify({"status": "ok"})

        logger.warning(f"Unhandled event type: {data.get('type')}")
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Error in event subscription: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tickets/slack/url-verification', methods=['POST'])
def slack_url_verification():
    """Handle Slack URL verification challenges"""
    logger.info("Received Slack URL verification request")
    try:
        if request.is_json:
            data = request.json
            if data and data.get('type') == 'url_verification':
                challenge = data.get('challenge')
                logger.info(f"Returning challenge: {challenge}")
                return jsonify({"challenge": challenge})

        logger.warning("Invalid URL verification request")
        return jsonify({"error": "Invalid verification request"}), 400
    except Exception as e:
        logger.error(f"Error in URL verification: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    db_status = "ok"
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
    except Exception as e:
        db_status = f"error: {str(e)}"
    finally:
        if 'conn' in locals():
            db_pool.putconn(conn)

    slack_status = "ok"
    try:
        client.auth_test()
    except Exception as e:
        slack_status = f"error: {str(e)}"

    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "uptime": time.time() - app.start_time if hasattr(app, 'start_time') else 0,
        "database": db_status,
        "slack": slack_status
    })

def build_agent_tickets_modal(user_id, filter_status=None, start_date=None, end_date=None):
    """Build a modal for agent tickets with filtering options"""
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM tickets WHERE created_by = %s"
        params = [user_id]

        if filter_status and filter_status != "all":
            query += " AND status = %s"
            params.append(filter_status)

        if start_date:
            query += " AND created_at >= %s"
            params.append(start_date)

        if end_date:
            query += " AND created_at <= %s"
            params.append(end_date)

        query += " ORDER BY created_at DESC"
        cur.execute(query, params)
        tickets = cur.fetchall()
    finally:
        db_pool.putconn(conn)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🗂️ Your Tickets", "emoji": True}},
        {
            "type": "actions",
            "block_id": "agent_ticket_filters",
            "elements": [
                {
                    "type": "static_select",
                    "action_id": "agent_filter_status",
                    "placeholder": {"type": "plain_text", "text": "Filter by Status"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "All Statuses"}, "value": "all"},
                        {"text": {"type": "plain_text", "text": "🟢 Open"}, "value": "Open"},
                        {"text": {"type": "plain_text", "text": "🔵 In Progress"}, "value": "In Progress"},
                        {"text": {"type": "plain_text", "text": "🟡 Resolved"}, "value": "Resolved"},
                        {"text": {"type": "plain_text", "text": "🔴 Closed"}, "value": "Closed"}
                    ]
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📝 New Ticket", "emoji": True},
                    "action_id": "create_new_ticket",
                    "style": "primary"
                }
            ]
        },
        {
            "type": "actions",
            "block_id": "agent_date_filters",
            "elements": [
                {
                    "type": "datepicker",
                    "action_id": "agent_start_date",
                    "placeholder": {"type": "plain_text", "text": "Start Date", "emoji": True},
                    "initial_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d") if start_date is None else start_date.strftime("%Y-%m-%d") if isinstance(start_date, datetime) else start_date
                },
                {
                    "type": "datepicker",
                    "action_id": "agent_end_date",
                    "placeholder": {"type": "plain_text", "text": "End Date", "emoji": True},
                    "initial_date": datetime.now().strftime("%Y-%m-%d") if end_date is None else end_date.strftime("%Y-%m-%d") if isinstance(end_date, datetime) else end_date
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 Apply Filters", "emoji": True},
                    "action_id": "agent_apply_date_filter"
                }
            ]
        },
        {"type": "divider"}
    ]

    if not tickets:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "You haven't submitted any tickets yet."}
        })
    else:
        filter_text = []
        if filter_status and filter_status != "all":
            filter_text.append(f"Status: {filter_status}")
        if start_date:
            filter_text.append(f"From: {start_date.strftime('%m/%d/%Y')}")
        if end_date:
            filter_text.append(f"To: {end_date.strftime('%m/%d/%Y')}")

        if filter_text:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"*Filters applied:* {', '.join(filter_text)}"}]
            })
            blocks.append({"type": "divider"})

        for ticket in tickets:
            ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at = ticket
            status_emoji = "🟢" if status == "Open" else "🔵" if status == "In Progress" else "🟡" if status == "Resolved" else "🔴"
            priority_emoji = "🔴" if priority == "High" else "🟡" if priority == "Medium" else "🔵"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":ticket: *T{ticket_id:03d} - {status}* {status_emoji}"
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👀 View Progress", "emoji": True},
                    "value": str(ticket_id),
                    "action_id": f"view_ticket_progress_{ticket_id}"
                }
            })

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

            blocks.append({"type": "divider"})

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": "Click *View Progress* to see detailed ticket information and updates."}
        ]
    })

    return blocks

@app.route('/api/tickets/agent-tickets', methods=['POST'])
def agent_tickets():
    logger.info("Received /api/tickets/agent-tickets request")
    try:
        logger.info(f"Request form data: {request.form}")
        user_id = request.form.get('user_id')
        if not user_id:
            return jsonify({"text": "Error: Could not identify user."}), 200

        blocks = build_agent_tickets_modal(user_id)
        modal = {
            "type": "modal",
            "title": {"type": "plain_text", "text": "Your Tickets", "emoji": True},
            "close": {"type": "plain_text", "text": "Close", "emoji": True},
            "blocks": blocks
        }

        trigger_id = request.form.get('trigger_id')
        if trigger_id:
            try:
                client.views_open(trigger_id=trigger_id, view=modal)
                return "", 200
            except Exception as e:
                logger.error(f"Error opening modal: {e}")
                return jsonify({"text": "❌ An error occurred while displaying your tickets."}), 200
        else:
            return jsonify({"response_type": "ephemeral", "blocks": blocks}), 200
    except Exception as e:
        logger.error(f"Error in /api/tickets/agent-tickets: {e}")
        return jsonify({"text": "❌ An error occurred. Please try again later."}), 200

def build_system_tickets_modal(filter_status=None, filter_priority=None, filter_campaign=None, start_date=None, end_date=None):
    """Build a modal for system tickets with filtering options"""
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM tickets"
        params = []
        where_clauses = []

        if filter_status and filter_status != "all":
            where_clauses.append("status = %s")
            params.append(filter_status)

        if filter_priority and filter_priority != "all":
            where_clauses.append("priority = %s")
            params.append(filter_priority)

        if filter_campaign and filter_campaign != "all":
            where_clauses.append("campaign = %s")
            params.append(filter_campaign)

        if start_date:
            where_clauses.append("created_at >= %s")
            params.append(start_date)

        if end_date:
            where_clauses.append("created_at <= %s")
            params.append(end_date)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY created_at DESC"
        cur.execute(query, params)
        tickets = cur.fetchall()

        cur.execute("SELECT DISTINCT campaign FROM tickets ORDER BY campaign")
        campaigns = [row[0] for row in cur.fetchall()]
    finally:
        db_pool.putconn(conn)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "System Tickets", "emoji": True}},
        {
            "type": "actions",
            "block_id": "ticket_filters",
            "elements": [
                {
                    "type": "static_select",
                    "action_id": "filter_status",
                    "placeholder": {"type": "plain_text", "text": "Filter by Status"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "All Statuses"}, "value": "all"},
                        {"text": {"type": "plain_text", "text": "🟢 Open"}, "value": "Open"},
                        {"text": {"type": "plain_text", "text": "🔵 In Progress"}, "value": "In Progress"},
                        {"text": {"type": "plain_text", "text": "🟡 Resolved"}, "value": "Resolved"},
                        {"text": {"type": "plain_text", "text": "🔴 Closed"}, "value": "Closed"}
                    ]
                },
                {
                    "type": "static_select",
                    "action_id": "filter_priority",
                    "placeholder": {"type": "plain_text", "text": "Filter by Priority"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "All Priorities"}, "value": "all"},
                        {"text": {"type": "plain_text", "text": "🔴 High"}, "value": "High"},
                        {"text": {"type": "plain_text", "text": "🟡 Medium"}, "value": "Medium"},
                        {"text": {"type": "plain_text", "text": "🔵 Low"}, "value": "Low"}
                    ]
                },
                {
                    "type": "static_select",
                    "action_id": "filter_campaign",
                    "placeholder": {"type": "plain_text", "text": "Filter by Campaign"},
                    "options": [{"text": {"type": "plain_text", "text": "All Campaigns"}, "value": "all"}] +
                               [{"text": {"type": "plain_text", "text": campaign}, "value": campaign} for campaign in campaigns]
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📊 Export", "emoji": True},
                    "action_id": "export_tickets",
                    "style": "primary"
                }
            ]
        },
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": "system_date_filters",
            "elements": [
                {
                    "type": "datepicker",
                    "action_id": "system_start_date",
                    "placeholder": {"type": "plain_text", "text": "Start Date", "emoji": True},
                    "initial_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d") if start_date is None else start_date.strftime("%Y-%m-%d") if isinstance(start_date, datetime) else start_date
                },
                {
                    "type": "datepicker",
                    "action_id": "system_end_date",
                    "placeholder": {"type": "plain_text", "text": "End Date", "emoji": True},
                    "initial_date": datetime.now().strftime("%Y-%m-%d") if end_date is None else end_date.strftime("%Y-%m-%d") if isinstance(end_date, datetime) else end_date
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 Apply Date Filter", "emoji": True},
                    "action_id": "system_apply_date_filter"
                }
            ]
        },
        {"type": "divider"}
    ]

    if not tickets:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "No tickets found matching the selected filters."}
        })
    else:
        filter_text = []
        if filter_status and filter_status != "all":
            filter_text.append(f"Status: {filter_status}")
        if filter_priority and filter_priority != "all":
            filter_text.append(f"Priority: {filter_priority}")
        if filter_campaign and filter_campaign != "all":
            filter_text.append(f"Campaign: {filter_campaign}")
        if start_date:
            filter_text.append(f"From: {start_date.strftime('%m/%d/%Y')}")
        if end_date:
            filter_text.append(f"To: {end_date.strftime('%m/%d/%Y')}")

        if filter_text:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"*Filters applied:* {', '.join(filter_text)}"}]
            })
            blocks.append({"type": "divider"})

        for ticket in tickets:
            ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at = ticket
            status_emoji = "🟢" if status == "Open" else "🔵" if status == "In Progress" else "🟡" if status == "Resolved" else "🔴"
            priority_emoji = "🔴" if priority == "High" else "🟡" if priority == "Medium" else "🔵"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*T{ticket_id:03d}* - `{status}` {status_emoji}"
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👀 View Details", "emoji": True},
                    "value": str(ticket_id),
                    "action_id": f"view_system_ticket_{ticket_id}"
                }
            })

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

            action_elements = []
            if status == "Open" and assigned_to == "Unassigned":
                action_elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🖐 Assign to Me", "emoji": True},
                    "value": str(ticket_id),
                    "action_id": f"system_assign_to_me_{ticket_id}",
                    "style": "primary"
                })
            elif status in ["Open", "In Progress"] and assigned_to != "Unassigned":
                action_elements.extend([
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔁 Reassign", "emoji": True},
                        "value": str(ticket_id),
                        "action_id": f"system_reassign_{ticket_id}"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🟢 Resolve", "emoji": True},
                        "value": str(ticket_id),
                        "action_id": f"system_resolve_{ticket_id}",
                        "style": "primary"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Close", "emoji": True},
                        "value": str(ticket_id),
                        "action_id": f"system_close_{ticket_id}",
                        "style": "danger"
                    }
                ])
            elif status in ["Resolved", "Closed"]:
                action_elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 Reopen", "emoji": True},
                    "value": str(ticket_id),
                    "action_id": f"system_reopen_{ticket_id}"
                })

            if action_elements:
                blocks.append({"type": "actions", "elements": action_elements})

            blocks.append({"type": "divider"})

    return blocks

@app.route('/api/tickets/system-tickets', methods=['POST'])
def system_tickets():
    logger.info("Received /api/tickets/system-tickets request")
    try:
        logger.info(f"Request form data: {request.form}")
        user_id = request.form.get('user_id')
        if not user_id:
            return jsonify({"text": "Error: Could not identify user."}), 200

        if not is_system_user(user_id):
            logger.info(f"User {user_id} attempted to access system tickets but is not in SYSTEM_USERS list: {SYSTEM_USERS}")
            return jsonify({
                "response_type": "ephemeral",
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": "❌ You do not have permission to view system tickets."}},
                    {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Your user ID: `{user_id}`\nTo gain access, ask an administrator to add your ID to the SYSTEM_USERS environment variable."}]}
                ]
            }), 200

        blocks = build_system_tickets_modal()
        modal = {
            "type": "modal",
            "title": {"type": "plain_text", "text": "System Tickets", "emoji": True},
            "close": {"type": "plain_text", "text": "Close", "emoji": True},
            "blocks": blocks
        }

        trigger_id = request.form.get('trigger_id')
        if trigger_id:
            try:
                client.views_open(trigger_id=trigger_id, view=modal)
                return "", 200
            except Exception as e:
                logger.error(f"Error opening modal: {e}")
                return jsonify({"text": "❌ An error occurred while displaying system tickets."}), 200
        else:
            return jsonify({"response_type": "ephemeral", "blocks": blocks}), 200
    except Exception as e:
        logger.error(f"Error in /api/tickets/system-tickets: {e}")
        return jsonify({"text": "❌ An error occurred. Please try again later."}), 200

@app.route('/api/tickets/ticket-summary', methods=['POST'])
def ticket_summary():
    logger.info("Received /api/tickets/ticket-summary request")
    try:
        logger.info(f"Request form data: {request.form}")
        user_id = request.form.get('user_id')
        if not user_id:
            return jsonify({"text": "Error: Could not identify user."}), 200

        if not is_system_user(user_id):
            return jsonify({"text": "❌ You do not have permission to view ticket summary."}), 200

        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM tickets")
            total_tickets = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Open'")
            open_tickets = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'In Progress'")
            in_progress_tickets = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Resolved'")
            resolved_tickets = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Closed'")
            closed_tickets = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tickets WHERE priority = 'High'")
            high_priority = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tickets WHERE assigned_to = 'Unassigned'")
            unassigned = cur.fetchone()[0]
        finally:
            db_pool.putconn(conn)

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "Ticket Summary"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Total Tickets:* {total_tickets}\n"
                            f"*Open:* {open_tickets}\n"
                            f"*In Progress:* {in_progress_tickets}\n"
                            f"*Resolved:* {resolved_tickets}\n"
                            f"*Closed:* {closed_tickets}\n"
                            f"*High Priority:* {high_priority}\n"
                            f"*Unassigned:* {unassigned}\n"
                }
            }
        ]

        return jsonify({"response_type": "ephemeral", "blocks": blocks}), 200
    except Exception as e:
        logger.error(f"Error in /api/tickets/ticket-summary: {e}")
        return jsonify({"text": "❌ An error occurred. Please try again later."}), 200

@app.route('/api/tickets/new-ticket', methods=['POST'])
def slack_new_ticket_command():
    logger.info("Received /api/tickets/new-ticket request")
    try:
        logger.info(f"Request form data: {request.form}")
        logger.info(f"Request headers: {request.headers}")
        if request.form.get('command') != '/new-ticket':
            logger.warning(f"Unexpected command: {request.form.get('command')}")

        trigger_id = request.form.get('trigger_id')
        logger.info(f"Trigger ID: {trigger_id}")
        if not trigger_id:
            logger.error("No trigger_id found in the request")
            return jsonify({"text": "Error: Could not process your request. Please try again."}), 200

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
        logger.info(f"Request form data: {request.form}")
        logger.info(f"Request headers: {request.headers}")

        trigger_id = request.form.get('trigger_id')
        logger.info(f"Trigger ID: {trigger_id}")
        if not trigger_id:
            logger.error("No trigger_id found in the request")
            return jsonify({"error": "No trigger_id found"}), 400

        token_preview = SLACK_BOT_TOKEN[:10] + "..." if SLACK_BOT_TOKEN else "None"
        logger.info(f"Using Slack token: {token_preview}")

        modal = build_new_ticket_modal()
        logger.info("Built new ticket modal")

        response = requests.post(
            "https://slack.com/api/views.open",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            json={"trigger_id": trigger_id, "view": modal}
        )
        logger.info(f"Slack API response: {response.status_code} - {response.text}")
        return jsonify(response.json())
    except Exception as e:
        logger.error(f"Error in /new-ticket: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def export_tickets(status_filter, priority_filter, start_date, end_date, user_id):
    """Generate a CSV string of tickets based on filters and post to user."""
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        query = "SELECT ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at FROM tickets"
        params = []
        where_clauses = []

        if status_filter and status_filter != "all":
            where_clauses.append("status = %s")
            params.append(status_filter)
        if priority_filter and priority_filter != "all":
            where_clauses.append("priority = %s")
            params.append(priority_filter)
        if start_date:
            where_clauses.append("created_at >= %s")
            params.append(start_date)
        if end_date:
            where_clauses.append("created_at <= %s")
            params.append(end_date)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY created_at DESC"
        cur.execute(query, params)
        tickets = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Ticket ID", "Created By", "Campaign", "Issue Type", "Priority", "Status", "Assigned To", "Details", "Salesforce Link", "File URL", "Created At", "Updated At"])
        for ticket in tickets:
            writer.writerow(ticket)

        csv_content = output.getvalue()
        output.close()

        # Post CSV to user as a file
        response = client.files_upload(
            channels=user_id,
            content=csv_content,
            filename=f"tickets_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            title="Tickets Export"
        )
        logger.info(f"Exported tickets CSV to user {user_id}: {response.get('ts')}")
    finally:
        db_pool.putconn(conn)

@app.route('/api/tickets/slack/interactivity', methods=['POST'])
def handle_interactivity():
    logger.info("Received /api/tickets/slack/interactivity request")
    try:
        logger.info(f"Content-Type: {request.content_type}")
        logger.info(f"Form data keys: {list(request.form.keys())}")

        payload = request.form.get('payload')
        if not payload:
            logger.error("No payload found in request")
            return jsonify({"error": "No payload found"}), 400

        try:
            data = json.loads(payload)
            logger.info(f"Payload type: {data.get('type')}")
            payload_preview = json.dumps(data)[:500] + "..." if len(json.dumps(data)) > 500 else json.dumps(data)
            logger.info(f"Payload preview: {payload_preview}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse payload: {e}")
            return jsonify({"error": "Invalid JSON payload"}), 400

        interaction_type = data.get('type')
        if interaction_type == 'view_submission':
            logger.info("Processing view submission")
            view_id = data.get('view', {}).get('id')
            callback_id = data.get('view', {}).get('callback_id')
            user_id = data.get('user', {}).get('id')

            if callback_id == 'new_ticket':
                try:
                    # Extract form values
                    state_values = data.get('view', {}).get('state', {}).get('values', {})
                    logger.info(f"Form state values: {json.dumps(state_values)}")

                    # Get form values
                    campaign = state_values.get('campaign_block', {}).get('campaign_select', {}).get('selected_option', {}).get('value')
                    issue_type = state_values.get('issue_type_block', {}).get('issue_type_select', {}).get('selected_option', {}).get('value')
                    priority = state_values.get('priority_block', {}).get('priority_select', {}).get('selected_option', {}).get('value')
                    details = state_values.get('details_block', {}).get('details_input', {}).get('value')
                    salesforce_link = state_values.get('salesforce_link_block', {}).get('salesforce_link_input', {}).get('value', '')

                    # Get file URL if uploaded
                    file_url = "No file uploaded"
                    if 'file_upload_block' in state_values and 'file_upload_input' in state_values['file_upload_block']:
                        file_ids = state_values['file_upload_block']['file_upload_input'].get('files', [])
                        if file_ids:
                            file_id = file_ids[0]
                            file_info = client.files_info(file=file_id)
                            if file_info and file_info.get('ok'):
                                file_url = file_info.get('file', {}).get('url_private', 'No file uploaded')

                    # Insert ticket into database
                    now = datetime.now(pytz.timezone(TIMEZONE))
                    conn = db_pool.getconn()
                    try:
                        cur = conn.cursor()
                        logger.info(f"Inserting ticket with values: user_id={user_id}, campaign={campaign}, issue_type={issue_type}, priority={priority}")
                        cur.execute(
                            "INSERT INTO tickets (created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING ticket_id",
                            (user_id, campaign, issue_type, priority, "Open", "Unassigned", details, salesforce_link, file_url, now, now)
                        )
                        ticket_id = cur.fetchone()[0]
                        conn.commit()
                        logger.info(f"Ticket inserted successfully with ID: {ticket_id}")

                        # Use the template to create the ticket submission message blocks
                        logger.info(f"Creating ticket submission blocks using template for ticket ID: {ticket_id}")
                        message_blocks = get_ticket_submission_blocks(
                            ticket_id=ticket_id,
                            campaign=campaign,
                            issue_type=issue_type,
                            priority=priority,
                            user_id=user_id,
                            details=details,
                            salesforce_link=salesforce_link,
                            file_url=file_url
                        )

                        # Post ticket to main channel
                        logger.info(f"Posting ticket to channel: {SLACK_CHANNEL_ID}")
                        try:
                            text_fallback = f"New Ticket T{ticket_id:03d} - {issue_type} - {priority} Priority - Submitted by <@{user_id}>"
                            response = client.chat_postMessage(
                                channel=SLACK_CHANNEL_ID,
                                blocks=message_blocks,
                                text=text_fallback  # This is shown if blocks can't be displayed
                            )
                            logger.info(f"Message posted successfully: {response.get('ts')}")

                            # Send confirmation to the user
                            confirmation_blocks = get_agent_confirmation_blocks(
                                ticket_id=ticket_id,
                                campaign=campaign,
                                issue_type=issue_type,
                                priority=priority
                            )

                            # Send a direct message to the user
                            dm_response = client.chat_postMessage(
                                channel=user_id,  # Sending DM to user
                                text=f":white_check_mark: Your ticket T{ticket_id:03d} has been submitted successfully!",
                                blocks=confirmation_blocks
                            )
                            logger.info(f"Confirmation sent to user: {dm_response.get('ts')}")
                        except Exception as post_err:
                            logger.error(f"Error posting message: {post_err}")
                            # Try a simpler approach
                            try:
                                simple_text = f"New ticket submitted: T{ticket_id:03d} - {issue_type} - {priority} Priority"
                                client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=simple_text)
                                logger.info("Posted simple text message as fallback")
                            except Exception as simple_err:
                                logger.error(f"Error posting simple message: {simple_err}")
                    except Exception as db_err:
                        logger.error(f"Database error: {db_err}")
                        conn.rollback()
                        raise
                    finally:
                        db_pool.putconn(conn)

                    # Return success response
                    logger.info("Ticket submission completed successfully")
                    return jsonify({"response_action": "clear"})
                except Exception as e:
                    logger.error(f"Error processing ticket submission: {e}")
                    return jsonify({"response_action": "clear"})
            elif callback_id == 'assign_to_me_action':
                metadata = json.loads(data["view"]["private_metadata"])
                ticket_id = metadata["ticket_id"]
                user_id = metadata["user_id"]
                message_ts = metadata["message_ts"]
                comment = data["view"]["state"]["values"]["comment"]["comment_input"]["value"] if "comment" in data["view"]["state"]["values"] else None
                update_ticket_status(ticket_id, "In Progress", assigned_to=user_id, message_ts=message_ts, comment=comment, action_user_id=user_id)
                return jsonify({"response_action": "clear"})
            elif callback_id == 'reassign_action':
                metadata = json.loads(data["view"]["private_metadata"])
                ticket_id = metadata["ticket_id"]
                message_ts = metadata["message_ts"]
                new_assignee = data["view"]["state"]["values"]["assignee"]["assignee_select"]["selected_user"]
                comment = data["view"]["state"]["values"]["comment"]["comment_input"]["value"] if "comment" in data["view"]["state"]["values"] else None
                update_ticket_status(ticket_id, "In Progress", assigned_to=new_assignee, message_ts=message_ts, comment=comment, action_user_id=user_id)
                return jsonify({"response_action": "clear"})
            elif callback_id == 'export_tickets_action':
                state = data["view"]["state"]["values"]
                status_filter = state["status_filter"]["status_select"]["selected_option"]["value"] if state["status_filter"]["status_select"]["selected_option"] else "all"
                priority_filter = state["priority_filter"]["priority_select"]["selected_option"]["value"] if state["priority_filter"]["priority_select"]["selected_option"] else "all"
                start_date = datetime.strptime(state["start_date"]["start_date_select"]["selected_date"], "%Y-%m-%d").replace(hour=0, minute=0, second=0, tzinfo=pytz.timezone(TIMEZONE)) if "start_date_select" in state["start_date"] and state["start_date"]["start_date_select"]["selected_date"] else None
                end_date = datetime.strptime(state["end_date"]["end_date_select"]["selected_date"], "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=pytz.timezone(TIMEZONE)) if "end_date_select" in state["end_date"] and state["end_date"]["end_date_select"]["selected_date"] else None

                export_tickets(status_filter, priority_filter, start_date, end_date, user_id)
                return jsonify({
                    "response_action": "update",
                    "view": {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Export Complete", "emoji": True},
                        "close": {"type": "plain_text", "text": "Close", "emoji": True},
                        "blocks": [
                            {"type": "section", "text": {"type": "mrkdwn", "text": "✅ Tickets have been exported and sent to you as a CSV file."}}
                        ]
                    }
                })
            return jsonify({"response_action": "clear"})

        elif interaction_type == 'block_actions':
            logger.info("Processing block action")
            if 'actions' not in data or not data['actions']:
                logger.error("No actions found in block_actions payload")
                return jsonify({"error": "No actions found"}), 400

            action = data["actions"][0]
            action_id = action.get("action_id")
            user_id = data.get("user", {}).get("id")
            trigger_id = data.get("trigger_id")
            message_ts = data.get("message", {}).get("ts") if "message" in data else None
            logger.info(f"Action ID: {action_id}, User ID: {user_id}")

            if action_id == "agent_filter_status":
                view_id = data.get("view", {}).get("id")
                selected_value = action["selected_option"]["value"]
                updated_blocks = build_agent_tickets_modal(user_id, selected_value if selected_value != "all" else None)
                client.views_update(
                    view_id=view_id,
                    view={"type": "modal", "title": {"type": "plain_text", "text": "Your Tickets", "emoji": True}, "close": {"type": "plain_text", "text": "Close", "emoji": True}, "blocks": updated_blocks}
                )
                return "", 200

            elif action_id in ["agent_start_date", "agent_end_date"]:
                return "", 200

            elif action_id == "agent_apply_date_filter":
                view_id = data.get("view", {}).get("id")
                view_info = client.views_info(view_id=view_id) if hasattr(client, 'views_info') else {"view": data.get("view", {})}
                blocks = view_info["view"]["blocks"]
                date_block = next((b for b in blocks if b.get("block_id") == "agent_date_filters"), None)
                filter_block = next((b for b in blocks if b.get("block_id") == "agent_ticket_filters"), None)
                filter_status = None
                start_date = None
                end_date = None

                if date_block:
                    for element in date_block.get("elements", []):
                        if element.get("action_id") == "agent_start_date" and "selected_date" in element:
                            start_date_str = element["selected_date"]
                            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
                        if element.get("action_id") == "agent_end_date" and "selected_date" in element:
                            end_date_str = element["selected_date"]
                            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

                updated_blocks = build_agent_tickets_modal(user_id, filter_status, start_date, end_date)
                client.views_update(
                    view_id=view_id,
                    view={"type": "modal", "title": {"type": "plain_text", "text": "Your Tickets", "emoji": True}, "close": {"type": "plain_text", "text": "Close", "emoji": True}, "blocks": updated_blocks}
                )
                return "", 200

            elif action_id == "create_new_ticket":
                modal = build_new_ticket_modal()
                client.views_open(trigger_id=trigger_id, view=modal)
                return "", 200

            elif action_id in ["filter_status", "filter_priority", "filter_campaign"]:
                if not is_system_user(user_id):
                    return jsonify({"text": "❌ You do not have permission to filter tickets."}), 403
                view_id = data.get("view", {}).get("id")
                selected_value = action["selected_option"]["value"]
                view_info = client.views_info(view_id=view_id) if hasattr(client, 'views_info') else {"view": data.get("view", {})}
                blocks = view_info["view"]["blocks"]
                filter_block = next((b for b in blocks if b.get("block_id") == "ticket_filters"), None)

                filter_status = None
                filter_priority = None
                filter_campaign = None
                if filter_block:
                    if action_id == "filter_status":
                        filter_status = selected_value if selected_value != "all" else None
                    elif action_id == "filter_priority":
                        filter_priority = selected_value if selected_value != "all" else None
                    elif action_id == "filter_campaign":
                        filter_campaign = selected_value if selected_value != "all" else None

                updated_blocks = build_system_tickets_modal(filter_status, filter_priority, filter_campaign)
                client.views_update(
                    view_id=view_id,
                    view={"type": "modal", "title": {"type": "plain_text", "text": "System Tickets", "emoji": True}, "close": {"type": "plain_text", "text": "Close", "emoji": True}, "blocks": updated_blocks}
                )
                return "", 200

            elif action_id in ["system_start_date", "system_end_date"]:
                return "", 200

            elif action_id == "system_apply_date_filter":
                if not is_system_user(user_id):
                    return jsonify({"text": "❌ You do not have permission to filter tickets."}), 403
                view_id = data.get("view", {}).get("id")
                view_info = client.views_info(view_id=view_id) if hasattr(client, 'views_info') else {"view": data.get("view", {})}
                blocks = view_info["view"]["blocks"]
                filter_block = next((b for b in blocks if b.get("block_id") == "ticket_filters"), None)
                date_block = next((b for b in blocks if b.get("block_id") == "system_date_filters"), None)

                filter_status = None
                filter_priority = None
                filter_campaign = None
                start_date = None
                end_date = None
                if filter_block:
                    for element in filter_block.get("elements", []):
                        if element.get("action_id") == "filter_status" and "selected_option" in element:
                            filter_status = element["selected_option"]["value"] if element["selected_option"]["value"] != "all" else None
                        elif element.get("action_id") == "filter_priority" and "selected_option" in element:
                            filter_priority = element["selected_option"]["value"] if element["selected_option"]["value"] != "all" else None
                        elif element.get("action_id") == "filter_campaign" and "selected_option" in element:
                            filter_campaign = element["selected_option"]["value"] if element["selected_option"]["value"] != "all" else None
                if date_block:
                    for element in date_block.get("elements", []):
                        if element.get("action_id") == "system_start_date" and "selected_date" in element:
                            start_date_str = element["selected_date"]
                            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").replace(hour=0, minute=0, second=0)
                        if element.get("action_id") == "system_end_date" and "selected_date" in element:
                            end_date_str = element["selected_date"]
                            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

                updated_blocks = build_system_tickets_modal(filter_status, filter_priority, filter_campaign, start_date, end_date)
                client.views_update(
                    view_id=view_id,
                    view={"type": "modal", "title": {"type": "plain_text", "text": "System Tickets", "emoji": True}, "close": {"type": "plain_text", "text": "Close", "emoji": True}, "blocks": updated_blocks}
                )
                return "", 200

            elif action_id in ["export_tickets", "export_all_tickets"]:
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
                    conn = db_pool.getconn()
                    try:
                        cur = conn.cursor()
                        cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
                        ticket = cur.fetchone()
                        if not ticket:
                            return jsonify({"text": "Ticket not found"}), 200

                        cur.execute("SELECT user_id, comment_text, created_at FROM comments WHERE ticket_id = %s ORDER BY created_at", (ticket_id,))
                        comments = cur.fetchall()

                        ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at = ticket
                        status_emoji = "🟢" if status == "Open" else "🔵" if status == "In Progress" else "🟡" if status == "Resolved" else "🔴"
                        priority_emoji = "🔴" if priority == "High" else "🟡" if priority == "Medium" else "🔵"

                        updates = [f"1️⃣ *{created_at.strftime('%m/%d/%Y %I:%M %p')}:* Ticket submitted by <@{created_by}>"]
                        for i, (comment_user, comment_text, comment_date) in enumerate(comments, 2):
                            updates.append(f"{i}️⃣ *{comment_date.strftime('%m/%d/%Y %I:%M %p')}:* {comment_text} - <@{comment_user}>")
                        if not comments and status != "Open":
                            updates.append(f"2️⃣ *{updated_at.strftime('%m/%d/%Y %I:%M %p')}:* Status changed to {status}")

                        blocks = [
                            {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Progress", "emoji": True}},
                            {"type": "divider"},
                            {"type": "section", "text": {"type": "mrkdwn", "text": f"*T{ticket_id:03d}* - `{status}` {status_emoji}"}},
                            {"type": "context", "elements": [
                                {"type": "mrkdwn", "text": f":file_folder: *Campaign:* {campaign}"},
                                {"type": "mrkdwn", "text": f":pushpin: *Issue:* {issue_type}"}
                            ]},
                            {"type": "context", "elements": [
                                {"type": "mrkdwn", "text": f":zap: *Priority:* {priority} {priority_emoji}"},
                                {"type": "mrkdwn", "text": f":bust_in_silhouette: *Assigned To:* {f'@{assigned_to}' if assigned_to != 'Unassigned' else ':x: Unassigned'}"},
                                {"type": "mrkdwn", "text": f":calendar: *Created:* {created_at.strftime('%m/%d/%Y')}"}
                            ]},
                            {"type": "divider"},
                            {"type": "header", "text": {"type": "plain_text", "text": "🔧 Recent Updates", "emoji": True}}
                        ]

                        for update in updates:
                            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": update}]})

                        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ":bell: *You will receive updates when the status changes.*"}]})
                        modal = {"type": "modal", "title": {"type": "plain_text", "text": "Ticket Progress"}, "close": {"type": "plain_text", "text": "Close"}, "blocks": blocks}
                        client.views_open(trigger_id=trigger_id, view=modal)
                    finally:
                        db_pool.putconn(conn)
                    return "", 200

        return jsonify({"status": "success"})
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error in /slack/interactivity: {e}\n{error_details}")
        return jsonify({"status": "ok", "error": str(e)}), 200

@app.route('/api/tickets/slack/events', methods=['POST'])
def handle_slack_events():
    logger.info("Received Slack event")
    try:
        logger.info(f"Content-Type: {request.content_type}")
        logger.info(f"Headers: {dict(request.headers)}")

        if request.is_json and request.json and request.json.get('type') == 'url_verification':
            challenge = request.json.get('challenge')
            logger.info(f"Received URL verification challenge: {challenge}")
            return jsonify({"challenge": challenge})

        if request.is_json and request.json and 'event' in request.json:
            event = request.json.get('event', {})
            event_type = event.get('type')
            logger.info(f"Received Slack event type: {event_type}")
            if event_type == 'message':
                logger.info(f"Message event in channel: {event.get('channel')}")
            return jsonify({"status": "ok"})

        payload = request.form.get('payload')
        if payload:
            logger.info("Processing form payload")
            data = json.loads(payload)
        else:
            try:
                raw_data = request.get_data(as_text=True)
                logger.info(f"Raw data: {raw_data[:200]}...")
                if raw_data and raw_data.startswith('{'):
                    data = json.loads(raw_data)
                else:
                    logger.warning("No valid payload found in request")
                    return jsonify({"status": "ok"}), 200
            except Exception as e:
                logger.error(f"Error parsing request data: {e}")
                return jsonify({"status": "ok"}), 200

        if data.get("type") == "view_submission":
            callback_id = data.get("view", {}).get("callback_id")
            logger.info(f"Processing view submission with callback_id: {callback_id}")
            logger.info(f"Full view submission payload: {json.dumps(data)[:500]}...")

            if callback_id == "new_ticket":
                try:
                    state = data["view"]["state"]["values"]
                    campaign = state["campaign_block"]["campaign_select"]["selected_option"]["value"]
                    issue_type = state["issue_type_block"]["issue_type_select"]["selected_option"]["value"]
                    priority = state["priority_block"]["priority_select"]["selected_option"]["value"]
                    details = state["details_block"]["details_input"]["value"]
                    salesforce_link = state.get("salesforce_link_block", {}).get("salesforce_link_input", {}).get("value", "N/A")
                    user_id = data["user"]["id"]

                    file_url = "No file uploaded"
                    if "file_upload_block" in state and "file_upload_input" in state["file_upload_block"]:
                        file_info = state["file_upload_block"]["file_upload_input"]
                        if file_info and "files" in file_info and len(file_info["files"]) > 0:
                            file_id = file_info["files"][0]["id"]
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
                        logger.info(f"Ticket data: user_id={user_id}, campaign={campaign}, issue_type={issue_type}, priority={priority}")
                        cur.execute(
                            "INSERT INTO tickets (created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING ticket_id",
                            (user_id, campaign, issue_type, priority, "Open", "Unassigned", details, salesforce_link, file_url, now, now)
                        )
                        ticket_id = cur.fetchone()[0]
                        conn.commit()
                        logger.info(f"Ticket inserted successfully with ID: {ticket_id}")
                    finally:
                        db_pool.putconn(conn)

                    message_blocks = get_ticket_submission_blocks(
                        ticket_id=ticket_id,
                        campaign=campaign,
                        issue_type=issue_type,
                        priority=priority,
                        user_id=user_id,
                        details=details,
                        salesforce_link=salesforce_link,
                        file_url=file_url
                    )
                    response = client.chat_postMessage(
                        channel=SLACK_CHANNEL_ID,
                        blocks=message_blocks,
                        text=f"New Ticket T{ticket_id:03d} - {issue_type} - {priority} Priority - Submitted by <@{user_id}>"
                    )
                    logger.info(f"Message posted successfully to {SLACK_CHANNEL_ID}: {response.get('ts')}")

                    admin_notification = f":ticket: *New Ticket Alert* | T{ticket_id} | {priority} Priority\n" \
                                        f">*Issue:* {issue_type}\n" \
                                        f">*Submitted by:* <@{user_id}>\n" \
                                        f">*Campaign:* {campaign}"
                    client.chat_postMessage(channel=ADMIN_CHANNEL, text=admin_notification)

                    confirmation_view = {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Ticket Submitted"},
                        "close": {"type": "plain_text", "text": "Close"},
                        "blocks": [
                            {"type": "header", "text": {"type": "plain_text", "text": "🎉 Ticket Submitted Successfully!", "emoji": True}},
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"✅ *Ticket ID:* T{ticket_id:03d}\n"
                                            f"📂 *Campaign:* {campaign}\n"
                                            f"📌 *Issue Type:* {issue_type}\n"
                                            f"⚡ *Priority:* {priority} {' 🔴' if priority == 'High' else ' 🟡' if priority == 'Medium' else ' 🔵'}\n"
                                            f"👤 *Assigned To:* ❌ Unassigned\n"
                                            f"🔄 *Status:* Open 🟢\n"
                                            f"📅 *Created On:* {now.strftime('%m/%d/%Y')}"
                                }
                            },
                            {"type": "divider"}
                        ]
                    }
                    if file_url != "No file uploaded":
                        confirmation_view["blocks"].append({
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "*Attached Image:*"},
                            "accessory": {"type": "image", "image_url": file_url, "alt_text": "Uploaded image"}
                        })
                    confirmation_view["blocks"].extend([
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"🔔 Your ticket has been posted in <#{SLACK_CHANNEL_ID}>.\n"
                                        f"📩 You will receive updates as it progresses.\n"
                                        f"💡 To check ticket status anytime, run:\n"
                                        f"/agent-tickets"
                            }
                        },
                        {"type": "context", "elements": [{"type": "mrkdwn", "text": "🚀 *Thank you! The Systems Team will review your issue shortly.*"}]}
                    ])

                    return jsonify({"response_action": "update", "view": confirmation_view})
                except Exception as e:
                    logger.error(f"Error in new_ticket submission: {e}")
                    return jsonify({"text": "❌ Ticket submission failed"}), 500

            elif callback_id == "assign_to_me_action":
                metadata = json.loads(data["view"]["private_metadata"])
                ticket_id = metadata["ticket_id"]
                user_id = metadata["user_id"]
                message_ts = metadata["message_ts"]
                comment = data["view"]["state"]["values"]["comment"]["comment_input"]["value"] if "comment" in data["view"]["state"]["values"] else None
                update_ticket_status(ticket_id, "In Progress", assigned_to=user_id, message_ts=message_ts, comment=comment, action_user_id=user_id)
                return jsonify({"response_action": "clear"})

            elif callback_id == "reassign_action":
                metadata = json.loads(data["view"]["private_metadata"])
                ticket_id = metadata["ticket_id"]
                message_ts = metadata["message_ts"]
                new_assignee = data["view"]["state"]["values"]["assignee"]["assignee_select"]["selected_user"]
                comment = data["view"]["state"]["values"]["comment"]["comment_input"]["value"] if "comment" in data["view"]["state"]["values"] else None
                update_ticket_status(ticket_id, "In Progress", assigned_to=new_assignee, message_ts=message_ts, comment=comment, action_user_id=data["user"]["id"])
                return jsonify({"response_action": "clear"})

            elif callback_id == "export_tickets_action":
                state = data["view"]["state"]["values"]
                status_filter = state["status_filter"]["status_select"]["selected_option"]["value"] if state["status_filter"]["status_select"]["selected_option"] else "all"
                priority_filter = state["priority_filter"]["priority_select"]["selected_option"]["value"] if state["priority_filter"]["priority_select"]["selected_option"] else "all"
                start_date = datetime.strptime(state["start_date"]["start_date_select"]["selected_date"], "%Y-%m-%d").replace(hour=0, minute=0, second=0, tzinfo=pytz.timezone(TIMEZONE)) if "start_date_select" in state["start_date"] and state["start_date"]["start_date_select"]["selected_date"] else None
                end_date = datetime.strptime(state["end_date"]["end_date_select"]["selected_date"], "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=pytz.timezone(TIMEZONE)) if "end_date_select" in state["end_date"] and state["end_date"]["end_date_select"]["selected_date"] else None

                export_tickets(status_filter, priority_filter, start_date, end_date, data["user"]["id"])
                return jsonify({
                    "response_action": "update",
                    "view": {
                        "type": "modal",
                        "title": {"type": "plain_text", "text": "Export Complete", "emoji": True},
                        "close": {"type": "plain_text", "text": "Close", "emoji": True},
                        "blocks": [
                            {"type": "section", "text": {"type": "mrkdwn", "text": "✅ Tickets have been exported and sent to you as a CSV file."}}
                        ]
                    }
                })

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error handling Slack event: {e}\n{error_details}")
        return jsonify({"status": "ok", "error": str(e)}), 200

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

def check_stale_tickets():
    logger.info("Checking for stale tickets...")
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        three_days_ago = datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=3)
        cur.execute(
            "SELECT ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, updated_at "
            "FROM tickets WHERE status IN ('Open', 'In Progress') AND updated_at < %s",
            (three_days_ago,)
        )
        stale_tickets = cur.fetchall()

        if stale_tickets:
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
                        "text": f"*T{ticket_id:03d}* | {priority} Priority | {status} | {days_stale} days without updates\n"
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
            client.chat_postMessage(channel=ADMIN_CHANNEL, blocks=blocks)
            logger.info(f"Stale tickets report sent with {len(stale_tickets)} tickets")
    except Exception as e:
        logger.error(f"Error in stale tickets check: {e}")
        client.chat_postMessage(channel=ADMIN_CHANNEL, text=f"⚠️ Stale tickets check failed: {e}")
    finally:
        db_pool.putconn(conn)

if __name__ == "__main__":
    # Only start the scheduler when running directly (not via Gunicorn)
    scheduler.add_job(check_overdue_tickets, "interval", hours=24)
    scheduler.add_job(check_stale_tickets, "interval", hours=24, start_date=datetime.now() + timedelta(minutes=30))
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    logger.info("Starting Flask server with scheduler...")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
else:
    # When run via Gunicorn, just log that the web server is starting
    logger.info("Starting Flask server via Gunicorn (scheduler not started here)...")