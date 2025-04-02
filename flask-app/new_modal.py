Q1Q11Q
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
                    "placeholder": {"type": "plain_text", "text": "Describe the issue in detail"}
                },
                "optional": False
            },
            {"type": "divider"},
            # Salesforce link field
            {
                "type": "input",
                "block_id": "salesforce_link_block",
                "label": {"type": "plain_text", "text": "📎 Salesforce Link"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "salesforce_link_input",
                    "placeholder": {"type": "plain_text", "text": "Paste Salesforce URL (if applicable)"}
                },
                "optional": True
            },
            # File attachment field
            {
                "type": "input",
                "block_id": "file_upload_block",
                "optional": True,
                "label": {"type": "plain_text", "text": "📷 Screenshot/Image URL"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "file_upload_input",
                    "placeholder": {"type": "plain_text", "text": "Automatically filled after upload (optional)"}
                }
            },
            {"type": "divider"},
            # Upload Image Button
            {
                "type": "actions",
                "block_id": "upload_actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🖼️ Upload Image", "emoji": True},
                        "action_id": "open_file_upload"
                    }
                ]
            }
        ]
    }

def build_ticket_confirmation_modal(ticket_id, campaign, issue_type, priority):
    """
    Construct a confirmation modal view to display after a successful ticket submission.
    The confirmation informs the user that the system team is reviewing the ticket,
    and that they will be notified when the status changes.
    """
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
