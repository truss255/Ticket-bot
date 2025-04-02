import os
import time
import atexit
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Attempt to import the config module, fallback to environment variables if missing
try:
    from config import SLACK_BOT_TOKEN, DATABASE_URL, TIMEZONE, SYSTEM_ISSUES_CHANNEL
except ModuleNotFoundError:
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
    DATABASE_URL = os.getenv("DATABASE_URL")
    TIMEZONE = os.getenv("TIMEZONE", "UTC")
    SYSTEM_ISSUES_CHANNEL = os.getenv("SYSTEM_ISSUES_CHANNEL")
    if not SLACK_BOT_TOKEN or not DATABASE_URL:
        raise ImportError("The 'config' module is missing, and required environment variables are not set.")

from database import db_pool, init_db
from slack_client import client

# Define the modal building functions directly in app.py
def build_new_ticket_modal():
    """Construct the modal for submitting a new ticket with an optional file attachment and enhanced layout."""
    return {
        "type": "modal",
        "callback_id": "new_ticket",
        "title": {"type": "plain_text", "text": "Submit a New Ticket"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            # Introduction text
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Fill out details and upload an image (optional).*"}
            },
            {"type": "divider"},
            # Campaign selection
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
            # Issue type selection
            {
                "type": "input",
                "block_id": "issue_type_block",
                "label": {"type": "plain_text", "text": "📌 Issue Type"},
                "element": {
                    "type": "static_select",
                    "action_id": "issue_type_select",
                    "placeholder": {"type": "plain_text", "text": "Select an issue type"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Salesforce Issues (Freeze/Crash)"}, "value": "Salesforce Performance Issues"},
                        {"text": {"type": "plain_text", "text": "Vonage Dialer Issues"}, "value": "Vonage Dialer Functionality Issues"},
                        {"text": {"type": "plain_text", "text": "Broken Links"}, "value": "Broken or Unresponsive Links"},
                        {"text": {"type": "plain_text", "text": "Laptop Won't Power On"}, "value": "Laptop Fails to Power On"},
                        {"text": {"type": "plain_text", "text": "Slow/Freezing Laptop"}, "value": "Slow Performance or Freezing Laptop"},
                        {"text": {"type": "plain_text", "text": "Other"}, "value": "Other"}
                    ]
                },
                "optional": False
            },
            # Priority selection
            {
                "type": "input",
                "block_id": "priority_block",
                "label": {"type": "plain_text", "text": "⚡ Priority"},
                "element": {
                    "type": "static_select",
                    "action_id": "priority_select",
                    "placeholder": {"type": "plain_text", "text": "Select priority"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Low"}, "value": "Low"},
                        {"text": {"type": "plain_text", "text": "Medium"}, "value": "Medium"},
                        {"text": {"type": "plain_text", "text": "High"}, "value": "High"}
                    ]
                },
                "optional": False
            },
            {"type": "divider"},
            # Details field
            {
                "type": "input",
                "block_id": "details_block",
                "label": {"type": "plain_text", "text": "✏️ Details"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "details_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Describe the issue clearly"}
                },
                "optional": False
            },
            {"type": "divider"},
            # Salesforce link field
            {
                "type": "input",
                "block_id": "salesforce_link_block",
                "label": {"type": "plain_text", "text": "🔗 Salesforce Link"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "salesforce_link_input",
                    "placeholder": {"type": "plain_text", "text": "Paste Salesforce URL if applicable"}
                },
                "optional": True
            },
            # File attachment field with native file picker
            {
                "type": "input",
                "block_id": "file_upload_block",
                "optional": True,
                "label": {"type": "plain_text", "text": "🖼️ Attach Screenshot (optional)"},
                "element": {
                    "type": "file_input",
                    "action_id": "file_upload_action"
                }
            }
        ]
    }

def get_system_ticket_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url):
    """Returns the blocks for a ticket message in the #systems-issues channel."""
    # Create the main message blocks
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🎟 *New Ticket Created!* (T{ticket_id:03d})"
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"📂 *Campaign:* {campaign}"},
                {"type": "mrkdwn", "text": f"📌 *Issue:* {issue_type}"}
            ]
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"⚡ *Priority:* {'🔴 High' if priority == 'High' else '🟡 Medium' if priority == 'Medium' else '🔵 Low'}"},
                {"type": "mrkdwn", "text": f"👤 *Assigned To:* ❌ Unassigned"}
            ]
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"🔄 *Status:* 🟢 Open"},
                {"type": "mrkdwn", "text": f"👤 *Submitted By:* <@{user_id}>"}
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"✏️ *Details:* {details}"}
        }
    ]

    # Add Salesforce link if available
    if salesforce_link and salesforce_link != "N/A":
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"🔗 *Salesforce Link:* <{salesforce_link}|Click Here>"}
        })

    # Add file attachment if available
    if file_url and file_url != "No file uploaded":
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"📷 *File Attachment:* <{file_url}|View Screenshot>"}
        })

    # Add divider before actions
    blocks.append({"type": "divider"})

    # Add Assign to Me button
    blocks.append({
        "type": "actions",
        "block_id": f"ticket_actions_{ticket_id}",
        "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "🔘 Assign to Me", "emoji": True},
             "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"}
        ]
    })

    return blocks

def build_ticket_confirmation_modal(ticket_id, campaign, issue_type, priority):
    """Construct a confirmation modal view to display after a successful ticket submission."""
    # Determine the appropriate priority icon.
    priority_icon = '🔴 High' if priority == 'High' else '🟡 Medium' if priority == 'Medium' else '🔵 Low'

    return {
        "type": "modal",
        "callback_id": "ticket_confirmation",
        "title": {"type": "plain_text", "text": "Ticket Submitted"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "✅ *Ticket Submitted Successfully!*"}
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
                    {"type": "mrkdwn", "text": f"⚡ *Priority:* {priority_icon}"}
                ]
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "👀 The system team is now reviewing your ticket.\n"
                        "You will be notified when the status changes.\n"
                        "📊 You can check your tickets anytime using: `/agent-tickets`"
                    )
                }
            }
        ]
    }

from utils import send_dm, is_authorized_user, export_tickets
from scheduler import scheduler

load_dotenv()
app = Flask(__name__)
app.start_time = time.time()

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database
init_db()

# Routes
@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "ok",
        "message": "Ticket Bot is running",
        "endpoints": [
            "/api/tickets/slack/interactivity",
            "/api/tickets/system-tickets",
            "/api/tickets/ticket-summary",
            "/api/tickets/new-ticket"
        ]
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    from werkzeug.utils import secure_filename
    if 'picture' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['picture']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        file_url = f"{request.url_root}static/uploads/{filename}"
        return jsonify({"file_url": file_url}), 200

@app.route('/slack/events', methods=['POST'])
def slack_events():
    payload = request.json
    if payload.get("type") == "url_verification":
        return jsonify({"challenge": payload.get("challenge")})
    return jsonify({"ok": True})

@app.route('/api/tickets/new-ticket', methods=['POST'])
def new_ticket():
    """Handle the /new-ticket slash command from Slack."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Received /api/tickets/new-ticket request")
    try:
        logger.info(f"Request form data: {request.form}")
        logger.info(f"Request headers: {request.headers}")

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
        logger.error(f"Error in /api/tickets/new-ticket: {e}")
        return jsonify({"text": "❌ An error occurred. Please try again later."}), 200

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
        "uptime": time.time() - app.start_time,
        "database": db_status,
        "slack": slack_status
    })

@app.route('/api/tickets/slack/events', methods=['POST'])
def handle_events():
    data = request.json
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})
    return jsonify({"status": "ok"})

@app.route('/api/tickets/slack/interactivity', methods=['POST'])
def interactivity():
    """Handle interactive components from Slack."""
    import logging
    import json
    import time
    from datetime import datetime
    import pytz

    logger = logging.getLogger(__name__)
    logger.info("Received /api/tickets/slack/interactivity request")
    payload = request.form.get('payload')
    if not payload:
        logger.error("No payload provided")
        return jsonify({"error": "No payload provided"}), 400
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return jsonify({"error": "Invalid JSON payload"}), 400

    # Handle modal submissions (view_submission)
    if data.get("type") == "view_submission":
        callback_id = data.get("view", {}).get("callback_id")
        user_id = data.get("user", {}).get("id")
        if callback_id == "new_ticket":
            try:
                state = data["view"]["state"]["values"]
                campaign = state["campaign_block"]["campaign_select"]["selected_option"]["value"]
                issue_type = state["issue_type_block"]["issue_type_select"]["selected_option"]["value"]
                priority = state["priority_block"]["priority_select"]["selected_option"]["value"]
                details = state["details_block"]["details_input"]["value"]
                salesforce_link = state.get("salesforce_link_block", {}).get("salesforce_link_input", {}).get("value", "")

                # Handle file uploads
                file_url = "No file uploaded"
                if "file_upload_block" in state and "file_upload_action" in state["file_upload_block"]:
                    file_ids = state["file_upload_block"]["file_upload_action"].get("files", [])
                    if file_ids:
                        file_id = file_ids[0]
                        file_info = client.files_info(file=file_id)
                        if file_info.get("ok"):
                            file_url = file_info.get("file", {}).get("url_private", "No file uploaded")

                now = datetime.now(pytz.timezone(TIMEZONE))
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
                    logger.info(f"Ticket inserted with ID: {ticket_id}")
                finally:
                    db_pool.putconn(conn)

                # Build and post ticket notification using the system ticket message template
                message_blocks = get_system_ticket_blocks(
                    ticket_id=ticket_id,
                    campaign=campaign,
                    issue_type=issue_type,
                    priority=priority,
                    user_id=user_id,
                    details=details,
                    salesforce_link=salesforce_link,
                    file_url=file_url
                )
                text_fallback = f"New Ticket T{ticket_id:03d} - {issue_type} - {priority} Priority - Submitted by <@{user_id}>"
                try:
                    channel_response = client.chat_postMessage(
                        channel=SYSTEM_ISSUES_CHANNEL,
                        blocks=message_blocks,
                        text=text_fallback
                    )
                    logger.info(f"Ticket message posted to channel: {channel_response.get('ts')}")
                except Exception as post_err:
                    logger.error(f"Error posting ticket message: {post_err}")

                # Send DM confirmation to submitting user
                confirmation_blocks = build_ticket_confirmation_modal(
                    ticket_id=ticket_id,
                    campaign=campaign,
                    issue_type=issue_type,
                    priority=priority
                )["blocks"]
                send_dm(user_id, f":white_check_mark: Your ticket T{ticket_id:03d} has been submitted successfully!", confirmation_blocks)

                # Return a success view instead of clearing
                success_view = {
                    "type": "modal",
                    "title": {"type": "plain_text", "text": "Success", "emoji": True},
                    "close": {"type": "plain_text", "text": "Close", "emoji": True},
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f":white_check_mark: *Ticket T{ticket_id:03d} has been submitted successfully!*"}
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "Your ticket has been posted in the #systems-issues channel."}
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "You'll also receive a direct message with your ticket details."}
                        }
                    ]
                }
                return jsonify({"response_action": "update", "view": success_view})
            except Exception as e:
                logger.error(f"Error processing new ticket submission: {e}")
                return jsonify({"response_action": "clear"})

        return jsonify({"response_action": "clear"})

    # Handle block actions (button clicks)
    elif data.get("type") == "block_actions":
        actions = data.get("actions", [])
        if not actions:
            logger.error("No actions found in block_actions payload")
            return jsonify({"error": "No actions found"}), 400
        action = actions[0]
        action_id = action.get("action_id")
        user_id = data.get("user", {}).get("id")
        trigger_id = data.get("trigger_id")

        # Handle the image upload button click
        if action_id == "open_file_upload":
            try:
                # Get the user ID from the payload
                user_id = data.get("user", {}).get("id")
                view_id = data.get("view", {}).get("id")

                # Store the view_id in a global dictionary to track which modal the file is for
                if not hasattr(app, 'file_upload_tracking'):
                    app.file_upload_tracking = {}

                app.file_upload_tracking[user_id] = {
                    'view_id': view_id,
                    'timestamp': time.time()
                }

                logger.info(f"Stored view_id {view_id} for user {user_id} file upload")

                # Send a DM prompting the user to upload a file with clear instructions
                client.chat_postMessage(
                    channel=user_id,
                    blocks=[
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "📷 *Upload your screenshot or image here*"}
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "1. Click the + button below to upload your file\n2. After uploading, you'll receive a link\n3. Copy that link and paste it in the ticket form"}
                        },
                        {
                            "type": "context",
                            "elements": [
                                {"type": "mrkdwn", "text": "_This window will stay open while you complete your ticket._"}
                            ]
                        }
                    ]
                )
                logger.info(f"Sent file upload prompt to user {user_id}")
            except Exception as e:
                logger.error(f"Error handling file upload request: {e}")
            return "", 200

        return "", 200

    return jsonify({"status": "ok"}), 200

@app.route('/api/tickets/system-tickets', methods=['POST'])
def system_tickets():
    user_id = request.form.get('user_id')
    if not user_id or not is_authorized_user(user_id):
        return jsonify({"text": "❌ You are not authorized to view system tickets."}), 200
    trigger_id = request.form.get('trigger_id')
    modal = {
        "type": "modal",
        "title": {"type": "plain_text", "text": "System Tickets", "emoji": True},
        "close": {"type": "plain_text", "text": "Close", "emoji": True},
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "System Tickets", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Dynamic filtering coming soon."}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Export Tickets", "emoji": True},
                 "action_id": "export_tickets", "value": "export"}
            ]}
        ]
    }
    if trigger_id:
        client.views_open(trigger_id=trigger_id, view=modal)
        return "", 200
    return jsonify({"response_type": "ephemeral", "blocks": modal["blocks"]}), 200

@app.route('/api/tickets/ticket-summary', methods=['POST'])
def ticket_summary():
    user_id = request.form.get('user_id')
    if not user_id or not is_authorized_user(user_id):
        return jsonify({"text": "❌ You are not authorized to view ticket summary."}), 200
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tickets"); total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Open'"); open_t = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'In Progress'"); in_progress = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Resolved'"); resolved = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Closed'"); closed = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE priority = 'High'"); high = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM tickets WHERE assigned_to = 'Unassigned'"); unassigned = cur.fetchone()[0]
    finally:
        db_pool.putconn(conn)
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Ticket Summary"}},
        {"type": "section", "text": {"type": "mrkdwn",
                                      "text": f"*Total Tickets:* {total}\n*Open:* {open_t}\n*In Progress:* {in_progress}\n*Resolved:* {resolved}\n*Closed:* {closed}\n*High Priority:* {high}\n*Unassigned:* {unassigned}"}}
    ]
    return jsonify({"response_type": "ephemeral", "blocks": blocks}), 200

if __name__ == "__main__":
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))