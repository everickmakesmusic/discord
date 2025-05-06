from bot import app, main
import threading

# Start the WebSocket bot in a background thread
bot_thread = threading.Thread(target=main, daemon=True)
bot_thread.start()

# WSGI entry point for Gunicorn
application = app
