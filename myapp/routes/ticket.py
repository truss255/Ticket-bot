from flask import Blueprint, jsonify, request
from myapp.services.ticket_service import (
    fetch_all_tickets,
    update_ticket_status,
    is_system_user,
    create_ticket
)
import logging

logger = logging.getLogger(__name__)
ticket_blueprint = Blueprint('ticket', __name__)

@ticket_blueprint.route('/new-ticket', methods=['POST'])
def new_ticket():
    try:
        logger.info(f"Incoming Slack request: {request.form}")
        data = request.form
        if not data or 'text' not in data:
            return jsonify({"error": "Invalid payload"}), 400
        
        logger.info(f"New ticket created with text: {data['text']}")
        return jsonify({"message": "Request received"}), 200
    except Exception as e:
        logger.error(f"Error creating ticket: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@ticket_blueprint.route('/agent-tickets', methods=['GET'])
def agent_tickets():
    try:
        tickets = fetch_all_tickets()
        return jsonify({"tickets": tickets}), 200
    except Exception as e:
        logger.error(f"Error fetching agent tickets: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@ticket_blueprint.route('/system-tickets', methods=['GET'])
def system_tickets():
    try:
        tickets = fetch_all_tickets()
        filtered_tickets = [t for t in tickets if t.get('is_system_ticket', False)]
        return jsonify({"tickets": filtered_tickets}), 200
    except Exception as e:
        logger.error(f"Error fetching system tickets: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@ticket_blueprint.route('/ticket-summary', methods=['GET'])
def ticket_summary():
    try:
        # Add your ticket summary logic here
        return jsonify({"message": "Ticket summary endpoint"}), 200
    except Exception as e:
        logger.error(f"Error in ticket summary: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@ticket_blueprint.route('/slack/events', methods=['POST'])
def slack_events():
    try:
        # Get the JSON data from the request
        data = request.get_json()
        
        # Log the incoming data
        logger.info(f"Received Slack event data: {data}")

        # Handle URL verification challenge
        if data and data.get('type') == 'url_verification':
            challenge = data.get('challenge')
            logger.info(f"Responding to challenge: {challenge}")
            return jsonify({
                "challenge": challenge
            })

        # Handle other events
        if data and data.get('type') == 'event_callback':
            event = data.get('event', {})
            logger.info(f"Processing event: {event}")
            # Add your event handling logic here
            
        return jsonify({"status": "ok"})

    except Exception as e:
        logger.error(f"Error in slack_events: {str(e)}")
        return jsonify({"error": str(e)}), 500



