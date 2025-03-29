from flask import Blueprint, jsonify, request
from myapp.services.ticket_service import (
    fetch_all_tickets,
    fetch_agent_tickets,
    fetch_system_tickets,
    create_ticket,
    get_ticket_summary,
    is_system_user
)
from myapp.utils.slack_verify import verify_slack_signature
import logging

logger = logging.getLogger(__name__)
ticket_blueprint = Blueprint('ticket', __name__)

@ticket_blueprint.route('/new-ticket', methods=['POST'])
@verify_slack_signature
def new_ticket():
    try:
        data = request.form
        if not data or 'text' not in data:
            return jsonify({
                "response_type": "ephemeral",
                "text": "Please provide ticket details"
            }), 400

        ticket = create_ticket({
            "text": data['text'],
            "user_id": data.get('user_id'),
            "user_name": data.get('user_name')
        })
        
        return jsonify({
            "response_type": "in_channel",
            "text": f"✅ Ticket created successfully!\nID: {ticket['ticket_id']}"
        })
    except Exception as e:
        logger.error(f"Error creating ticket: {str(e)}")
        return jsonify({
            "response_type": "ephemeral",
            "text": "Failed to create ticket. Please try again."
        }), 500

@ticket_blueprint.route('/agent-tickets', methods=['POST'])
@verify_slack_signature
def agent_tickets():
    try:
        user_id = request.form.get('user_id')
        tickets = fetch_agent_tickets(user_id)
        
        return jsonify({
            "response_type": "ephemeral",
            "text": format_tickets_response(tickets)
        })
    except Exception as e:
        logger.error(f"Error fetching agent tickets: {str(e)}")
        return jsonify({
            "response_type": "ephemeral",
            "text": "Failed to fetch tickets. Please try again."
        }), 500

@ticket_blueprint.route('/system-tickets', methods=['POST'])
@verify_slack_signature
def system_tickets():
    try:
        user_id = request.form.get('user_id')
        if not is_system_user(user_id):
            return jsonify({
                "response_type": "ephemeral",
                "text": "⚠️ Access denied. This command is for system users only."
            }), 403
            
        tickets = fetch_system_tickets()
        return jsonify({
            "response_type": "ephemeral",
            "text": format_tickets_response(tickets)
        })
    except Exception as e:
        logger.error(f"Error fetching system tickets: {str(e)}")
        return jsonify({
            "response_type": "ephemeral",
            "text": "Failed to fetch tickets. Please try again."
        }), 500

@ticket_blueprint.route('/ticket-summary', methods=['POST'])
@verify_slack_signature
def ticket_summary():
    try:
        user_id = request.form.get('user_id')
        if not is_system_user(user_id):
            return jsonify({
                "response_type": "ephemeral",
                "text": "⚠️ Access denied. This command is for system users only."
            }), 403
            
        summary = get_ticket_summary()
        return jsonify({
            "response_type": "ephemeral",
            "text": format_summary_response(summary)
        })
    except Exception as e:
        logger.error(f"Error getting ticket summary: {str(e)}")
        return jsonify({
            "response_type": "ephemeral",
            "text": "Failed to get summary. Please try again."
        }), 500

def format_tickets_response(tickets):
    if not tickets:
        return "No tickets found."
        
    response = "📋 *Tickets*\n\n"
    for ticket in tickets:
        response += (
            f"🎫 *ID:* {ticket['ticket_id']}\n"
            f"📝 *Issue:* {ticket['issue']}\n"
            f"🔄 *Status:* {ticket['status']}\n"
            f"-------------------\n"
        )
    return response

def format_summary_response(summary):
    return (
        "📊 *Ticket Summary*\n\n"
        f"📫 Open: {summary['open']}\n"
        f"✅ Closed: {summary['closed']}\n"
        f"⚡ High Priority: {summary['high_priority']}\n"
        f"⏳ Average Resolution Time: {summary['avg_resolution_time']}\n"
    )




