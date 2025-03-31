# Ticket Management Slack Bot

This Flask app is a Slack bot designed to manage tickets within a Slack workspace. It allows users to submit new tickets via a Slack modal, assign tickets to system users, update ticket statuses, and post ticket details to a designated Slack channel. The app uses a PostgreSQL database to store ticket information and comments.

---

## Table of Contents

- [Features](#features)
- [Setup Instructions](#setup-instructions)
  - [Environment Variables](#environment-variables)
  - [Database Setup](#database-setup)
- [Usage](#usage)
  - [Slack Commands](#slack-commands)
  - [Interacting with Ticket Messages](#interacting-with-ticket-messages)
- [Scheduled Tasks](#scheduled-tasks)
- [Deployment on Railway](#deployment-on-railway)
- [License](#license)

---

## Features

- **Ticket Submission**: Users can submit new tickets via the `/new-ticket` Slack command.
- **Ticket Assignment**: System users can assign tickets to themselves or others.
- **Status Updates**: Tickets can be updated to "In Progress," "Resolved," "Closed," or "Reopened."
- **Slack Integration**: Ticket details are posted and updated in a designated Slack channel.
- **Database Storage**: Tickets and comments are stored in a PostgreSQL database.
- **Scheduled Tasks**: Automated tasks for weekly summaries, overdue ticket reminders, and pinning high-priority unassigned tickets.

---

## Setup Instructions

### Environment Variables

The following environment variables must be set for the app to function correctly:

- **`SLACK_BOT_TOKEN`**: The token for your Slack bot. Obtain this from your Slack app's settings.
- **`DATABASE_URL`**: The connection string for your PostgreSQL database. On Railway, this will be provided when you provision a PostgreSQL database.
- **`ADMIN_CHANNEL`**: The Slack channel where error notifications will be posted (e.g., `#admin-notifications`).
- **`TIMEZONE`**: Your preferred timezone (e.g., `America/New_York`).
- **`SYSTEM_USERS`**: A comma-separated list of Slack user IDs who have system privileges (e.g., `U12345678,U87654321`).

On Railway, set these variables in your project's environment settings.

### Database Setup

The app includes an `init_db()` function that creates the necessary database tables. After setting up the database connection, this function is called automatically to initialize the schema.

---

## Usage

### Slack Commands

- **`/new-ticket`**: Opens a modal for submitting a new ticket. Users can select a campaign, issue type, priority, and provide details.
- **`/agent-tickets`**: Displays a modal showing the user's submitted tickets, including their status and details.

### Interacting with Ticket Messages

System users can interact with ticket messages in the Slack channel using the following buttons:

- **🖐 Assign to Me**: Assigns the ticket to the user and updates the status to "In Progress."
- **🔁 Reassign**: Opens a modal to select a new assignee.
- **❌ Close**: Updates the ticket status to "Closed."
- **🟢 Resolve**: Updates the ticket status to "Resolved."
- **🔄 Reopen**: Updates the ticket status to "Open."

---

## Scheduled Tasks

The app includes the following scheduled tasks, managed by APScheduler:

- **Weekly Summary**: Posts a summary of ticket statuses to the Slack channel every Monday at 9:00 AM.
- **Overdue Ticket Check**: Sends reminders to assignees of tickets that have been open or in progress for more than 7 days.
- **High-Priority Pinning**: Pins a message in the Slack channel listing high-priority unassigned tickets, updated every hour.

---

## Deployment on Railway

To deploy this app on Railway:

1. **Create a Railway Project**:
   - Link your GitHub repository to a new Railway project.

2. **Provision a PostgreSQL Database**:
   - Add a PostgreSQL database to your Railway project.
   - Copy the provided `DATABASE_URL` for use in environment variables.

3. **Set Environment Variables**:
   - In your Railway project settings, add the following variables:
     - `SLACK_BOT_TOKEN`
     - `DATABASE_URL` (from the provisioned database)
     - `ADMIN_CHANNEL`
     - `TIMEZONE`
     - `SYSTEM_USERS`

4. **Deploy the App**:
   - Railway will automatically detect the Flask app and deploy it.
   - Ensure your `requirements.txt` is up-to-date with all dependencies (e.g., `flask`, `slack_sdk`, `psycopg2-binary`, `apscheduler`, `pytz`).

5. **Verify Deployment**:
   - Check the Railway logs to ensure the app starts correctly and the database schema is initialized.

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.