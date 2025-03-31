# Ticket Bot

A Slack-integrated Flask application for managing support tickets, designed to streamline issue reporting and resolution for agents and system users. Features include ticket submission with file uploads, ticket management, CSV export, and automated notifications for overdue and stale tickets.

## Features
- **Ticket Submission**: Agents can submit tickets via a Slack modal with details like campaign, issue type, priority, and optional file attachments.
- **Agent View**: Agents can view their submitted tickets with filtering options (`/agent-tickets`).
- **System User View**: System users can manage all tickets, assign/reassign them, and export to CSV (`/system-tickets`).
- **Export Functionality**: System users can export tickets to CSV with customizable filters (status, priority, date range).
- **Scheduled Tasks**: Automated checks for overdue (7+ days) and stale (3+ days without updates) tickets, with notifications sent via Slack.
- **Slack Integration**: Fully integrated with Slack for modals, messages, and file uploads.

## Prerequisites
- **Python**: Version 3.8 or higher.
- **PostgreSQL**: A running PostgreSQL database for ticket storage.
- **Slack App**: A Slack app with a bot token and the following scopes:
  - `chat:write`
  - `files:write`
  - `users:read`
  - Additional scopes may be needed for specific features (e.g., `channels:read` for channel validation).
- **Git**: For version control and deployment (optional).

## Project Structure
your_project/
├── app.py              # Main Flask application
├── check_db_route.py   # Database check endpoint
├── ticket_templates.py # Slack block and modal templates
├── .env                # Environment variables (not tracked)
├── requirements.txt    # Python dependencies
├── Procfile            # Deployment process definitions
└── .gitignore          # Git ignore file

text

Collapse

Wrap

Copy

## Setup Instructions (Local Development)

1. **Clone the Repository** (if using Git):
   ```bash
   git clone <your-repo-url>
   cd your_project
Or manually create the directory and add the files.

Install Dependencies:
Ensure you have Python installed.
Install required packages:
bash

Collapse

Wrap

Copy
pip install -r requirements.txt
Configure Environment Variables:
Create a .env file in the project root:
text

Collapse

Wrap

Copy
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token-here
DATABASE_URL=postgresql://user:password@host:port/dbname
ADMIN_CHANNEL=#admin-notifications
TIMEZONE=America/New_York
SYSTEM_USERS=U12345678,U98765432
SLACK_CHANNEL_ID=C08JTKR1RPT
PORT=8080
Replace placeholders:
SLACK_BOT_TOKEN: Get from your Slack app’s "OAuth & Permissions" page.
DATABASE_URL: Your PostgreSQL connection string (e.g., postgresql://postgres:password@localhost:5432/tickets).
SYSTEM_USERS: Comma-separated Slack user IDs for system users.
SLACK_CHANNEL_ID: The ID of your #systems-issues channel (starts with C).
Set Up PostgreSQL:
Create a database matching your DATABASE_URL.
The app will initialize tables (tickets and comments) on first run.
Run the Application:
Start the Flask server:
bash

Collapse

Wrap

Copy
python app.py
The app will run on http://0.0.0.0:8080 (or your specified PORT).
Deployment Instructions (Railway)
Prepare for Deployment:
Ensure all files are in your project directory (see Project Structure).
Commit changes to Git:
bash

Collapse

Wrap

Copy
git init
git add .
git commit -m "Initial commit"
git remote add origin <your-github-repo-url>
git push origin main
Set Up Railway:
Log in to Railway.
Create a new project and link your GitHub repository.
Add a PostgreSQL service:
Go to "New" > "Database" > "PostgreSQL".
Copy the DATABASE_URL from the database settings.
Configure Environment Variables:
In your Railway project, go to "Variables" and add:
text

Collapse

Wrap

Copy
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token-here
DATABASE_URL=<from-railway-postgres>
ADMIN_CHANNEL=#admin-notifications
TIMEZONE=America/New_York
SYSTEM_USERS=U12345678,U98765432
SLACK_CHANNEL_ID=C08JTKR1RPT
PORT=8080
Deploy:
Railway will detect the Procfile and deploy two processes:
web: Runs the Flask app with Gunicorn for HTTP requests.
worker: Runs background tasks (APScheduler).
Monitor logs in the Railway dashboard to confirm deployment.
Usage
Submit a Ticket:
In Slack, run /new-ticket to open the submission modal.
Fill in details and submit. A confirmation modal will appear, and the ticket will post to #systems-issues.
View Your Tickets:
Run /agent-tickets to see your submitted tickets with filtering options.
Manage Tickets (System Users):
Run /system-tickets to view all tickets, assign/reassign, resolve, close, or export them.
Click "Export" to open the export modal, apply filters, and receive a CSV file in your DM.
Scheduled Notifications:
Overdue tickets (7+ days) notify assignees daily.
Stale tickets (3+ days without updates) notify the admin channel daily.
Files
app.py: Core Flask app with routes, Slack integration, and scheduled tasks.
check_db_route.py: Adds /api/check-db endpoint to verify database connectivity.
ticket_templates.py: Defines Slack block templates for ticket messages and modals (e.g., submission, confirmation, export).
.env: Stores sensitive environment variables (not tracked in Git).
requirements.txt: Lists Python dependencies:
text

Collapse

Wrap

Copy
flask==2.3.2
slack-sdk==3.21.3
psycopg2-binary==2.9.6
python-dotenv==1.0.0
apscheduler==3.10.1
requests==2.31.0
gunicorn==20.1.0
Procfile: Defines deployment processes for Railway:
text

Collapse

Wrap

Copy
web: gunicorn app:app
worker: python app.py
.gitignore: Excludes sensitive or temporary files:
text

Collapse

Wrap

Copy
.env
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
*.log
Troubleshooting
Slack Errors: Ensure the bot token has required scopes and is added to relevant channels.
Database Issues: Verify DATABASE_URL and PostgreSQL connectivity with /api/check-db.
Deployment Failures: Check Railway logs for errors (e.g., missing variables, dependency issues).
Contributing
Feel free to fork this repository, submit pull requests, or report issues.

License
MIT License

text

Collapse

Wrap

Copy

---

### Instructions
1. **Create the File**:
   - In VS Code, right-click in your project directory, select "New File," and name it `README.md`.
2. **Copy and Paste**:
   - Copy the entire content above (from `# Ticket Bot` to `MIT License`) and paste it into `README.md`.
3. **Customize**:
   - Replace `<your-repo-url>` with your actual GitHub repository URL if applicable.
   - Update any placeholders (e.g., Slack token, user IDs) with real examples or leave them as-is for documentation.
4. **Save**:
   - Save the file in your project directory.

---

### Notes
- **Purpose**: This `README.md` serves as both user documentation and developer setup instructions, making it easy to onboard others or remind yourself of the setup process.
- **Deployment Focus**: It assumes Railway as a potential deployment platform due to your script’s logging comment, but it’s flexible for other platforms.
- **Completeness**: Covers all aspects of your current project, including the export feature and scheduled tasks.

If you need adjustments (e.g., a different deployment platform, more detailed usage examples), let me know,