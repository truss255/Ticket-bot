from datetime import datetime, timedelta
import pytz

TIMEZONE = "America/New_York"  # Match with app.py

def get_ticket_submission_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url):
    """Generate blocks for a new ticket submission in #systems-issues."""
    now = datetime.now(pytz.timezone(TIMEZONE))
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "🎫 New Ticket Alert", "emoji": True}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":ticket: *T{ticket_id:03d}* | {priority} Priority {' :fire:' if priority == 'High' else ' :hourglass_flowing_sand:' if priority == 'Medium' else ''}\n"
                        f"*Campaign:* {campaign}\n"
                        f"*Issue:* {issue_type}\n"
                        f"*Created by:* <@{user_id}>\n"
                        f"*Priority:* {priority} {' 🔴' if priority == 'High' else ' 🟡' if priority == 'Medium' else ' 🔵'}\n"
                        f"*Status:* Open 🟢"
            }
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"✏️ *Details:* {details}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":link: *Salesforce Link:* {salesforce_link if salesforce_link != 'N/A' else 'N/A'}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":camera: *Screenshot/Image:* {f'<{file_url}|View Image>' if file_url != 'No file uploaded' else 'No image uploaded'}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"📅 *Created:* {now.strftime('%m/%d/%Y (%A)')}"}},
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "🖐 Assign to Me", "emoji": True}, "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"}
            ]
        }
    ]

def get_agent_confirmation_blocks(ticket_id, campaign, issue_type, priority):
    """Generate blocks for agent confirmation message (used in modal now)."""
    now = datetime.now(pytz.timezone(TIMEZONE))
    return [
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
        }
    ]

def get_ticket_updated_blocks(ticket_id, campaign, issue_type, priority, assigned_to, status, details, salesforce_link, file_url, created_at, comments):
    """Generate blocks for updated ticket (not currently used but included for completeness)."""
    comments_str = "\n".join([f"<@{c[0]}>: {c[1]} ({c[2].strftime('%m/%d/%Y %H:%M:%S')})" for c in comments]) or "N/A"
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "🎫 Ticket Updated", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":ticket: *Ticket Updated* | T{ticket_id:03d} | {priority} Priority {':fire:' if priority == 'High' else ':hourglass_flowing_sand:' if priority == 'Medium' else ''}\n\n"}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"📂 *Campaign:* {campaign}\n\n"
                        f"📌 *Issue:* {issue_type}\n\n"
                        f"⚡ *Priority:* {priority} {' 🔴' if priority == 'High' else ' 🟡' if priority == 'Medium' else ' 🔵'}\n\n"
                        f"👤 *Assigned To:* {f'<@{assigned_to}>' if assigned_to != 'Unassigned' else 'Unassigned'}\n\n"
                        f"🔄 *Status:* `{status}` {'🟢' if status == 'Open' else '🔵' if status == 'In Progress' else '🟡' if status == 'Resolved' else '🔴'}\n\n"
            }
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"✏️ *Details:* {details}\n\n"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":link: *Salesforce Link:* {salesforce_link or 'N/A'}\n\n"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":camera: *Screenshot/Image:* {f'<{file_url}|View Image>' if file_url != 'No file uploaded' else 'No image uploaded'}\n\n"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"📅 *Created:* {created_at.strftime('%m/%d/%Y %I:%M %p')} ({created_at.strftime('%A')})\n\n"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"💬 *Comments:* {comments_str}\n\n"}}
    ]

def build_export_filter_modal():
    """Build a modal for exporting tickets with filters."""
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