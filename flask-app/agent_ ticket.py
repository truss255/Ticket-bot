from flask import request, jsonify
import json
from slack_sdk.errors import SlackApiError

def get_agent_tickets(user_id, status_filter="Open", sort_by="created_at", tickets_db=None):
    """Fetch tickets assigned to the agent, filtered by status and sorted."""
    if tickets_db is None:
        return []
    tickets = [(tid, ticket) for tid, ticket in tickets_db.items() if ticket["assigned_to"] == user_id]
    if status_filter != "all":
        tickets = [t for t in tickets if t[1]["status"] == status_filter]
    # Sort tickets
    if sort_by == "priority":
        priority_order = {"High": 0, "Medium": 1, "Low": 2}
        tickets.sort(key=lambda x: priority_order.get(x[1]["priority"], 3))
    else:  # Default to created_at
        tickets.sort(key=lambda x: x[1].get("created_at", 0))
    return tickets

def generate_ticket_list_blocks(tickets, page=0, per_page=5):
    """Generate Slack blocks for a paginated list of tickets."""
    if not tickets:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "No tickets found."}}]
    start = page * per_page
    end = start + per_page
    blocks = []
    for ticket_id, ticket in tickets[start:end]:
        campaign = ticket["campaign"]
        issue_type = ticket["issue_type"]
        priority = ticket["priority"]
        status = ticket["status"]
        assignee = ticket["assigned_to"]
        assignee_text = f"👤 *Assigned to:* <@{assignee}>" if assignee != "Unassigned" else "👤 *Assigned to:* Unassigned"
        ticket_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Ticket ID:* 🎟️ T{ticket_id:03d}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"📂 *Campaign:* {campaign}"},
                    {"type": "mrkdwn", "text": f"📌 *Issue Type:* {issue_type}"},
                    {"type": "mrkdwn", "text": f"⚡ *Priority:* {'🔴 High' if priority == 'High' else '🟡 Medium' if priority == 'Medium' else '🔵 Low'}"},
                    {"type": "mrkdwn", "text": f"🔄 *Status:* {status}"}
                ]
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": assignee_text}]
            },
            {"type": "divider"}
        ]
        blocks.extend(ticket_blocks)
    # Pagination buttons
    total_pages = (len(tickets) + per_page - 1) // per_page
    if total_pages > 1:
        buttons = []
        if page > 0:
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Previous"},
                "action_id": "prev_page",
                "value": str(page - 1)
            })
        if page < total_pages - 1:
            buttons.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Next"},
                "action_id": "next_page",
                "value": str(page + 1)
            })
        blocks.append({"type": "actions", "elements": buttons})
    return blocks[:-1] if not blocks[-1]["type"] == "actions" else blocks

def agent_tickets(client, tickets_db, logger):
    """Handle the /agent-tickets Slack command to open a modal."""
    user_id = request.form["user_id"]
    trigger_id = request.form["trigger_id"]
    initial_tickets = get_agent_tickets(user_id, "Open", "created_at", tickets_db)
    ticket_blocks = generate_ticket_list_blocks(initial_tickets, 0)
    modal = {
        "type": "modal",
        "callback_id": "agent_tickets_view",
        "title": {"type": "plain_text", "text": "Your Assigned Tickets"},
        "blocks": [
            {
                "type": "input",
                "block_id": "status_filter",
                "label": {"type": "plain_text", "text": "Filter by Status"},
                "element": {
                    "type": "static_select",
                    "action_id": "status_select",
                    "placeholder": {"type": "plain_text", "text": "Select status"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "All"}, "value": "all"},
                        {"text": {"type": "plain_text", "text": "Open"}, "value": "Open"},
                        {"text": {"type": "plain_text", "text": "In Progress"}, "value": "In Progress"},
                        {"text": {"type": "plain_text", "text": "Resolved"}, "value": "Resolved"},
                        {"text": {"type": "plain_text", "text": "Closed"}, "value": "Closed"}
                    ],
                    "initial_option": {"text": {"type": "plain_text", "text": "Open"}, "value": "Open"}
                }
            },
            {
                "type": "input",
                "block_id": "sort_filter",
                "label": {"type": "plain_text", "text": "Sort By"},
                "element": {
                    "type": "static_select",
                    "action_id": "sort_select",
                    "placeholder": {"type": "plain_text", "text": "Select sort option"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Created Date"}, "value": "created_at"},
                        {"text": {"type": "plain_text", "text": "Priority"}, "value": "priority"}
                    ],
                    "initial_option": {"text": {"type": "plain_text", "text": "Created Date"}, "value": "created_at"}
                }
            },
            {
                "type": "section",
                "block_id": "tickets_list",
                "text": {"type": "mrkdwn", "text": "*Your Tickets:*"}
            }
        ] + ticket_blocks
    }
    try:
        client.views_open(trigger_id=trigger_id, view=modal)
        return "", 200
    except SlackApiError as e:
        logger.error(f"Error opening modal: {e}")
        return jsonify({"text": "Error opening modal"}), 200

def handle_interactivity(payload, client, tickets_db):
    """Handle interactivity in the modal (filter, sort, pagination)."""
    if payload["type"] != "block_actions":
        return False
    action = payload["actions"][0]
    user_id = payload["user"]["id"]
    view_id = payload["view"]["id"]
    current_blocks = payload["view"]["blocks"]
    status_filter = next((b["element"]["initial_option"]["value"] for b in current_blocks if b["block_id"] == "status_filter"), "Open")
    sort_by = next((b["element"]["initial_option"]["value"] for b in current_blocks if b["block_id"] == "sort_filter"), "created_at")
    page = int(action["value"]) if action["action_id"] in ["next_page", "prev_page"] else 0

    if action["action_id"] == "status_select":
        status_filter = action["selected_option"]["value"]
    elif action["action_id"] == "sort_select":
        sort_by = action["selected_option"]["value"]
    elif action["action_id"] in ["next_page", "prev_page"]:
        page = int(action["value"])

    filtered_tickets = get_agent_tickets(user_id, status_filter, sort_by, tickets_db)
    ticket_blocks = generate_ticket_list_blocks(filtered_tickets, page)
    updated_view = {
        "type": "modal",
        "callback_id": "agent_tickets_view",
        "title": {"type": "plain_text", "text": "Your Assigned Tickets"},
        "blocks": [
            {
                "type": "input",
                "block_id": "status_filter",
                "label": {"type": "plain_text", "text": "Filter by Status"},
                "element": {
                    "type": "static_select",
                    "action_id": "status_select",
                    "placeholder": {"type": "plain_text", "text": "Select status"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "All"}, "value": "all"},
                        {"text": {"type": "plain_text", "text": "Open"}, "value": "Open"},
                        {"text": {"type": "plain_text", "text": "In Progress"}, "value": "In Progress"},
                        {"text": {"type": "plain_text", "text": "Resolved"}, "value": "Resolved"},
                        {"text": {"type": "plain_text", "text": "Closed"}, "value": "Closed"}
                    ],
                    "initial_option": {
                        "text": {"type": "plain_text", "text": status_filter.capitalize()},
                        "value": status_filter
                    }
                }
            },
            {
                "type": "input",
                "block_id": "sort_filter",
                "label": {"type": "plain_text", "text": "Sort By"},
                "element": {
                    "type": "static_select",
                    "action_id": "sort_select",
                    "placeholder": {"type": "plain_text", "text": "Select sort option"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "Created Date"}, "value": "created_at"},
                        {"text": {"type": "plain_text", "text": "Priority"}, "value": "priority"}
                    ],
                    "initial_option": {
                        "text": {"type": "plain_text", "text": "Created Date" if sort_by == "created_at" else "Priority"},
                        "value": sort_by
                    }
                }
            },
            {
                "type": "section",
                "block_id": "tickets_list",
                "text": {"type": "mrkdwn", "text": "*Your Tickets:*"}
            }
        ] + ticket_blocks
    }
    client.views_update(view_id=view_id, view=updated_view)
    return True