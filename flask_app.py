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
import traceback
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

def _log_background_exception(future):
    try:
        result = future.result()
        print(f"[Background task completed successfully] {result}")
    except Exception as exc:
        print(f"[Background task FAILED] {type(exc).__name__}: {exc}")
        traceback.print_exc()


def run_async(coro, wait=True, timeout=None):
    """Run an async coroutine on the persistent background event loop.

    If wait is True, block until the coroutine finishes or times out.
    If wait is False, schedule it in the background and return immediately.
    """
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    if wait:
        return future.result(timeout=timeout)
    future.add_done_callback(_log_background_exception)
    return future


async def _process_update_logged(update):
    """Wrapper around bot processing with logging."""
    try:
        print(f"[Bot] Processing update {update.update_id} starting...")
        await bot_app.process_update(update)
        print(f"[Bot] Processing update {update.update_id} completed")
    except Exception as e:
        print(f"[Bot] FAILED to process update {update.update_id}: {type(e).__name__}: {e}")
        traceback.print_exc()

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
        update_type = "message" if update.message else ("callback_query" if update.callback_query else "other")
        print(f"[Webhook] Received update {update.update_id}, type: {update_type}")
        run_async(bot_app.process_update(update), wait=True, timeout=30)
        print(f"[Webhook] Update {update.update_id} processed successfully")
        return "OK", 200
    except Exception as e:
        print(f"[Webhook ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        return "Internal Error", 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """A helper route to register the webhook url with Telegram."""
    if not config.WEBHOOK_URL:
        return (
            "Error: WEBHOOK_URL is not set. Please set the WEBHOOK_URL environment variable or "
            "add it to config.json (e.g. 'https://yourusername.pythonanywhere.com')."
        ), 400

    if not config.TELEGRAM_BOT_TOKEN:
        return (
            "Error: TELEGRAM_BOT_TOKEN is not configured. Please set it as an environment variable "
            "or in config.json."
        ), 500

    webhook_target_url = f"{config.WEBHOOK_URL.rstrip('/')}/webhook"

    async def register():
        return await bot_app.bot.set_webhook(
            url=webhook_target_url,
            secret_token=config.WEBHOOK_SECRET_TOKEN
        )

    try:
        run_async(register(), wait=False)
        return (
            f"✅ Webhook registration queued for: {webhook_target_url}",
            202
        )
    except Exception as e:
        traceback.print_exc()
        return (
            f"❌ Failed to queue webhook registration: {type(e).__name__}: {e}",
            500
        )

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
