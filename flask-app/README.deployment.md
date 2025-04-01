# Deployment Instructions

## Railway Deployment

This application is configured to deploy on Railway with both web and worker processes:

1. **Web Process**: Runs the Flask application using Gunicorn
2. **Worker Process**: Runs the scheduler for background tasks

### Configuration Files

- **Procfile**: Defines the web and worker processes
- **railway.json**: Configures Railway deployment settings
- **start.sh**: Script to install dependencies and start the application
- **requirements.txt**: Lists all Python dependencies
- **runtime.txt**: Specifies the Python version

### Environment Variables

Make sure the following environment variables are set in your Railway project:

- `DATABASE_URL`: PostgreSQL connection string
- `SLACK_BOT_TOKEN`: Slack bot token
- `SLACK_CHANNEL_ID`: ID of the Slack channel for ticket notifications
- `ADMIN_CHANNEL`: ID of the Slack channel for admin notifications
- `SYSTEM_USERS`: Comma-separated list of Slack user IDs with system access
- `TIMEZONE`: Timezone for date/time operations (default: America/New_York)

### Deployment Steps

1. Push your code to GitHub
2. Connect your GitHub repository to Railway
3. Set up the environment variables
4. Deploy the application

### Troubleshooting

If you encounter issues with Gunicorn not being found:

1. SSH into your Railway instance
2. Run `pip install gunicorn`
3. Restart the application

Or update the `start.sh` script to ensure Gunicorn is installed before starting the application.
