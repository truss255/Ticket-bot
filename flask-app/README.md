# Ticket Bot

A Flask-based ticket management system with Slack integration, designed to handle ticket creation, retrieval, and summaries.

## Features

- **New Ticket Creation**: Create new tickets via the `/api/tickets/new-ticket` endpoint.
- **Agent Tickets**: Retrieve tickets assigned to agents via the `/api/tickets/agent-tickets` endpoint.
- **System Tickets**: Retrieve system-related tickets via the `/api/tickets/system-tickets` endpoint.
- **Ticket Summary**: Get a summary of tickets via the `/api/tickets/ticket-summary` endpoint.
- **Slack Events**: Handle Slack events via the `/api/tickets/slack/events` endpoint.

## Deployment

This application is deployed on [Railway](https://railway.app/).

### Environment Variables

The following environment variables are required for the application to run:

- `SLACK_BOT_TOKEN`: Token for Slack bot integration.
- `DATABASE_URL`: URL for the database connection.
- `ADMIN_CHANNEL`: Slack channel for admin notifications.
- `TIMEZONE`: Timezone for ticket processing.

### Running the Application

The application is configured to run on Railway. No additional setup is required if the environment variables are configured in Railway's dashboard.

## Endpoints

| Endpoint                          | Method | Description                     |
|-----------------------------------|--------|---------------------------------|
| `/api/tickets/new-ticket`         | POST   | Create a new ticket.           |
| `/api/tickets/agent-tickets`      | POST   | Retrieve agent tickets.        |
| `/api/tickets/system-tickets`     | POST   | Retrieve system tickets.       |
| `/api/tickets/ticket-summary`     | POST   | Get a summary of tickets.      |
| `/api/tickets/slack/events`       | POST   | Handle Slack events.           |

## Requirements

- Python 3.9 or higher
- Flask
- Any additional dependencies listed in `requirements.txt`

## Installation (For Local Development)

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/Ticket-bot.git
   cd Ticket-bot/flask-app