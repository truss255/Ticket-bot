"""
This module contains functions for building modal dialogs for the ticket system.
"""

def build_new_ticket_modal():
    """
    Construct the modal for submitting a new ticket with an optional file attachment and enhanced layout.
    """
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
                "label": {"type": "plain_text", "text": "📎 Salesforce Link"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "salesforce_link_input",
                    "placeholder": {"type": "plain_text", "text": "Paste Salesforce URL if applicable"}
                },
                "optional": True
            },
            # File attachment field
            {
                "type": "input",
                "block_id": "file_upload_block",
                "label": {
                    "type": "plain_text",
                    "text": "🖼️ Attach Screenshot (optional)"
                },
                "element": {
                    "type": "file_input",
                    "action_id": "file_upload_action"
                },
                "optional": True
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

