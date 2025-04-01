from setuptools import setup, find_packages

setup(
    name="ticket-bot",
    version="1.0.0",
    packages=find_packages(),
    py_modules=["app", "ticket_templates", "check_db_route"],
    install_requires=[
        "Flask==2.2.5",
        "slack_sdk==3.21.2",
        "psycopg2-binary==2.9.5",
        "APScheduler==3.9.1",
        "python-dotenv==1.0.0",
        "pytz==2022.7.1",
        "requests==2.28.2",
        "gunicorn==20.1.0",
    ],
)
