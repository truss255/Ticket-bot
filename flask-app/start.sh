#!/bin/bash

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Explicitly install gunicorn
echo "Ensuring Gunicorn is installed..."
pip install gunicorn==20.1.0

# Install the package in development mode
echo "Installing package in development mode..."
pip install -e .

# Make sure the current directory is in the Python path
echo "Setting up Python path..."
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Check for syntax errors in app.py
echo "Checking for syntax errors in app.py..."
python -c "import py_compile; py_compile.compile('app.py')"
if [ $? -ne 0 ]; then
    echo "Syntax error detected in app.py. Exiting."
    exit 1
fi

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
    # Use the full path to gunicorn with detailed error logging
    $(which gunicorn) app:app --bind 0.0.0.0:$PORT --log-level debug --capture-output --error-logfile - --access-logfile -
fi
