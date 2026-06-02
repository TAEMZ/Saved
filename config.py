import os
import json
from dotenv import load_dotenv

# Load environment variables if a .env file exists
load_dotenv()

# Default configuration values
DATABASE_PATH = os.getenv("DATABASE_PATH", "saved_messages.db")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
# A secret token to verify that incoming webhook requests are from Telegram
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "super_secret_webhook_token_123")

# Fallback: check config.json ONLY for keys NOT set by env (env vars take priority)
CONFIG_FILE = "config.json"

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r") as f:
            config_data = json.load(f)
            if not TELEGRAM_BOT_TOKEN:
                TELEGRAM_BOT_TOKEN = config_data.get("TELEGRAM_BOT_TOKEN", "")
            if not TELEGRAM_API_ID:
                TELEGRAM_API_ID = config_data.get("TELEGRAM_API_ID", "")
            if not TELEGRAM_API_HASH:
                TELEGRAM_API_HASH = config_data.get("TELEGRAM_API_HASH", "")
            if not DATABASE_PATH:
                DATABASE_PATH = config_data.get("DATABASE_PATH", "saved_messages.db")
            if not WEBHOOK_URL:
                WEBHOOK_URL = config_data.get("WEBHOOK_URL", "")
            if not WEBHOOK_SECRET_TOKEN:
                WEBHOOK_SECRET_TOKEN = config_data.get("WEBHOOK_SECRET_TOKEN", "super_secret_webhook_token_123")
    except Exception as e:
        print(f"Error reading {CONFIG_FILE}: {e}")

def save_config(token, webhook_url="", secret_token="", api_id="", api_hash=""):
    """Helper to save config to config.json if needed."""
    config_data = {
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_API_ID": api_id or TELEGRAM_API_ID,
        "TELEGRAM_API_HASH": api_hash or TELEGRAM_API_HASH,
        "DATABASE_PATH": DATABASE_PATH,
        "WEBHOOK_URL": webhook_url,
        "WEBHOOK_SECRET_TOKEN": secret_token or WEBHOOK_SECRET_TOKEN
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f, indent=4)
