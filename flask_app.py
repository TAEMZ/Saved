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

# --- Simplified Architecture: Each webhook gets its own thread ---
# No background event loop needed - each request gets its own asyncio.run()
print("[Startup] Flask app ready - using per-request event loops")

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
        print(f"[Webhook] Got JSON for update")
        
        # Spawn a dedicated thread for this update with its own bot_app and event loop
        def _run_update(update_json):
            async def _process():
                print(f"[Bot] Processing update in dedicated thread")
                import time
                start = time.time()
                try:
                    print(f"[Bot] Creating fresh bot_app for this update...")
                    local_app = get_bot_app()
                    
                    print(f"[Bot] Initializing bot_app...")
                    await local_app.initialize()
                    
                    # Deserialize the update using THIS bot instance
                    print(f"[Bot] Deserializing update...")
                    update = Update.de_json(update_json, local_app.bot)
                    update_id = update.update_id if update else "unknown"
                    update_type = "message" if update.message else ("callback_query" if update.callback_query else "other")
                    print(f"[Bot] Received update {update_id}, type: {update_type}")
                    if update.message:
                        print(f"[Bot] Message text: {repr(update.message.text)}, entities: {update.message.entities}")
                    
                    print(f"[Bot] Processing update {update_id}...")
                    await local_app.process_update(update)
                    
                    print(f"[Bot] Shutting down bot_app...")
                    await local_app.shutdown()
                    
                    elapsed = time.time() - start
                    print(f"[Bot] Update {update_id} completed successfully in {elapsed:.2f}s")
                except Exception as e:
                    elapsed = time.time() - start
                    print(f"[Bot] FAILED to process update after {elapsed:.2f}s: {type(e).__name__}: {e}")
                    traceback.print_exc()
            
            asyncio.run(_process())
        
        print(f"[Webhook] Spawning dedicated thread for update...")
        t = threading.Thread(target=_run_update, args=(update_json,), daemon=True)
        t.start()
        
        print(f"[Webhook] Returning 200 OK")
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

    async def _register():
        print(f"[SetWebhook] Creating bot_app...")
        local_app = get_bot_app()
        
        print(f"[SetWebhook] Initializing bot_app...")
        await local_app.initialize()
        
        try:
            print(f"[SetWebhook] Setting webhook to {webhook_target_url}...")
            result = await local_app.bot.set_webhook(
                url=webhook_target_url,
                secret_token=config.WEBHOOK_SECRET_TOKEN
            )
            print(f"[SetWebhook] Webhook set successfully: {result}")
            return result
        finally:
            print(f"[SetWebhook] Shutting down bot_app...")
            await local_app.shutdown()

    try:
        # Run in a thread with its own event loop
        def _run():
            return asyncio.run(_register())
        
        result = _run()
        return (
            f"✅ Webhook registered for: {webhook_target_url}",
            200
        )
    except Exception as e:
        print(f"[SetWebhook ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        return (
            f"❌ Failed to set webhook: {type(e).__name__}: {e}",
            500
        )

@app.route('/check_reminders', methods=['GET'])
def check_reminders():
    """Secure endpoint triggered by a cron job to check and send due reminders."""
    token = request.args.get("token")
    if token != config.WEBHOOK_SECRET_TOKEN:
        return "Unauthorized: Invalid Secret Query Parameter", 403
    
    async def run_check():
        print(f"[CheckReminders] Creating bot_app...")
        local_app = get_bot_app()
        
        print(f"[CheckReminders] Initializing bot_app...")
        await local_app.initialize()
        
        try:
            print(f"[CheckReminders] Checking and sending due reminders...")
            count = await check_and_send_due_reminders(local_app.bot)
            print(f"[CheckReminders] Reminders sent: {count}")
            return count
        finally:
            print(f"[CheckReminders] Shutting down bot_app...")
            await local_app.shutdown()
        
    try:
        # Run in the current thread with asyncio.run
        count = asyncio.run(run_check())
        return jsonify({
            "status": "success",
            "message": f"Processed successfully. Reminders sent: {count}",
            "reminders_sent": count
        }), 200
    except Exception as e:
        print(f"Error running cron check: {e}")
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

if __name__ == "__main__":
    # Local debugging
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
