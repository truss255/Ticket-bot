import requests
import json

BASE_URL = "http://localhost:8080"  # Change port if different

def test_health():
    response = requests.get(f"{BASE_URL}/health")
    print(f"Health Check: {response.status_code}")
    print(response.json())

def test_tickets_endpoints():
    # Test getting all agent tickets
    response = requests.get(f"{BASE_URL}/api/tickets/agent-tickets")
    print(f"\nAgent Tickets: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

    # Test getting system tickets
    response = requests.get(f"{BASE_URL}/api/tickets/system-tickets")
    print(f"\nSystem Tickets: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

def test_create_ticket():
    # Test creating a new ticket
    test_ticket = {
        "text": "Test ticket creation",
        "user": "test_user"
    }
    response = requests.post(f"{BASE_URL}/api/tickets/new-ticket", data=test_ticket)
    print(f"\nCreate Ticket: {response.status_code}")
    print(response.json())

if __name__ == "__main__":
    test_health()
    test_tickets_endpoints()
    test_create_ticket()