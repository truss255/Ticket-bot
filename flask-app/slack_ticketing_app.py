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

SLACK_CHANNEL_ID = "C08JTKR1RPT"
logger.info(f"Using Slack channel ID: {SLACK_CHANNEL_ID}")

# Verify channel access directly
try:
    # Try posting a test message instead of checking channel info
    test_response = client.chat_postMessage(
        channel=SLACK_CHANNEL_ID,
        text="Bot connection test - please ignore",
        as_user=True
    )
    if test_response["ok"]:
        # If successful, delete the test message
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

# Initialize database connection pool (unchanged)
db_pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
logger.info("Database connection pool initialized.")

# Add SYSTEM_USERS initialization
SYSTEM_USERS = os.getenv("SYSTEM_USERS", "").split(",")
logger.info(f"System users loaded: {SYSTEM_USERS}")

# Add database initialization function
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
                salesforce_link TEXT,
                file_url TEXT,
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
        logger.info("Database schema verified/created")
    except Exception as e:
        logger.error(f"Error initializing DB: {e}")
        raise
    finally:
        db_pool.putconn(conn)

# Initialize the database schema
init_db()

# Add find_ticket_by_id function
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

# Add update_ticket_status function
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
                {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Details", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":white_check_mark: *Ticket ID:* T{ticket_id}\n\n"}},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":file_folder: *Campaign:* {updated_ticket[2]}\n\n"
                                f":pushpin: *Issue:* {updated_ticket[3]}\n\n"
                                f":zap: *Priority:* {updated_ticket[4]} {' :red_circle:' if updated_ticket[4] == 'High' else ' :large_yellow_circle:' if updated_ticket[4] == 'Medium' else ' :large_blue_circle:'}\n\n"
                                f":bust_in_silhouette: *Assigned To:* {'<@' + updated_ticket[6] + '>' if updated_ticket[6] != 'Unassigned' else ':x: Unassigned'}\n\n"
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

# Add build_export_filter_modal function
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

@app.route('/new-ticket', methods=['POST'])
def new_ticket():
    """
    Slash command: /new-ticket
    Opens a modal for submitting a new ticket.
    """
    logger.info("Received /new-ticket request")
    try:
        trigger_id = request.form.get('trigger_id')
        modal = build_new_ticket_modal()

        # Open the modal
        response = requests.post(
            "https://slack.com/api/views.open",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            json={"trigger_id": trigger_id, "view": modal}
        )
        return jsonify(response.json())
    except Exception as e:
        logger.error(f"Error in /new-ticket: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tickets/agent-tickets", methods=["POST"])
def agent_tickets():
    """
    Slash command: /agent-tickets
    Displays a modal with the agent's submitted tickets.
    """
    logger.info("Received /agent-tickets request")
    try:
        # Implementation for displaying agent's tickets goes here
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error in /agent-tickets: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/tickets/system-tickets", methods=["POST"])
def system_tickets():
    """
    Slash command: /system-tickets
    Displays a list of system tickets for system users only.
    """
    logger.info("Received /system-tickets request")
    try:
        user_id = request.form.get("user_id")
        if not is_system_user(user_id):
            return jsonify({"text": "❌ You do not have permission to view system tickets."}), 403

        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM tickets WHERE status IN ('Open', 'In Progress') ORDER BY priority DESC, created_at ASC")
            tickets = cur.fetchall()
        finally:
            db_pool.putconn(conn)

        if not tickets:
            return jsonify({"text": "🎉 No system tickets found."})

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "📂 System Tickets"}},
            {"type": "divider"}
        ]
        for ticket in tickets:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*T{ticket[0]}* _({ticket[5]} {'🟢' if ticket[5] == 'Open' else '🔵' if ticket[5] == 'In Progress' else '🟡' if ticket[5] == 'Resolved' else '🔴'})_\n"
                            f"*Campaign:* {ticket[2]}\n"
                            f"*Issue:* {ticket[3]}\n"
                            f"*Priority:* {ticket[4]} {'🔴' if ticket[4] == 'High' else '🟡' if ticket[4] == 'Medium' else '🔵'}\n"
                            f"*Created At:* {ticket[10].strftime('%m/%d/%Y')}\n"
                }
            })
            blocks.append({"type": "divider"})

        return jsonify({"blocks": blocks})
    except Exception as e:
        logger.error(f"Error in /system-tickets: {e}")
        return jsonify({"text": "❌ An error occurred while processing the request."}), 500


@app.route("/api/tickets/ticket-summary", methods=["POST"])
def ticket_summary():
    """
    Slash command: /ticket-summary
    Displays a summary of tickets for system users only.
    """
    logger.info("Received /ticket-summary request")
    try:
        user_id = request.form.get("user_id")
        if not is_system_user(user_id):
            return jsonify({"text": "❌ You do not have permission to view the ticket summary."}), 403

        conn = db_pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT status, COUNT(*) FROM tickets GROUP BY status")
            status_counts = cur.fetchall()
        finally:
            db_pool.putconn(conn)

        summary = "*📊 Ticket Summary*\n\n"
        total_tickets = 0
        for status, count in status_counts:
            total_tickets += count
            emoji = "🟢" if status == "Open" else "🔵" if status == "In Progress" else "🟡" if status == "Resolved" else "🔴"
            summary += f"{emoji} *{status}:* {count}\n"
        summary += f"\n*Total Tickets:* {total_tickets}"

        return jsonify({"text": summary})
    except Exception as e:
        logger.error(f"Error in /ticket-summary: {e}")
        return jsonify({"text": "❌ An error occurred while processing the request."}), 500

@app.route("/api/tickets/slack/events", methods=["POST"])
def handle_slack_events():
    """
    Handles block actions and view submissions, including:
    - Export tickets (triggered by /export-all-tickets).
    """
    logger.info("Received Slack event")
    try:
        data = json.loads(request.form.get('payload'))

        # Handle ticket submission
        if data.get("type") == "view_submission" and data["view"]["callback_id"] == "new_ticket":
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

            # Post ticket details to Slack channel
            message_blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Details", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":white_check_mark: *Ticket ID:* T{ticket_id}\n\n"}},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":file_folder: *Campaign:* {campaign}\n\n"
                                f":pushpin: *Issue:* {issue_type}\n\n"
                                f":zap: *Priority:* {priority} {' :red_circle:' if priority == 'High' else ' :large_yellow_circle:' if priority == 'Medium' else ' :large_blue_circle:'}\n\n"
                                f":bust_in_silhouette: *Assigned To:* :x: Unassigned\n\n"
                                f":gear: *Status:* Open :green_circle:\n\n"
                    }
                },
                {"type": "divider"},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":writing_hand: *Details:* {details}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":link: *Salesforce Link:* {salesforce_link}\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":file_folder: *File Attachment:* No file uploaded\n\n"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f":calendar: *Created Date:* {now.strftime('%m/%d/%Y')}\n\n"}},
                {"type": "divider"},
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "🖐 Assign to Me", "emoji": True}, "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"} if is_system_user(user_id) else None
                    ]
                }
            ]
            message_blocks[-1]["elements"] = [elem for elem in message_blocks[-1]["elements"] if elem]
            client.chat_postMessage(channel=SLACK_CHANNEL_ID, blocks=message_blocks)

            # Show confirmation modal
            confirmation_view = {
                "type": "modal",
                "callback_id": "ticket_confirmation",
                "title": {"type": "plain_text", "text": "Ticket Submitted"},
                "close": {"type": "plain_text", "text": "Close"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"🎉 *Ticket T{ticket_id} has been submitted successfully!*\n\n"
                                    f"You can check the status of your ticket by running:\n"
                                    f"`/agent-tickets`\n\n"
                                    f"Your ticket details have been posted in <#{SLACK_CHANNEL_ID}>."
                        }
                    }
                ]
            }
            client.views_open(trigger_id=data["trigger_id"], view=confirmation_view)
            return jsonify({"response_action": "clear"})

        # Handle block actions
        elif data.get("type") == "block_actions":
            action = data["actions"][0]
            action_id = action["action_id"]
            user_id = data["user"]["id"]
            trigger_id = data["trigger_id"]
            message_ts = data["message"]["ts"] if "message" in data else None

            if action_id.startswith("assign_to_me_"):
                ticket_id = int(action["value"])
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
                ticket_id = int(action["value"])
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
                ticket_id = int(action["value"])
                update_ticket_status(ticket_id, "Closed", message_ts=message_ts, action_user_id=user_id)
                return "", 200

            elif action_id.startswith("resolve_"):
                ticket_id = int(action["value"])
                update_ticket_status(ticket_id, "Resolved", message_ts=message_ts, action_user_id=user_id)
                return "", 200

            elif action_id.startswith("reopen_"):
                ticket_id = int(action["value"])
                update_ticket_status(ticket_id, "Open", message_ts=message_ts, action_user_id=user_id)
                return "", 200

        # Handle view submissions
        elif data.get("type") == "view_submission":
            callback_id = data["view"]["callback_id"]
            if callback_id == "assign_to_me_action":
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
                assignee = data["view"]["state"]["values"]["assignee"]["assignee_select"]["selected_user"]
                comment = data["view"]["state"]["values"]["comment"]["comment_input"]["value"] if "comment" in data["view"]["state"]["values"] else None
                update_ticket_status(ticket_id, "In Progress", assigned_to=assignee, message_ts=message_ts, comment=comment, action_user_id=data["user"]["id"])
                return jsonify({"response_action": "clear"})

        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error handling Slack event: {e}")
        return jsonify({"text": "❌ An error occurred while processing the event."}), 500

if __name__ == "__main__":
    logger.info("Starting Flask server...")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
