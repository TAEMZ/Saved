"""Webhook entry point for hosting on PythonAnywhere (free tier) or any WSGI host.

How it works:
- Telegram POSTs each update to /<BOT_TOKEN> (the token doubles as a secret path).
- An external cron service (cron-job.org) pings /run_jobs?token=... every minute to
  deliver due reminders and, at most every 6h, the stale-item nudges.
- Visit /set_webhook once after deploy to register the webhook with Telegram.

Note: /sync (Telethon history import) does NOT work on PythonAnywhere's free tier —
it needs raw socket access to Telegram's servers, which the free tier blocks.
Direct saving, reminders, tags, nudges and languages all work fine.
"""
import asyncio
import threading

from flask import Flask, request, jsonify
from telegram import Update

import config
import bot as botmod

app = Flask(__name__)

application = botmod.get_bot_app()

_loop = asyncio.new_event_loop()


def _start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

_loop_thread = threading.Thread(target=_start_loop, args=(_loop,), daemon=True)
_loop_thread.start()


def _run(coro, timeout=None):
    """Schedule an async coroutine on the shared event loop and wait for its result."""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


def _log_background_exception(future):
    try:
        future.result()
    except Exception as exc:
        print(f"Background task failed: {exc}")


try:
    _run(application.initialize(), timeout=30)
except Exception as exc:
    print(f"Failed to initialize bot application: {exc}")
    raise


@app.route("/")
def index():
    return "Saved Messages bot is running."


@app.route(f"/{config.TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, application.bot)
    future = asyncio.run_coroutine_threadsafe(application.process_update(update), _loop)
    future.add_done_callback(_log_background_exception)
    return jsonify({"ok": True})


@app.route("/run_jobs")
def run_jobs():
    if request.args.get("token") != config.WEBHOOK_SECRET_TOKEN:
        return jsonify({"ok": False, "error": "forbidden"}), 403
    future = asyncio.run_coroutine_threadsafe(botmod.run_due_jobs(application.bot), _loop)
    future.add_done_callback(_log_background_exception)
    return jsonify({"ok": True})


@app.route("/set_webhook")
def set_webhook():
    base = (config.WEBHOOK_URL or "").rstrip("/")
    if not base:
        return jsonify({"ok": False, "error": "WEBHOOK_URL not set in config"}), 400
    url = f"{base}/{config.TELEGRAM_BOT_TOKEN}"
    _run(application.bot.set_webhook(url=url, allowed_updates=Update.ALL_TYPES), timeout=30)
    return jsonify({"ok": True, "webhook": url})


@app.route("/delete_webhook")
def delete_webhook():
    _run(application.bot.delete_webhook(), timeout=30)
    return jsonify({"ok": True})
