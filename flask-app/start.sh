#!/bin/bash

# Install dependencies
pip install -r requirements.txt

# Check if gunicorn is installed
if ! command -v gunicorn &> /dev/null; then
    echo "Gunicorn not found, installing..."
    pip install gunicorn
fi

# Start the application
if [ "$RAILWAY_ENVIRONMENT" = "production" ]; then
    echo "Starting in production mode with Gunicorn..."
    gunicorn app:app --bind 0.0.0.0:$PORT
else
    echo "Starting in development mode..."
    python app.py
fi
