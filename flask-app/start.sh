#!/bin/bash

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Explicitly install gunicorn
echo "Ensuring Gunicorn is installed..."
pip install gunicorn==23.0.0

# Set default port if not provided
PORT=${PORT:-8080}

# Start the application
echo "Starting application..."

# Check if we should run in worker mode
if [ "$PROCESS_TYPE" = "worker" ]; then
    echo "Starting in worker mode..."
    python app.py
else
    echo "Starting in web mode with Gunicorn..."
    # Use the full path to gunicorn
    $(which gunicorn) app:app --bind 0.0.0.0:$PORT --log-level info
fi
