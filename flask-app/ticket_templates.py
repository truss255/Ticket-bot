"""
Ticket message templates for Slack
"""

def get_ticket_submission_blocks(ticket_id, campaign, issue_type, priority, user_id, details, salesforce_link, file_url):
    # Return blocks for ticket submission
    return [
        # ...template blocks for ticket submission...
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