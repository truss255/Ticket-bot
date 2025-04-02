import logging
from slack_sdk.errors import SlackApiError
from ticket_templates import build_new_ticket_modal, get_system_ticket_blocks, get_agent_confirmation_blocks
from utils import send_dm
from database import db_pool
from datetime import datetime
import pytz
from config import TIMEZONE, SYSTEM_ISSUES_CHANNEL

logger = logging.getLogger(__name__)

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

def new_ticket_command(request, client, db_pool):
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
        finally:
            db_pool.putconn(conn)

        message_blocks = get_system_ticket_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url)
        client.chat_postMessage(channel=SYSTEM_ISSUES_CHANNEL, blocks=message_blocks, text=f"New Ticket T{ticket_id:03d}")

        confirmation_blocks = get_agent_confirmation_blocks(ticket_id, campaign, issue_type, priority)
        send_dm(user_id, f":white_check_mark: Your ticket T{ticket_id:03d} has been submitted!", confirmation_blocks)

        return {"response_action": "clear"}
    except Exception as e:
        logger.error(f"Error processing submission: {e}")
        return {"response_action": "clear"}