def get_system_ticket_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url):
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"🎟 *New Ticket Created!* (T{ticket_id:03d})"}},
        {"type": "divider"},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"📂 *Campaign:* {campaign}"},
            {"type": "mrkdwn", "text": f"📌 *Issue:* {issue_type}"}
        ]},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"⚡ *Priority:* {'🔴 High' if priority == 'High' else '🟡 Medium' if priority == 'Medium' else '🔵 Low'}"},
            {"type": "mrkdwn", "text": f"👤 *Assigned To:* ❌ Unassigned"}
        ]},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"🔄 *Status:* 🟢 Open"},
            {"type": "mrkdwn", "text": f"👤 *Submitted By:* <@{user_id}>"}
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"✏️ *Details:* {details}"}}
    ]
    if salesforce_link and salesforce_link != "N/A":
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"🔗 *Salesforce Link:* <{salesforce_link}|Click Here>"}})
    if file_url and file_url != "No file uploaded":
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"📷 *File Attachment:* <{file_url}|View Screenshot>"}})
    blocks.extend([
        {"type": "divider"},
        {"type": "actions", "block_id": f"ticket_actions_{ticket_id}", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "🔘 Assign to Me", "emoji": True},
             "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"}
        ]}
    ])
    return blocks

def get_ticket_submission_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url):
    return get_system_ticket_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url)

def get_agent_confirmation_blocks(ticket_id, campaign, issue_type, priority):
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "✅ *Ticket Submitted Successfully!*"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"🎟️ *Ticket ID:* T{ticket_id:03d}"},
            {"type": "mrkdwn", "text": f"📂 *Campaign:* {campaign}"}
        ]},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"📌 *Issue Type:* {issue_type}"},
            {"type": "mrkdwn", "text": f"⚡ *Priority:* {'🔴 High' if priority == 'High' else '🟡 Medium' if priority == 'Medium' else '🔵 Low'}"}
        ]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "📣 Your ticket has been posted in `#systems-issues`.\n👀 The systems team has been notified and will review it shortly.\n📊 You can check your ticket status anytime using: `/agent-tickets`"}}
    ]

def get_ticket_updated_blocks(ticket_id, priority, issue_type, assigned_to, status, comment=None):
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"🎟 *Ticket Updated!* (T{ticket_id:03d})"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"👤 *Assigned To:* @{assigned_to}"},
            {"type": "mrkdwn", "text": f"🔄 *Status:* {'🟢 Open' if status == 'Open' else '🔵 In Progress' if status == 'In Progress' else '🟡 Resolved' if status == 'Resolved' else '❌ Closed'}"}
        ]}
    ]
    if comment:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"💬 *Comment:* \"{comment}\""}})
    blocks.extend([
        {"type": "divider"},
        {"type": "actions", "block_id": f"ticket_update_actions_{ticket_id}", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "🔁 Reassign", "emoji": True},
             "action_id": f"reassign_{ticket_id}", "value": str(ticket_id)},
            {"type": "button", "text": {"type": "plain_text", "text": "🟢 Resolve", "emoji": True},
             "action_id": f"resolve_{ticket_id}", "value": str(ticket_id)},
            {"type": "button", "text": {"type": "plain_text", "text": "❌ Close", "emoji": True},
             "action_id": f"close_{ticket_id}", "value": str(ticket_id), "style": "danger"}
        ]}
    ])
    return blocks

def build_export_filter_modal():
    from datetime import datetime, timedelta
    import pytz
    now = datetime.now(pytz.timezone("America/New_York"))
    thirty_days_ago = now - timedelta(days=30)
    return {
        "type": "modal",
        "callback_id": "export_tickets_action",
        "title": {"type": "plain_text", "text": "Export Tickets", "emoji": True},
        "submit": {"type": "plain_text", "text": "Export", "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Select filters for ticket export:*"}},
            {"type": "input", "block_id": "status_filter", "element": {
                "type": "static_select", "action_id": "status_select", "placeholder": {"type": "plain_text", "text": "Filter by Status"},
                "options": [
                    {"text": {"type": "plain_text", "text": "All Statuses"}, "value": "all"},
                    {"text": {"type": "plain_text", "text": "🟢 Open"}, "value": "Open"},
                    {"text": {"type": "plain_text", "text": "🔵 In Progress"}, "value": "In Progress"},
                    {"text": {"type": "plain_text", "text": "🟡 Resolved"}, "value": "Resolved"},
                    {"text": {"type": "plain_text", "text": "🔴 Closed"}, "value": "Closed"}
                ]
            }, "label": {"type": "plain_text", "text": "Status", "emoji": True}},
            {"type": "input", "block_id": "priority_filter", "element": {
                "type": "static_select", "action_id": "priority_select", "placeholder": {"type": "plain_text", "text": "Filter by Priority"},
                "options": [
                    {"text": {"type": "plain_text", "text": "All Priorities"}, "value": "all"},
                    {"text": {"type": "plain_text", "text": "🔴 High"}, "value": "High"},
                    {"text": {"type": "plain_text", "text": "🟡 Medium"}, "value": "Medium"},
                    {"text": {"type": "plain_text", "text": "🔵 Low"}, "value": "Low"}
                ]
            }, "label": {"type": "plain_text", "text": "Priority", "emoji": True}},
            {"type": "input", "block_id": "start_date", "element": {
                "type": "datepicker", "action_id": "start_date_select", "initial_date": thirty_days_ago.strftime("%Y-%m-%d"),
                "placeholder": {"type": "plain_text", "text": "Select a start date"}
            }, "label": {"type": "plain_text", "text": "Start Date", "emoji": True}},
            {"type": "input", "block_id": "end_date", "element": {
                "type": "datepicker", "action_id": "end_date_select", "initial_date": now.strftime("%Y-%m-%d"),
                "placeholder": {"type": "plain_text", "text": "Select an end date"}
            }, "label": {"type": "plain_text", "text": "End Date", "emoji": True}},
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": "The CSV will be sent to you as a direct message."}
            ]}
        ]
    }