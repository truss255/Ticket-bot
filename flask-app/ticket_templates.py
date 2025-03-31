"""
Ticket message templates for Slack
"""

def get_ticket_submission_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url):
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
        {"type": "section", "text": {"type": "mrkdwn", "text": f":link: *Salesforce Link:* {salesforce_link if salesforce_link != 'N/A' else 'N/A'}}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f":camera: *Screenshot/Image:* {f'<{file_url}|View Image>' if file_url != 'No file uploaded' else 'No image uploaded'}}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"📅 *Created:* {datetime.now(pytz.timezone('America/New_York')).strftime('%m/%d/%Y (%A)')}}},
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "🖐 Assign to Me", "emoji": True}, "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"}
            ]
        }
    ]

def get_agent_confirmation_blocks(ticket_id, campaign, issue_type, priority):
    # Return blocks for agent confirmation
    return [
        # ...template blocks for agent confirmation...
    ]

def get_ticket_updated_blocks(ticket_id, status, assigned_to, comments):
    # Return blocks for ticket updates
    return [
        # ...template blocks for ticket updates...
    ]