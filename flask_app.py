import sys
# Configure UTF-8 encoding for standard output/error to prevent UnicodeEncodeError on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

import asyncio
import threading
import os
from flask import Flask, request, jsonify
from telegram import Update
import config
from bot import get_bot_app, check_and_send_due_reminders

app = Flask(__name__)

# --- Persistent Event Loop in a Background Thread ---
# This solves the "Event loop is closed" error that occurs when creating/destroying
# loops per request. The bot's internal httpx client keeps connections alive, so
# they must all share the same long-lived loop.

_loop = asyncio.new_event_loop()

def _start_background_loop(loop):
    """Run the event loop forever in a background thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()

_thread = threading.Thread(target=_start_background_loop, args=(_loop,), daemon=True)
_thread.start()

def run_async(coro):
    """Run an async coroutine on the persistent background event loop and wait for the result."""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result()

# Initialize the bot app global instance
bot_app = get_bot_app()

# Initialize the Telegram Bot Application
# Only initialize() is needed for webhook mode. Do NOT call start() —
# that launches an update_fetcher polling task which conflicts with webhooks.
run_async(bot_app.initialize())

@app.route('/')
def home():
    return "Saved Messages Bot Backend is running 🚀"

@app.route('/webhook', methods=['POST'])
def webhook():
    """Receives updates from Telegram and feeds them to the bot handlers."""
    # Verify the secret header to ensure it's actually Telegram calling
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != config.WEBHOOK_SECRET_TOKEN:
        return "Unauthorized: Invalid Secret Token", 403
        
    try:
        update_json = request.get_json(force=True)
        update = Update.de_json(update_json, bot_app.bot)
        run_async(bot_app.process_update(update))
        return "OK", 200
    except Exception as e:
        print(f"Error processing webhook update: {e}")
        return "Internal Error", 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """A helper route to register the webhook url with Telegram."""
    if not config.WEBHOOK_URL:
        return (
            "Error: WEBHOOK_URL is not set. Please set the WEBHOOK_URL environment variable or "
            "add it to config.json (e.g. 'https://yourusername.pythonanywhere.com')."
        ), 400
        
    webhook_target_url = f"{config.WEBHOOK_URL}/webhook"
    
    async def register():
        return await bot_app.bot.set_webhook(
            url=webhook_target_url,
            secret_token=config.WEBHOOK_SECRET_TOKEN
        )
        
    try:
        success = run_async(register())
        if success:
            return f"✅ Webhook successfully configured to: {webhook_target_url}", 200
        else:
            return "❌ Telegram rejected webhook registration.", 500
    except Exception as e:
        return f"❌ Failed to set webhook: {str(e)}", 500

@app.route('/check_reminders', methods=['GET'])
def check_reminders():
    """Secure endpoint triggered by a cron job to check and send due reminders."""
    token = request.args.get("token")
    if token != config.WEBHOOK_SECRET_TOKEN:
        return "Unauthorized: Invalid Secret Query Parameter", 403
        
    async def run_check():
        return await check_and_send_due_reminders(bot_app.bot)
        
    try:
        count = run_async(run_check())
        return jsonify({
            "status": "success",
            "message": f"Processed successfully. Reminders sent: {count}",
            "reminders_sent": count
        }), 200
    except Exception as e:
        print(f"Error running cron check: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

if __name__ == "__main__":
    # Local debugging
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
