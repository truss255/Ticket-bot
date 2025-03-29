# Flask Application

This is a Flask application designed to handle ticket management and integrate with Slack.

## Project Structure

```
flask-app
├── app.py                # Main application file for the Flask app
├── requirements.txt      # Python dependencies required for the project
├── runtime.txt           # Specifies the Python version for deployment
├── Procfile              # Commands executed by the application on Railway
├── Dockerfile            # Instructions for building a Docker image
├── .env                  # Environment variables for the application
└── README.md             # Documentation for the project
```

## Setup Instructions

1. **Clone the repository:**
   ```
   git clone <repository-url>
   cd flask-app
   ```

2. **Create a virtual environment:**
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```

4. **Set up environment variables:**
   Create a `.env` file in the root directory and add your environment variables.

5. **Run the application:**
   ```
   python app.py
   ```

## Usage

- The application exposes several API endpoints for ticket management:
  - `POST /api/tickets/new-ticket`: Create a new ticket.
  - `POST /api/tickets/agent-tickets`: Retrieve agent tickets.
  - `POST /api/tickets/system-tickets`: Retrieve system tickets.
  - `POST /api/tickets/ticket-summary`: Get a summary of tickets.
  - `POST /api/tickets/slack/events`: Handle Slack events.

## Deployment

This application can be deployed on Railway. Ensure that the `Procfile` and `runtime.txt` are correctly configured for the deployment environment.

## License

This project is licensed under the MIT License.