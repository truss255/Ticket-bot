from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import pytz
from database import db_pool
from slack_client import client
from config import TIMEZONE, SYSTEM_ISSUES_CHANNEL

scheduler = BackgroundScheduler(timezone=pytz.timezone(TIMEZONE))

def check_overdue_tickets():
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        seven_days_ago = datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=7)
        cur.execute("SELECT ticket_id, assigned_to FROM tickets WHERE status IN ('Open', 'In Progress') AND created_at < %s", (seven_days_ago,))
        overdue_tickets = cur.fetchall()
        for ticket_id, assignee_id in overdue_tickets:
            if assignee_id and assignee_id != 'Unassigned':
                client.chat_postMessage(channel=assignee_id, text=f"⏰ Reminder: Ticket T{ticket_id} is overdue. Please review.")
    finally:
        db_pool.putconn(conn)

def check_stale_tickets():
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        three_days_ago = datetime.now(pytz.timezone(TIMEZONE)) - timedelta(days=3)
        cur.execute(
            "SELECT ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, updated_at "
            "FROM tickets WHERE status IN ('Open', 'In Progress') AND updated_at < %s",
            (three_days_ago,)
        )
        stale_tickets = cur.fetchall()
        if stale_tickets:
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "⚠️ Stale Tickets Alert", "emoji": True}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "The following tickets have had no updates for 3+ days:"}}
            ]
            for ticket in stale_tickets:
                ticket_id, created_by, campaign, issue_type, priority, status, assigned_to, updated_at = ticket
                days_stale = (datetime.now(pytz.timezone(TIMEZONE)) - updated_at).days
                blocks.extend([
                    {"type": "divider"},
                    {"type": "section", "text": {"type": "mrkdwn",
                                                  "text": f"*T{ticket_id:03d}* | {priority} Priority | {status} | {days_stale} days stale\n"
                                                          f">*Issue:* {issue_type}\n"
                                                          f">*Assigned to:* {f'<@{assigned_to}>' if assigned_to != 'Unassigned' else 'Unassigned'}\n"
                                                          f">*Campaign:* {campaign}"}}
                ])
            client.chat_postMessage(channel=SYSTEM_ISSUES_CHANNEL, blocks=blocks)
    finally:
        db_pool.putconn(conn)

scheduler.add_job(check_overdue_tickets, "interval", hours=24)
scheduler.add_job(check_stale_tickets, "interval", hours=24, start_date=datetime.now() + timedelta(minutes=30))