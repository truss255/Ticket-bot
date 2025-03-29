from flask import Blueprint, jsonify, request
from myapp.services.ticket_service import fetch_messages, create_ticket
import logging

logger = logging.getLogger(__name__)
system_blueprint = Blueprint("system", __name__)

@system_blueprint.route("/example", methods=["GET"])
def example_route():
    data = fetch_messages()
    new_ticket = {
        "ticket_id": "T1001",
        "issue": "System Crash",
        "status": "Open",
        "campaign": "Maui Wildfires",
        "salesforce_link": "https://example.com"
    }
    create_ticket(new_ticket)
    return "Example route with Slack storage!"
