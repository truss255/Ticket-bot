import csv
import io
from datetime import datetime
import pytz
from database import db_pool
from slack_client import client
from config import TIMEZONE, SYSTEM_ISSUES_CHANNEL

def send_dm(user_id, text, blocks=None):
    from slack_client import send_dm as slack_send_dm
    return slack_send_dm(user_id, text, blocks)

def is_authorized_user(user_id):
    try:
        response = client.conversations_members(channel=SYSTEM_ISSUES_CHANNEL)
        return user_id in response.get("members", [])
    except Exception:
        return False

def find_ticket_by_id(ticket_id):
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
        return cur.fetchone()
    finally:
        db_pool.putconn(conn)

def update_ticket_status(ticket_id, status, assigned_to=None, message_ts=None, comment=None, action_user_id=None):
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        ticket = find_ticket_by_id(ticket_id)
        if not ticket:
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

        if message_ts:
            cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (ticket_id,))
            updated_ticket = cur.fetchone()
            cur.execute("SELECT user_id, comment_text, created_at FROM comments WHERE ticket_id = %s ORDER BY created_at", (ticket_id,))
            comments = cur.fetchall()
            comments_str = "\n".join([f"<@{c[0]}>: {c[1]} ({c[2].strftime('%m/%d/%Y %H:%M:%S')})" for c in comments]) or "N/A"
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Details:* {updated_ticket[7]}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Salesforce Link:* {updated_ticket[8] or 'N/A'}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Screenshot/Image:* {f'<{updated_ticket[9]}|View Image>' if updated_ticket[9] != 'No file uploaded' else 'No image uploaded'}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Comments:* {comments_str}"}},
                {"type": "divider"}
            ]
            action_elements = []
            if updated_ticket[5] == "Open" and updated_ticket[6] == "Unassigned":
                action_elements.append({"type": "button", "text": {"type": "plain_text", "text": "🖐 Assign to Me", "emoji": True},
                                        "action_id": f"assign_to_me_{ticket_id}", "value": str(ticket_id), "style": "primary"})
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
                action_elements.append({"type": "button", "text": {"type": "plain_text", "text": "🔄 Reopen", "emoji": True},
                                        "action_id": f"reopen_{ticket_id}", "value": str(ticket_id)})
            if action_elements:
                blocks.append({"type": "actions", "elements": action_elements})
            client.chat_update(channel=SYSTEM_ISSUES_CHANNEL, ts=message_ts, blocks=blocks)
        return True
    finally:
        db_pool.putconn(conn)

def export_tickets(status_filter, priority_filter, start_date, end_date, user_id):
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

        client.files_upload(
            channels=user_id,
            content=csv_content,
            filename=f"tickets_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            title="Tickets Export"
        )
    finally:
        db_pool.putconn(conn)