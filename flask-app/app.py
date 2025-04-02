import os
import json
import logging
import time
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
from dotenv import load_dotenv
import requests

# Import your ticket template functions or define them inline if the module can't be found
try:
    from ticket_templates import (
        get_ticket_submission_blocks,
        get_agent_confirmation_blocks,
        build_export_filter_modal
    )
    from new_modal import build_new_ticket_modal
    from system_ticket_message import (
        get_system_ticket_blocks,
        get_ticket_updated_blocks,
        get_ticket_detail_blocks
    )
    print("Successfully imported all template modules")
except ImportError:
    print("Could not import template modules, defining functions inline")

    # Define fallback function for get_system_ticket_blocks
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

    # Define the functions inline if the module can't be found
    def get_ticket_submission_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url):
        """Returns the blocks for a ticket submission message in the #systems-issues channel"""
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
                    "text": f"🎟 *Ticket Updated!* (T{ticket_id:03d})"
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

    def build_export_filter_modal():
        """Build a modal for exporting tickets with filters."""
        from datetime import datetime, timedelta
        import pytz

        TIMEZONE = "America/New_York"  # Match with app.py

        now = datetime.now(pytz.timezone(TIMEZONE))
        thirty_days_ago = now - timedelta(days=30)

        return {
            "type": "modal",
            "callback_id": "export_tickets_action",
            "title": {"type": "plain_text", "text": "Export Tickets", "emoji": True},
            "submit": {"type": "plain_text", "text": "Export", "emoji": True},
            "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*Select filters for ticket export:*"}
                },
                {
                    "type": "input",
                    "block_id": "status_filter",
                    "element": {
                        "type": "static_select",
                        "action_id": "status_select",
                        "placeholder": {"type": "plain_text", "text": "Filter by Status"},
                        "options": [
                            {"text": {"type": "plain_text", "text": "All Statuses"}, "value": "all"},
                            {"text": {"type": "plain_text", "text": "🟢 Open"}, "value": "Open"},
                            {"text": {"type": "plain_text", "text": "🔵 In Progress"}, "value": "In Progress"},
                            {"text": {"type": "plain_text", "text": "🟡 Resolved"}, "value": "Resolved"},
                            {"text": {"type": "plain_text", "text": "🔴 Closed"}, "value": "Closed"}
                        ]
                    },
                    "label": {"type": "plain_text", "text": "Status", "emoji": True}
                },
                {
                    "type": "input",
                    "block_id": "priority_filter",
                    "element": {
                        "type": "static_select",
                        "action_id": "priority_select",
                        "placeholder": {"type": "plain_text", "text": "Filter by Priority"},
                        "options": [
                            {"text": {"type": "plain_text", "text": "All Priorities"}, "value": "all"},
                            {"text": {"type": "plain_text", "text": "🔴 High"}, "value": "High"},
                            {"text": {"type": "plain_text", "text": "🟡 Medium"}, "value": "Medium"},
                            {"text": {"type": "plain_text", "text": "🔵 Low"}, "value": "Low"}
                        ]
                    },
                    "label": {"type": "plain_text", "text": "Priority", "emoji": True}
                },
                {
                    "type": "input",
                    "block_id": "start_date",
                    "element": {
                        "type": "datepicker",
                        "action_id": "start_date_select",
                        "initial_date": thirty_days_ago.strftime("%Y-%m-%d"),
                        "placeholder": {"type": "plain_text", "text": "Select a start date"}
                    },
                    "label": {"type": "plain_text", "text": "Start Date", "emoji": True}
                },
                {
                    "type": "input",
                    "block_id": "end_date",
                    "element": {
                        "type": "datepicker",
                        "action_id": "end_date_select",
                        "initial_date": now.strftime("%Y-%m-%d"),
                        "placeholder": {"type": "plain_text", "text": "Select an end date"}
                    },
                    "label": {"type": "plain_text", "text": "End Date", "emoji": True}
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "The CSV will be sent to you as a direct message."}
                    ]
                }
            ]
        }

# Import additional route for checking the database (if needed)
try:
    from check_db_route import add_db_check_route
    print("Successfully imported check_db_route module")
except ImportError:
    print("Could not import check_db_route module, defining function inline")

    def add_db_check_route(app, db_pool):
        """Adds a route to the Flask app for checking database tables"""
        @app.route('/api/check-db', methods=['GET'])
        def check_db():
            """Check database tables and return their status"""
            from flask import jsonify

            try:
                conn = db_pool.getconn()
                cur = conn.cursor()

                # Get list of tables
                cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                """)
                tables = [row[0] for row in cur.fetchall()]

                # Get row counts for each table
                table_counts = {}
                for table in tables:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cur.fetchone()[0]
                    table_counts[table] = count

                return jsonify({
                    "status": "ok",
                    "tables": tables,
                    "counts": table_counts
                })
            except Exception as e:
                return jsonify({
                    "status": "error",
                    "message": str(e)
                }), 500
            finally:
                if 'conn' in locals():
                    db_pool.putconn(conn)

        return app

#######################################
# Configuration & Initialization
#######################################

load_dotenv()  # Load environment variables from .env

# Create Flask app and set start time
app = Flask(__name__)
app.start_time = time.time()

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.info("Logging configured.")

# Environment variables & constants
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
# All notifications will be posted to the system issues channel
SYSTEM_ISSUES_CHANNEL = "C08JTKR1RPT"
SLACK_CHANNEL_ID = SYSTEM_ISSUES_CHANNEL

if not SLACK_BOT_TOKEN or not DATABASE_URL:
    logger.error("Missing required environment variables.")
    raise ValueError("Missing required environment variables.")

# Initialize Slack client
client = WebClient(token=SLACK_BOT_TOKEN)
try:
    auth_test = client.auth_test()
    logger.info(f"Connected as: {auth_test.get('user')} to workspace: {auth_test.get('team')}")
except Exception as e:
    logger.error(f"Error initializing Slack client: {e}")
    raise

# Test Slack channel access
try:
    test_response = client.chat_postMessage(
        channel=SLACK_CHANNEL_ID,
        text="Bot connection test - please ignore",
        as_user=True
    )
    if test_response.get("ok"):
        client.chat_delete(channel=SLACK_CHANNEL_ID, ts=test_response.get("ts"))
        logger.info("Successfully connected to system issues channel")
except Exception as e:
    logger.error(f"Error accessing system issues channel: {e}")
    raise ValueError("Cannot access system issues channel. Check bot permissions.")

# Initialize database connection pool
db_pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
logger.info("Database connection pool initialized.")

#######################################
# Database Schema Initialization
#######################################

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

init_db()
app = add_db_check_route(app, db_pool)

#######################################
# Helper Functions
#######################################

def send_dm(user_id, text, blocks=None):
    """Open a DM with the user and send a message."""
    try:
        dm_response = client.conversations_open(users=user_id)
        channel_id = dm_response["channel"]["id"]
        message_response = client.chat_postMessage(
            channel=channel_id,
            text=text,
            blocks=blocks
        )
        logger.info(f"DM sent to user {user_id} in channel {channel_id}: {message_response.get('ts')}")
    except SlackApiError as e:
        logger.error(f"Error sending DM to {user_id}: {e}")

def is_authorized_user(user_id):
    """Check if the user is a member of the system issues channel."""
    try:
        response = client.conversations_members(channel=SYSTEM_ISSUES_CHANNEL)
        members = response.get("members", [])
        return user_id in members
    except Exception as e:
        logger.error(f"Error checking authorized users: {e}")
        return False

def find_ticket_by_id(ticket_id):
    """Retrieve a ticket record from the database."""
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
        return cur.fetchone()
    finally:
        db_pool.putconn(conn)

def update_ticket_status(ticket_id, status, assigned_to=None, message_ts=None, comment=None, action_user_id=None):
    """
    Update ticket status (and optionally add a comment) in the database,
    then update the original Slack message if a message timestamp is provided.
    """
    logger.info(f"Updating ticket {ticket_id}: Status={status}, Assigned To={assigned_to}")
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        ticket = find_ticket_by_id(ticket_id)
        if not ticket:
            logger.error("Ticket not found")
            return False

        new_assigned_to = assigned_to if assigned_to else ticket[6]
        now = datetime.now(pytz.timezone(TIMEZONE))
        cur.execute(
            "UPDATE tickets SET status = %s, assigned_to = %s, updated_at = %s WHERE ticket_id = %s",
            (status, new_assigned_to, now, ticket_id)
        )
        if comment:
            cur.execute(
                "INSERT INTO comments (ticket_id, user_id, comment_text, created_at) VALUES (%s, %s, %s, %s)",
                (ticket_id, action_user_id, comment, now)
            )
        conn.commit()
        logger.info("Ticket updated in database")

        if message_ts:
            cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
            updated_ticket = cur.fetchone()
            cur.execute("SELECT user_id, comment_text, created_at FROM comments WHERE ticket_id = %s ORDER BY created_at", (ticket_id,))
            comments = cur.fetchall()
            comments_str = "\n".join(
                [f"<@{c[0]}>: {c[1]} ({c[2].strftime('%m/%d/%Y %H:%M:%S')})" for c in comments]
            ) or "N/A"

            # Build updated message blocks (you can also use get_ticket_updated_blocks)
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Updated", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn",
                                               "text": f"*Ticket T{updated_ticket[0]:03d}* - {updated_ticket[3]} (Priority: {updated_ticket[4]})\n"
                                                       f"*Status:* {updated_ticket[5]} {'🟢' if updated_ticket[5]=='Open' else '🔵' if updated_ticket[5]=='In Progress' else '🟡' if updated_ticket[5]=='Resolved' else '🔴'}\n"
                                                       f"*Assigned To:* {f'<@{updated_ticket[6]}>' if updated_ticket[6] != 'Unassigned' else 'Unassigned'}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Details:* {updated_ticket[7]}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Salesforce Link:* {updated_ticket[8] or 'N/A'}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Screenshot/Image:* {f'<{updated_ticket[9]}|View Image>' if updated_ticket[9] != 'No file uploaded' else 'No image uploaded'}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Comments:* {comments_str}"}},
                {"type": "divider"}
            ]

            # Add action buttons based on current ticket state
            action_elements = []
            if updated_ticket[5] == "Open" and updated_ticket[6] == "Unassigned":
                action_elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🖐 Assign to Me", "emoji": True},
                    "action_id": f"assign_to_me_{ticket_id}",
                    "value": str(ticket_id),
                    "style": "primary"
                })
            elif updated_ticket[5] in ["Open", "In Progress"] and updated_ticket[6] != "Unassigned":
                action_elements.extend([
                    {"type": "button", "text": {"type": "plain_text", "text": "🔁 Reassign", "emoji": True},
                     "action_id": f"reassign_{ticket_id}", "value": str(ticket_id)},
                    {"type": "button", "text": {"type": "plain_text", "text": "❌ Close", "emoji": True},
                     "action_id": f"close_{ticket_id}", "value": str(ticket_id), "style": "danger"},
                    {"type": "button", "text": {"type": "plain_text", "text": "🟢 Resolve", "emoji": True},
                     "action_id": f"resolve_{ticket_id}", "value": str(ticket_id), "style": "primary"}
                ])
            elif updated_ticket[5] in ["Closed", "Resolved"]:
                action_elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 Reopen", "emoji": True},
                    "action_id": f"reopen_{ticket_id}",
                    "value": str(ticket_id)
                })
            if action_elements:
                blocks.append({"type": "actions", "elements": action_elements})

            try:
                client.chat_update(channel=SLACK_CHANNEL_ID, ts=message_ts, blocks=blocks)
                logger.info("Slack message updated with new action buttons")
            except Exception as slack_update_err:
                logger.error(f"Error updating Slack message: {slack_update_err}")

        return True
    except Exception as e:
        logger.error(f"Error updating ticket: {e}")
        client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=f"⚠️ Error updating ticket {ticket_id}: {e}")
        return False
    finally:
        db_pool.putconn(conn)

def export_tickets(status_filter, priority_filter, start_date, end_date, user_id):
    """
    Generate a CSV export of tickets based on provided filters and send it to the user.
    """
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        query = "SELECT ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, details, salesforce_link, file_url, created_at, updated_at FROM tickets"
        params = []
        where_clauses = []
        if status_filter and status_filter.lower() != "all":
            where_clauses.append("status = %s")
            params.append(status_filter)
        if priority_filter and priority_filter.lower() != "all":
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

        # Upload the CSV file to the user as a direct message file
        response = client.files_upload(
            channels=user_id,
            content=csv_content,
            filename=f"tickets_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            title="Tickets Export"
        )
        logger.info(f"Exported tickets CSV to user {user_id}: {response.get('ts')}")
    except Exception as e:
        logger.error(f"Error exporting tickets: {e}")
    finally:
        db_pool.putconn(conn)

#######################################
# Modal Builders
#######################################

def build_new_ticket_modal():
    """Construct the modal for submitting a new ticket."""
    return {
        "type": "modal",
        "callback_id": "new_ticket",
        "title": {"type": "plain_text", "text": "Submit a New Ticket"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Please fill out the details below to submit your ticket.*"}
            },
            {"type": "divider"},
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
                        {"text": {"type": "plain_text", "text": "Salesforce Issues (Freeze/Crash)"}, "value": "Salesforce Performance Issues"},
                        {"text": {"type": "plain_text", "text": "Vonage Dialer Issues"}, "value": "Vonage Dialer Functionality Issues"},
                        {"text": {"type": "plain_text", "text": "Broken Links"}, "value": "Broken or Unresponsive Links"},
                        {"text": {"type": "plain_text", "text": "Laptop Won’t Power On"}, "value": "Laptop Fails to Power On"},
                        {"text": {"type": "plain_text", "text": "Slow/Freezing Laptop"}, "value": "Slow Performance or Freezing Laptop"},
                        {"text": {"type": "plain_text", "text": "Other"}, "value": "Other"}
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
                        {"text": {"type": "plain_text", "text": "Low"}, "value": "Low"},
                        {"text": {"type": "plain_text", "text": "Medium"}, "value": "Medium"},
                        {"text": {"type": "plain_text", "text": "High"}, "value": "High"}
                    ]
                },
                "optional": False
            },
            {"type": "divider"},
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
            {"type": "divider"},
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
                "optional": True,
                "label": {"type": "plain_text", "text": "📷 File Attachment"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "file_upload_input",
                    "placeholder": {"type": "plain_text", "text": "Paste the URL of your uploaded file"}
                }
            }
        ]
    }

#######################################
# Route Handlers
#######################################

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

@app.route('/api/tickets/new-ticket', methods=['POST'])
def new_ticket_command():
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

@app.route('/api/tickets/slack/interactivity', methods=['POST'])
def handle_interactivity():
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
                # Get file URL from text input instead of file upload
                file_url = state.get("file_upload_block", {}).get("file_upload_input", {}).get("value", "No file uploaded")
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
                        channel=SLACK_CHANNEL_ID,
                        blocks=message_blocks,
                        text=text_fallback
                    )
                    logger.info(f"Ticket message posted to channel: {channel_response.get('ts')}")
                except Exception as post_err:
                    logger.error(f"Error posting ticket message: {post_err}")

                # Send DM confirmation to submitting user
                confirmation_blocks = get_agent_confirmation_blocks(
                    ticket_id=ticket_id,
                    campaign=campaign,
                    issue_type=issue_type,
                    priority=priority
                )
                send_dm(user_id, f":white_check_mark: Your ticket T{ticket_id:03d} has been submitted successfully!", confirmation_blocks)
                return jsonify({"response_action": "clear"})
            except Exception as e:
                logger.error(f"Error processing new ticket submission: {e}")
                return jsonify({"response_action": "clear"})

        elif callback_id == "assign_to_me_action":
            metadata = json.loads(data["view"]["private_metadata"])
            ticket_id = metadata["ticket_id"]
            user_id = metadata["user_id"]
            message_ts = metadata["message_ts"]
            comment = data["view"]["state"]["values"].get("comment", {}).get("comment_input", {}).get("value")
            update_ticket_status(ticket_id, "In Progress", assigned_to=user_id, message_ts=message_ts, comment=comment, action_user_id=user_id)
            return jsonify({"response_action": "clear"})

        elif callback_id == "reassign_action":
            metadata = json.loads(data["view"]["private_metadata"])
            ticket_id = metadata["ticket_id"]
            message_ts = metadata["message_ts"]
            new_assignee = data["view"]["state"]["values"]["assignee"]["assignee_select"]["selected_user"]
            comment = data["view"]["state"]["values"].get("comment", {}).get("comment_input", {}).get("value")
            update_ticket_status(ticket_id, "In Progress", assigned_to=new_assignee, message_ts=message_ts, comment=comment, action_user_id=user_id)
            return jsonify({"response_action": "clear"})

        elif callback_id == "export_tickets_action":
            # Process export filtering modal submission
            state = data["view"]["state"]["values"]
            status_filter = state["status_filter"]["status_select"]["selected_option"]["value"] if state["status_filter"].get("status_select", {}).get("selected_option") else "all"
            priority_filter = state["priority_filter"]["priority_select"]["selected_option"]["value"] if state["priority_filter"].get("priority_select", {}).get("selected_option") else "all"
            # Parse dates if provided
            start_date = None
            end_date = None
            if state["start_date"].get("start_date_select", {}).get("selected_date"):
                start_date = datetime.strptime(state["start_date"]["start_date_select"]["selected_date"], "%Y-%m-%d")
                start_date = start_date.replace(hour=0, minute=0, second=0, tzinfo=pytz.timezone(TIMEZONE))
            if state["end_date"].get("end_date_select", {}).get("selected_date"):
                end_date = datetime.strptime(state["end_date"]["end_date_select"]["selected_date"], "%Y-%m-%d")
                end_date = end_date.replace(hour=23, minute=59, second=59, tzinfo=pytz.timezone(TIMEZONE))
            export_tickets(status_filter, priority_filter, start_date, end_date, user_id)
            # Return a simple modal view confirming export
            confirmation_view = {
                "type": "modal",
                "title": {"type": "plain_text", "text": "Export Complete", "emoji": True},
                "close": {"type": "plain_text", "text": "Close", "emoji": True},
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": "✅ Tickets have been exported and sent to you as a CSV file."}}
                ]
            }
            return jsonify({"response_action": "update", "view": confirmation_view})
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
        message_ts = data.get("message", {}).get("ts")
        logger.info(f"Action received: {action_id} by user {user_id}")

        if action_id.startswith("assign_to_me_"):
            ticket_id = int(action.get("value"))
            modal = {
                "type": "modal",
                "callback_id": "assign_to_me_action",
                "title": {"type": "plain_text", "text": f"Assign Ticket T{ticket_id:03d}"},
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
            try:
                client.views_open(trigger_id=trigger_id, view=modal)
            except Exception as modal_err:
                logger.error(f"Error opening assign modal: {modal_err}")
            return "", 200

        elif action_id.startswith("reassign_"):
            ticket_id = int(action.get("value"))
            modal = {
                "type": "modal",
                "callback_id": "reassign_action",
                "title": {"type": "plain_text", "text": f"Reassign Ticket T{ticket_id:03d}"},
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
            try:
                client.views_open(trigger_id=trigger_id, view=modal)
            except Exception as modal_err:
                logger.error(f"Error opening reassign modal: {modal_err}")
            return "", 200

        elif action_id.startswith("close_"):
            ticket_id = int(action.get("value"))
            update_ticket_status(ticket_id, "Closed", message_ts=message_ts, action_user_id=user_id)
            return "", 200

        elif action_id.startswith("resolve_"):
            ticket_id = int(action.get("value"))
            update_ticket_status(ticket_id, "Resolved", message_ts=message_ts, action_user_id=user_id)
            return "", 200

        elif action_id.startswith("reopen_"):
            ticket_id = int(action.get("value"))
            update_ticket_status(ticket_id, "Open", message_ts=message_ts, action_user_id=user_id)
            return "", 200

        # If export tickets button clicked, open the dynamic filtering modal
        elif action_id in ["export_tickets", "export_all_tickets"]:
            # Use build_export_filter_modal to create the export filter modal
            modal = build_export_filter_modal()
            try:
                client.views_open(trigger_id=trigger_id, view=modal)
            except Exception as modal_err:
                logger.error(f"Error opening export modal: {modal_err}")
            return "", 200

        # Handle the image upload button click
        elif action_id == "open_file_upload":
            try:
                # Get the user ID from the payload
                user_id = data.get("user", {}).get("id")

                # Send a DM prompting the user to upload a file
                client.chat_postMessage(
                    channel=user_id,
                    text="📷 Please upload your image directly here. It will be attached to your ticket automatically."
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
    if not user_id:
        return jsonify({"text": "Error: Could not identify user."}), 200

    if not is_authorized_user(user_id):
        logger.info(f"User {user_id} is not authorized to access system tickets.")
        return jsonify({
            "response_type": "ephemeral",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "❌ You are not authorized to view system tickets."}}
            ]
        }), 200

    # Build system tickets modal here (for now, this is a placeholder)
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "System Tickets", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "Dynamic filtering and ticket list coming soon."}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Export Tickets", "emoji": True},
             "action_id": "export_tickets", "value": "export"}
        ]}
    ]
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
            logger.error(f"Error opening system tickets modal: {e}")
            return jsonify({"text": "❌ An error occurred while displaying system tickets."}), 200
    else:
        return jsonify({"response_type": "ephemeral", "blocks": blocks}), 200

@app.route('/api/tickets/ticket-summary', methods=['POST'])
def ticket_summary():
    user_id = request.form.get('user_id')
    if not user_id:
        return jsonify({"text": "Error: Could not identify user."}), 200

    if not is_authorized_user(user_id):
        return jsonify({"text": "❌ You are not authorized to view ticket summary."}), 200

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
        {"type": "section", "text": {"type": "mrkdwn",
                                      "text": f"*Total Tickets:* {total_tickets}\n"
                                              f"*Open:* {open_tickets}\n"
                                              f"*In Progress:* {in_progress_tickets}\n"
                                              f"*Resolved:* {resolved_tickets}\n"
                                              f"*Closed:* {closed_tickets}\n"
                                              f"*High Priority:* {high_priority}\n"
                                              f"*Unassigned:* {unassigned}\n"}}
    ]
    return jsonify({"response_type": "ephemeral", "blocks": blocks}), 200

#######################################
# Scheduler Setup
#######################################

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
        client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=f"⚠️ Overdue tickets check failed: {e}")
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
                    "text": {"type": "mrkdwn",
                             "text": f"*T{ticket_id:03d}* | {priority} Priority | {status} | {days_stale} days stale\n"
                                     f">*Issue:* {issue_type}\n"
                                     f">*Assigned to:* {f'<@{assigned_to}>' if assigned_to != 'Unassigned' else 'Unassigned'}\n"
                                     f">*Campaign:* {campaign}"}
                })
            client.chat_postMessage(channel=SLACK_CHANNEL_ID, blocks=blocks)
            logger.info(f"Stale tickets report sent with {len(stale_tickets)} tickets")
    except Exception as e:
        logger.error(f"Error in stale tickets check: {e}")
        client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=f"⚠️ Stale tickets check failed: {e}")
    finally:
        db_pool.putconn(conn)

# Schedule overdue and stale ticket checks every 24 hours
scheduler.add_job(check_overdue_tickets, "interval", hours=24)
scheduler.add_job(check_stale_tickets, "interval", hours=24, start_date=datetime.now() + timedelta(minutes=30))

#######################################
# Run the Application
#######################################

if __name__ == "__main__":
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    logger.info("Starting Flask server with scheduler...")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
else:
    logger.info("Starting Flask server via Gunicorn (scheduler not started here)...")