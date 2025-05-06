from flask import Flask
import websocket
import json
import time
import threading
import logging
import requests
import os
import uuid

# Initialize Flask app
app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Health check route for Render and UptimeRobot
@app.route('/')
def health_check():
    return {"status": "Bot is running", "websocket_active": running}, 200

# Gateway URL
GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"

# Globals
heartbeat_interval = None
last_sequence = None
session_id = None
user_id = None
running = True
reconnect_delay = 1  # Initial reconnect delay in seconds

# Load Discord token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    logger.error("DISCORD_TOKEN environment variable is not set")
    raise ValueError("DISCORD_TOKEN environment variable is not set")

# Send a plain text message with rate-limit handling
def send_discord_message(channel_id, token, message):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }
    payload = {"content": message}
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            logger.info("Message sent successfully")
        elif response.status_code == 429:  # Rate limit
            retry_after = response.json().get("retry_after", 1)
            logger.warning(f"Rate limited. Retrying after {retry_after}s")
            time.sleep(retry_after)
            return send_discord_message(channel_id, token, message)  # Retry
        else:
            logger.error(f"Failed to send message: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error sending message: {e}")

# Send a file to a Discord channel with rate-limit handling
def send_music_file(channel_id, token, filename, filepath):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    headers = {"Authorization": token}
    try:
        with open(filepath, 'rb') as f:
            files = {"files[0]": (filename, f)}
            payload = {
                "content": "",
                "nonce": str(uuid.uuid4()),  # Unique nonce
                "tts": False
            }
            response = requests.post(url, headers=headers, data=payload, files=files)
            if response.status_code == 200:
                logger.info(f"File sent successfully: {response.json()['id']}")
            elif response.status_code == 429:
                retry_after = response.json().get("retry_after", 1)
                logger.warning(f"Rate limited. Retrying after {retry_after}s")
                time.sleep(retry_after)
                return send_music_file(channel_id, token, filename, filepath)
            else:
                logger.error(f"Failed to send file: {response.status_code} - {response.text}")
    except FileNotFoundError:
        logger.error(f"File not found: {filepath}")
    except Exception as e:
        logger.error(f"Error sending file: {e}")

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
                logger.info(f"User ready! Username: {user.get('username')}#{user.get('discriminator')}, Session ID: {session_id}")

            elif event_name == "MESSAGE_CREATE":
                author = event_data.get("author", {})
                content = event_data.get("content")
                channel_id = event_data.get("channel_id")
                author_id = author.get("id")
                username = f"{author.get('username')}#{author.get('discriminator')}"

                channel_type = event_data.get("type", 1)  # Default to DM (type 1)
                if channel_type == 1 and author_id != user_id:  # DM channel
                    logger.info(f"[COMMANDS] DM from {username}: {content}")
                    if content.startswith("!help"):
                        send_discord_message(channel_id, DISCORD_TOKEN, (
                            "Hey there! Here are the commands you can use:\n\n"
                            "!everick - Get the invite link to my Discord server.\n"
                            "!instagram - Check out my Instagram page.\n"
                            "!linktree - A link to all my platforms.\n"
                            "!help - Displays this list of commands.\n\n"
                            "Thanks for reaching out!\n"
                            "Use !lunaraids to get your own bot! Made by Everick!"
                        ))
                    elif content.startswith("!everick"):
                        send_discord_message(channel_id, DISCORD_TOKEN, "discord.gg/everick")
                    elif content.startswith("!instagram"):
                        send_discord_message(channel_id, DISCORD_TOKEN, "https://www.instagram.com/thisiseverick/")
                    elif content.startswith("!linktree"):
                        send_discord_message(channel_id, DISCORD_TOKEN, "https://linktr.ee/everick")
                    elif content.startswith("!lunaraids"):
                        send_discord_message(channel_id, DISCORD_TOKEN, "https://lunaraids.vip/")
                else:
                    logger.debug("Ignored message from self or non-DM channel")

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
    global running, reconnect_delay
    logger.info(f"WebSocket closed with code {close_status_code}, message: {close_msg}")
    running = False
    # Trigger reconnection
    logger.info(f"Attempting to reconnect in {reconnect_delay}s...")
    time.sleep(reconnect_delay)
    reconnect_delay = min(reconnect_delay * 2, 30)  # Exponential backoff, max 30s

def on_open(ws):
    global reconnect_delay
    logger.info("WebSocket connection opened")
    reconnect_delay = 1  # Reset reconnect delay on successful connection

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
                "token": DISCORD_TOKEN,
                "intents": 1 << 12,  # DIRECT_MESSAGES intent
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

def run_websocket():
    global running
    while True:
        running = True
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
        except Exception as e:
            logger.error(f"WebSocket run error: {e}")
        if not running:
            continue  # Reconnect if closed
        break  # Exit if manually stopped

def main():
    # Start WebSocket in a separate thread
    bot_thread = threading.Thread(target=run_websocket, daemon=True)
    bot_thread.start()

    # Run Flask app (for local testing; Gunicorn handles production)
    port = int(os.getenv("PORT", 8000))  # Use Render's PORT or fallback to 8000
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    main()
