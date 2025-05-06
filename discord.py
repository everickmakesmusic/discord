import websocket
import json
import time
import threading
import logging
import getpass
import requests

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Gateway URL
GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"

# Globals
heartbeat_interval = None
last_sequence = None
session_id = None
user_id = None
running = True

# Secure token input
USER_TOKEN = getpass.getpass("Enter your Discord user token: ")

# Send a plain text message
def send_discord_message(channel_id, token, message):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }
    payload = {
        "content": message
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print("Message sent successfully!")
    else:
        print(f"Failed to send message. Status code: {response.status_code}, Response: {response.text}")

# Send a file to a Discord channel
def send_music_file(channel_id, token, filename, filepath):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {
        "Authorization": token
    }
    with open(filepath, 'rb') as f:
        files = {
            "files[0]": (filename, f)
        }
        payload = {
            "content": "",
            "nonce": "1369160438163439616",
            "tts": False
        }
        response = requests.post(url, headers=headers, data=payload, files=files)
        if response.status_code == 200:
            print(response.json()['id'])
        else:
            print(f"Failed to send file: {response.status_code} - {response.text}")

# WebSocket message handler
def on_message(ws, message):
    global heartbeat_interval, last_sequence, session_id, user_id
    try:
        data = json.loads(message)
        op_code = data.get("op")
        event_data = data.get("d")
        sequence = data.get("s")

        if sequence is not None:
            last_sequence = sequence

        if op_code == 0:  # Dispatch
            event_name = data.get("t")
            logger.info(f"Received event: {event_name}")

            if event_name == "READY":
                session_id = event_data.get("session_id")
                user = event_data.get("user", {})
                user_id = user.get("id")
                logger.info(f"User is ready! Username: {user.get('username')}#{user.get('discriminator')}, Session ID: {session_id}")

            elif event_name == "MESSAGE_CREATE":
                author = event_data.get("author", {})
                content = event_data.get("content")
                channel_id = event_data.get("channel_id")
                author_id = author.get("id")
                username = f"{author.get('username')}#{author.get('discriminator')}"

                # Prevent key error by using .get with a fallback
                channel_type = event_data.get("channel_type", 0)

                if channel_type == 1 and author_id != user_id:  # DM channel
                    print(f"\033[92m[COMMANDS] Somebody messaged you: {username} said \"{content}\"\033[0m")
                    if content.startswith("!help"):
                        send_discord_message(channel_id, USER_TOKEN, "Hey there! Here are the commands you can use:\n\n!everick - Get the invite link to my Discord server.\n!instagram - Check out my Instagram page for updates and content.\n!linktree - A link to all my platforms in one place.\n!help - Displays this list of commands.\n\nThanks for reaching out!\nᴜsᴇ !ʟᴜɴᴀʀᴀɪᴅs ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ! ᴍᴀᴅᴇ ʙʏ ᴇᴠᴇʀɪᴄᴋ!")
                    elif content.startswith("!everick"):
                        send_discord_message(channel_id, USER_TOKEN, "discord.gg/everick")
                    elif content.startswith("!instagram"):
                        send_discord_message(channel_id, USER_TOKEN, "https://www.instagram.com/thisiseverick/")
                    elif content.startswith("!linktree"):
                        send_discord_message(channel_id, USER_TOKEN, "https://linktr.ee/everick")
                    elif content.startswith("!lunaraids"):
                        send_discord_message(channel_id, USER_TOKEN, "https://lunaraids.vip/")
                else:
                    logger.debug(f"Ignored message from self or non-DM channel")

        elif op_code == 10:  # Hello
            heartbeat_interval = event_data.get("heartbeat_interval") / 1000.0
            logger.info(f"Received Hello, heartbeat interval: {heartbeat_interval}s")
            threading.Thread(target=send_heartbeat, args=(ws,), daemon=True).start()
            send_identify(ws)

        elif op_code == 11:  # Heartbeat ACK
            logger.debug("Heartbeat ACK received")

        else:
            logger.warning(f"Unhandled OP code: {op_code}, data: {data}")

    except json.JSONDecodeError:
        logger.error("Failed to parse message as JSON")
    except Exception as e:
        logger.error(f"Error in on_message: {e}")

def on_error(ws, error):
    logger.error(f"WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    global running
    logger.info(f"WebSocket closed with code {close_status_code}, message: {close_msg}")
    running = False

def on_open(ws):
    logger.info("WebSocket connection opened")

def send_heartbeat(ws):
    while running and heartbeat_interval:
        try:
            payload = {"op": 1, "d": last_sequence}
            ws.send(json.dumps(payload))
            logger.debug("Sent heartbeat")
            time.sleep(heartbeat_interval)
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            break

def send_identify(ws):
    try:
        payload = {
            "op": 2,
            "d": {
                "token": USER_TOKEN,
                "properties": {
                    "$os": "linux",
                    "$browser": "custom",
                    "$device": "custom"
                },
                "presence": {
                    "status": "online",
                    "since": 0,
                    "activities": [],
                    "afk": False
                }
            }
        }
        ws.send(json.dumps(payload))
        logger.info("Sent Identify payload")
    except Exception as e:
        logger.error(f"Error sending Identify: {e}")

def main():
    websocket.enableTrace(False)
    ws = websocket.WebSocketApp(
        GATEWAY_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    try:
        ws.run_forever(ping_interval=30, ping_timeout=10)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        global running
        running = False
        ws.close()

if __name__ == "__main__":
    main()
