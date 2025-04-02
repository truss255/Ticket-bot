from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from config import SLACK_BOT_TOKEN

client = WebClient(token=SLACK_BOT_TOKEN)

def send_dm(user_id, text, blocks=None):
    try:
        dm_response = client.conversations_open(users=user_id)
        channel_id = dm_response["channel"]["id"]
        message_response = client.chat_postMessage(
            channel=channel_id,
            text=text,
            blocks=blocks
        )
        return message_response
    except SlackApiError as e:
        raise