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
from ticket_templates import get_ticket_submission_blocks, get_agent_confirmation_blocks, get_ticket_updated_blocks

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

    # Check auth
    auth_test = client.auth_test()
    logger.info(f"Slack Auth Test: {auth_test}")
    logger.info(f"Connected as: {auth_test.get('user')} to workspace: {auth_test.get('team')}")

    # Log available methods
    available_methods = [method for method in dir(client) if not method.startswith('_')]
    logger.info(f"Available Slack client methods: {', '.join(available_methods[:20])}...")

    logger.info("Slack client initialized successfully.")
except Exception as e:
    logger.error(f"Error initializing Slack client: {e}")

# Set Slack channel ID or name
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "systems-issues")

# Add # prefix if it's a channel name and doesn't already have it
if not SLACK_CHANNEL_ID.startswith("C") and not SLACK_CHANNEL_ID.startswith("#"):
    SLACK_CHANNEL_ID = f"#{SLACK_CHANNEL_ID}"

logger.info(f"Using Slack channel: {SLACK_CHANNEL_ID}")

# Skip channel verification to avoid sending test messages
logger.info(f"Skipping channel verification for {SLACK_CHANNEL_ID}")

# Just log a message instead of trying to verify channel access
logger.info("Channel access will be verified when first message is sent")

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
                                f"👤 *Assigned To:* <@{updated_ticket[6]}>\n\n"
                                f"🔄 *Status:* `{updated_ticket[5]}` {'🟢' if updated_ticket[5] == "Open" else '🔵' if updated_ticket[5] == 'In Progress' else '🟡' if updated_ticket[5] == 'Resolved' else '🔴'}\n\n"
                    }
                },
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"✏️ *Details:* {updated_ticket[7]}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":link: *Salesforce Link:* {updated_ticket[8] or 'N/A'}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":camera: *Screenshot/Image:* {f'<{updated_ticket[9]}|View Image>' if updated_ticket[9] != 'No file uploaded' else 'No image uploaded'}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"📅 *Created:* {updated_ticket[10].strftime('%m/%d/%Y %I:%M %p')} ({updated_ticket[10].strftime('%A')})\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"💬 *Comments:* {comments_str}\n\n"}},
                {"type": "divider"},
                {"type": "actions", "elements": []}
            ]

            # Dynamic button logic based on ticket state
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

@app.route('/api/tickets/slack/events', methods=['POST'])
def handle_slack_events():
    logger.info("Received Slack event")
    try:
        # Log request details for debugging
        logger.info(f"Content-Type: {request.content_type}")
        logger.info(f"Headers: {dict(request.headers)}")

        # Check if this is a URL verification challenge (application/json)
        if request.is_json and request.json and request.json.get('type') == 'url_verification':
            challenge = request.json.get('challenge')
            logger.info(f"Received URL verification challenge: {challenge}")
            return jsonify({"challenge": challenge})

        # For event subscriptions (application/json)
        if request.is_json and request.json and 'event' in request.json:
            event = request.json.get('event', {})
            event_type = event.get('type')
            logger.info(f"Received Slack event type: {event_type}")

            # Handle different event types here
            if event_type == 'message':
                # Process message events
                logger.info(f"Message event in channel: {event.get('channel')}")

            # Return a 200 OK for all events to acknowledge receipt
            return jsonify({"status": "ok"})

        # Handle payload from interactive components (application/x-www-form-urlencoded)
        payload = request.form.get('payload')
        if payload:
            logger.info("Processing form payload")
            data = json.loads(payload)
        else:
            # Try to get raw data if not in form or json
            try:
                raw_data = request.get_data(as_text=True)
                logger.info(f"Raw data: {raw_data[:200]}...") # Log first 200 chars
                if raw_data and raw_data.startswith('{'):
                    data = json.loads(raw_data)
                else:
                    logger.warning("No valid payload found in request")
                    return jsonify({"status": "ok"}), 200
            except Exception as e:
                logger.error(f"Error parsing request data: {e}")
                return jsonify({"status": "ok"}), 200

        # Handle ticket submission
        if data.get("type") == "view_submission":
            callback_id = data.get("view", {}).get("callback_id")
            logger.info(f"Processing view submission with callback_id: {callback_id}")
            logger.info(f"Full view submission payload: {json.dumps(data)[:500]}...")

            # Add more detailed logging
            try:
                # Log the state values
                state_values = data.get("view", {}).get("state", {}).get("values", {})
                logger.info(f"State values: {json.dumps(state_values)}")

                # Log user info
                user_info = data.get("user", {})
                logger.info(f"User info: {json.dumps(user_info)}")
            except Exception as log_err:
                logger.error(f"Error logging details: {log_err}")

            if callback_id == "new_ticket":
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

                    logger.info("Inserting ticket into database")
                    conn = db_pool.getconn()
                    try:
                        cur = conn.cursor()
                        now = datetime.now(pytz.timezone(TIMEZONE))
                        logger.info(f"Ticket data: user_id={user_id}, campaign={campaign}, issue_type={issue_type}, priority={priority}")

                        # Check if the tickets table exists
                        cur.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'tickets')")
                        table_exists = cur.fetchone()[0]
                        if not table_exists:
                            logger.error("Tickets table does not exist in the database!")
                            # Create the table if it doesn't exist
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
                            """)
                            conn.commit()
                            logger.info("Created tickets table")

                        # Insert the ticket
                        logger.info(f"Inserting ticket with values: user_id={user_id}, campaign={campaign}, issue_type={issue_type}, priority={priority}")
                        try:
                            cur.execute(
                                "INSERT INTO tickets (created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at) "
                                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING ticket_id",
                                (user_id, campaign, issue_type, priority, "Open", "Unassigned", details, salesforce_link, file_url, now, now)
                            )
                            ticket_id = cur.fetchone()[0]
                            conn.commit()
                            logger.info(f"Ticket inserted successfully with ID: {ticket_id}")
                        except Exception as insert_err:
                            logger.error(f"Error inserting ticket: {insert_err}")
                            # Try to get more details about the error
                            logger.error(f"Error details: {str(insert_err.__class__.__name__)}: {str(insert_err)}")
                            raise
                    except Exception as db_err:
                        logger.error(f"Database error: {db_err}")
                        raise
                    finally:
                        db_pool.putconn(conn)

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
                    logger.info(f"Message blocks: {json.dumps(message_blocks[:2])}...")
                    # Try different approaches for posting to the channel
                    logger.info(f"Attempting to post to channel {SLACK_CHANNEL_ID} using different methods")

                    # Try to find the channel first
                    try:
                        # Try to find the channel by name or ID
                        if SLACK_CHANNEL_ID.startswith('#'):
                            # It's a channel name, try to find the ID
                            channel_name = SLACK_CHANNEL_ID[1:]  # Remove the # prefix
                            logger.info(f"Looking up channel ID for name: {channel_name}")

                            # List all public channels
                            channels_response = client.conversations_list(types="public_channel")

                            channel_id = None
                            for channel in channels_response["channels"]:
                                if channel["name"] == channel_name:
                                    channel_id = channel["id"]
                                    logger.info(f"Found channel ID: {channel_id} for name: {channel_name}")
                                    break

                            if channel_id:
                                # Use the channel ID for posting
                                post_channel = channel_id
                            else:
                                # Fall back to the original channel name
                                logger.warning(f"Could not find channel ID for {channel_name}, using channel name")
                                post_channel = SLACK_CHANNEL_ID
                        else:
                            # It's already a channel ID
                            post_channel = SLACK_CHANNEL_ID

                        # Now post the message
                        text_fallback = f"New Ticket T{ticket_id:03d} - {issue_type} - {priority} Priority - Submitted by <@{user_id}>"
                        response = client.chat_postMessage(
                            channel=post_channel,
                            blocks=message_blocks,
                            text=text_fallback  # This is shown if blocks can't be displayed
                        )
                        logger.info(f"Message posted successfully to {post_channel}: {response.get('ts')}")
                    except Exception as channel_err:
                        logger.error(f"Error posting to channel {SLACK_CHANNEL_ID}: {channel_err}")

                        # Try a simpler approach with just text
                        try:
                            text_only = f"*New Ticket Alert* | T{ticket_id:03d} | {priority} Priority\n" + \
                                       f"*Campaign:* {campaign}\n" + \
                                       f"*Issue:* {issue_type}\n" + \
                                       f"*Created by:* <@{user_id}>\n" + \
                                       f"*Status:* Open\n" + \
                                       f"*Details:* {details[:100]}..."

                            # Try posting to #general as a fallback
                            general_channel = "#general"
                            response = client.chat_postMessage(
                                channel=general_channel,
                                text=text_only,
                                mrkdwn=True
                            )
                            logger.info(f"Fallback message posted to {general_channel}: {response.get('ts')}")
                        except Exception as fallback_err:
                            logger.error(f"All posting methods failed. Last error: {fallback_err}")

                    # Send notification to admin channel
                    admin_notification = f":ticket: *New Ticket Alert* | T{ticket_id} | {priority} Priority\n" + \
                                        f">*Issue:* {issue_type}\n" + \
                                        f">*Submitted by:* <@{user_id}>\n" + \
                                        f">*Campaign:* {campaign}"
                    try:
                        client.chat_postMessage(channel=ADMIN_CHANNEL, text=admin_notification)
                    except Exception as admin_err:
                        logger.error(f"Error sending admin notification: {admin_err}")

                    # Show confirmation modal instead of DM
                    confirmation_view = {
                        "type": "modal",
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
                                    "text": f"✅ *Ticket ID:* T{ticket_id:03d}\n"
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
                                            f"/agent-tickets"
                                }
                            },
                            {
                                "type": "context",
                                "elements": [
                                    {"type": "mrkdwn", "text": "🚀 *Thank you! The Systems Team will review your issue shortly.*"}
                                ]
                            }
                        ]
                    }

                    # Add image preview if uploaded
                    if file_url != "No file uploaded":
                        confirmation_view["blocks"].insert(3, {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "*Attached Image:*"},
                            "accessory": {
                                "type": "image",
                                "image_url": file_url,
                                "alt_text": "Uploaded image"
                            }
                        })

                    # Return response_action to update the modal with confirmation
                    return jsonify({
                        "response_action": "update",
                        "view": confirmation_view
                    })

                except Exception as e:
                    logger.error(f"Error in new_ticket submission: {e}")
                    return jsonify({"text": "❌ Ticket submission failed"}), 500

    except Exception as e:
        # Log the full error with traceback
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error handling Slack event: {e}\n{error_details}")

        # Log additional details about the request
        try:
            logger.error(f"Request method: {request.method}")
            logger.error(f"Request headers: {dict(request.headers)}")
            logger.error(f"Request form data: {request.form}")
            logger.error(f"Request JSON data: {request.get_json(silent=True)}")
        except Exception as log_err:
            logger.error(f"Error logging request details: {log_err}")

        # Return a 200 OK even for errors to prevent Slack from retrying
        # This is important because Slack expects a 200 response within 3 seconds
        return jsonify({"status": "ok", "error": str(e)}), 200

    # Default response if no conditions are met
    return jsonify({"status": "ok"}), 200

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