from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from config import SLACK_BOT_TOKEN

client = WebClient(token=SLACK_BOT_TOKEN)

def send_dm(user_id, text, blocks=None):
    try:
        # Send directly to the user ID (no need to open a conversation first)
        message_response = client.chat_postMessage(
            channel=user_id,
            text=text,
            blocks=blocks
        )
        return message_response
    except SlackApiError as e:
        print(f"Error sending DM: {e}")
        return None