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
_loop_started_at = None

def _start_background_loop(loop):
    """Run the event loop forever in a background thread."""
    global _loop_started_at
    asyncio.set_event_loop(loop)
    _loop_started_at = asyncio.get_event_loop()
    print(f"[EventLoop] Starting in thread {threading.current_thread().name}...")
    print(f"[EventLoop] Loop object: {loop}")
    try:
        print(f"[EventLoop] About to call run_forever()...")
        loop.run_forever()
        print(f"[EventLoop] run_forever() returned (loop was stopped)")
    except Exception as e:
        print(f"[EventLoop CRASHED] {type(e).__name__}: {e}")
        traceback.print_exc()
    except BaseException as e:
        print(f"[EventLoop FATAL] {type(e).__name__}: {e}")
        traceback.print_exc()

_thread = threading.Thread(target=_start_background_loop, args=(_loop,), daemon=True)
_thread.start()
print(f"[Startup] Background thread started: {_thread}")

# Give the thread time to start
import time
time.sleep(0.1)
print(f"[Startup] Loop started at: {_loop_started_at}, is_running: {_loop.is_running()}")

def _log_background_exception(future):
    try:
        result = future.result()
        print(f"[Background task completed successfully] {result}")
    except Exception as exc:
        print(f"[Background task FAILED] {type(exc).__name__}: {exc}")
        traceback.print_exc()


# --- Monitor thread to detect if event loop is deadlocked ---
_last_heartbeat_time = None

def _monitor_event_loop():
    """Monitor the event loop in a separate thread to detect deadlocks."""
    global _last_heartbeat_time
    import time
    while True:
        time.sleep(10)  # Check every 10 seconds
        now = time.time()
        if _last_heartbeat_time is None:
            print(f"[Monitor] WARNING: Heartbeat has never executed! Event loop may be deadlocked.")
        elif now - _last_heartbeat_time > 15:
            print(f"[Monitor] CRITICAL: Heartbeat stopped {now - _last_heartbeat_time:.1f}s ago! Event loop is DEADLOCKED.")
        else:
            print(f"[Monitor] OK: Heartbeat is healthy (last {now - _last_heartbeat_time:.1f}s ago)")

_monitor_thread = threading.Thread(target=_monitor_event_loop, daemon=True)
_monitor_thread.start()
print(f"[Startup] Monitor thread started")


def run_async(coro, wait=True, timeout=None):
    """Run an async coroutine on the persistent background event loop.

    If wait is True, block until the coroutine finishes or times out.
    If wait is False, schedule it in the background and return immediately.
    """
    print(f"[run_async] Scheduling: {coro}, wait={wait}")
    print(f"[run_async] Loop running: {_loop.is_running()}, closed: {_loop.is_closed()}")
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    print(f"[run_async] Future created: {future}")
    if wait:
        print(f"[run_async] Waiting (timeout={timeout})...")
        result = future.result(timeout=timeout)
        print(f"[run_async] Wait completed, result: {result}")
        return result
    print(f"[run_async] Adding callback for background execution")
    future.add_done_callback(_log_background_exception)
    print(f"[run_async] Callback added")
    print(f"[run_async] Returning immediately (future state: {future._state})")
    return future


async def _process_update_logged(update):
    """Wrapper around bot processing with logging."""
    print(f"[Bot] _process_update_logged STARTED for update {update.update_id}")
    import time
    start = time.time()
    try:
        print(f"[Bot] Processing update {update.update_id} starting... type={update.__class__.__name__}")
        print(f"[Bot] Calling bot_app.process_update() with 10s timeout...")
        
        # Wrap process_update in a timeout to prevent deadlocks
        await asyncio.wait_for(
            bot_app.process_update(update),
            timeout=10.0
        )
        
        elapsed = time.time() - start
        print(f"[Bot] Processing update {update.update_id} completed successfully in {elapsed:.2f}s")
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        print(f"[Bot] TIMEOUT processing update {update.update_id} after {elapsed:.2f}s - process_update hung")
    except Exception as e:
        elapsed = time.time() - start
        print(f"[Bot] FAILED to process update {update.update_id} after {elapsed:.2f}s: {type(e).__name__}: {e}")
        traceback.print_exc()


async def _heartbeat():
    """Periodic heartbeat to verify event loop is processing coroutines."""
    global _last_heartbeat_time
    import time
    count = 0
    while True:
        count += 1
        now = time.time()
        _last_heartbeat_time = now
        print(f"[Heartbeat #{count}] Event loop is alive at {time.strftime('%H:%M:%S')}")
        try:
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[Heartbeat] Exception during sleep: {e}")
            break


async def _startup():
    """Async startup: initialize bot_app on the event loop where it will be used."""
    global bot_app
    print("[Async Startup] Starting in event loop thread...")
    try:
        print("[Async Startup] Creating bot_app via get_bot_app()...")
        bot_app = get_bot_app()
        print("[Async Startup] bot_app created, now initializing...")
        await bot_app.initialize()
        print("[Async Startup] bot_app initialized successfully!")
        return True
    except Exception as e:
        print(f"[Async Startup ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        raise


# Initialize the bot app INSIDE the event loop before serving requests
bot_app = None  # Will be set during async startup
print("[Startup] Scheduling async startup on event loop...")
try:
    future = asyncio.run_coroutine_threadsafe(_startup(), _loop)
    print(f"[Startup] Created startup future: {future}")
    result = future.result(timeout=30)
    print(f"[Startup] Async startup completed: {result}")
    
    # Verify event loop is running and processing tasks
    print("[Startup] Verifying event loop is running...")
    print(f"[Startup] Loop running: {_loop.is_running()}")
    print(f"[Startup] Loop closed: {_loop.is_closed()}")
    print(f"[Startup] Thread is alive: {_thread.is_alive()}")
    print(f"[Startup] bot_app is initialized: {bot_app is not None}")
    
    print(f"[Startup] Scheduling heartbeat task...")
    run_async(_heartbeat(), wait=False)
    print("[Startup] Heartbeat scheduled")
except Exception as e:
    print(f"[Startup ERROR] Failed to initialize bot: {e}")
    traceback.print_exc()
    raise

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
        update = Update.de_json(update_json, bot_app.bot)
        print(f"[Webhook] Deserialized update {update.update_id}")
        update_type = "message" if update.message else ("callback_query" if update.callback_query else "other")
        print(f"[Webhook] Received update {update.update_id}, type: {update_type}")
        print(f"[Webhook] About to schedule _process_update_logged coroutine...")
        coro = _process_update_logged(update)
        print(f"[Webhook] Coroutine created: {coro}")
        print(f"[Webhook] Calling run_async with wait=False...")
        future = run_async(coro, wait=False)
        print(f"[Webhook] run_async returned future: {future}")
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
