# Telegram Saved Messages Organizer & Reminder Bot (Multi-User & Encrypted) 🚀

This is a beautiful, highly interactive Telegram bot that helps users organize their saved messages, links, files, and photos with tags and timely reminders. 

### Key Features
1. **Multi-User Out of the Box:** Anyone on Telegram can search for your bot, click **Start**, and immediately use it. Database entries and tags are private and isolated per user.
2. **AES-256 Database Encryption:** Built with privacy in mind. Every saved message's text and caption is automatically encrypted using AES-256 (via the `cryptography` library) *before* being saved to the database. If your server database file (`saved_messages.db`) is stolen or leaked, it is completely unreadable.
3. **On-Demand Saved Messages Sync (`/sync`):** Users can easily import their older official Telegram "Saved Messages" history dynamically! No manual typing is required—the bot uses Telegram's native **Share Contact** button to securely fetch their phone number, temporarily log in using your server's developer API credentials, import their last 100 messages, and immediately log out and wipe any session files.
4. **Natural Language Reminders:** Pick a pre-set reminder ("1 hour", "Tomorrow morning") or type a natural language custom date (e.g. `tomorrow at 3pm`, `in 45 minutes`, `next friday 9am`) using the interactive buttons!

---

## 🛠️ Step-by-Step Server Setup

### 1. Get Telegram Developer Credentials
Since this bot supports historical `/sync` downloading from Telegram's client API:
1. Log in to [my.telegram.org](https://my.telegram.org) with your personal Telegram phone number.
2. Go to **API development tools**.
3. Create a new application (fill out the title and short name, e.g., "SavedMsgHelper").
4. Copy the **App api_id** (integer) and **App api_hash** (string).
*Note: Your bot users will NOT need to do this. You are hosting the server, so only you need these credentials to share globally.*

### 2. Get a Telegram Bot Token
1. Open Telegram and search for `@BotFather`.
2. Send `/newbot` and follow the instructions to create a bot.
3. Copy the **HTTP API Token**.

### 3. Configure Settings
Open [config.json](file:///c:/Users/calm/Desktop/sare/config.json) in your project folder and replace the placeholders:
```json
{
    "TELEGRAM_BOT_TOKEN": "YOUR_BOT_TOKEN_FROM_BOTFATHER",
    "TELEGRAM_API_ID": "YOUR_API_ID_FROM_MY_TELEGRAM_ORG",
    "TELEGRAM_API_HASH": "YOUR_API_HASH_FROM_MY_TELEGRAM_ORG",
    "DATABASE_PATH": "saved_messages.db",
    "WEBHOOK_URL": "",
    "WEBHOOK_SECRET_TOKEN": "sare_secret_token_98351"
}
```

---

## 💻 Running Locally (Polling Mode)

1. Open your terminal in the project directory.
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the bot:
   ```bash
   python bot.py
   ```
4. Find your bot on Telegram, click **Start**, and send some messages!
   * Try forwarding a message to it.
   * Try typing `/sync` to import your history!

---

## ☁️ Deploying 24/7 on PythonAnywhere (100% Free)

Follow these steps to host your bot on PythonAnywhere's free tier:

### 1. Create a Free Account
Sign up for a free Beginner account at [pythonanywhere.com](https://www.pythonanywhere.com).

### 2. Upload Your Files
Upload the following files to your PythonAnywhere files section (usually inside `/home/YOUR_USERNAME/mysite`):
* `requirements.txt`
* `config.json` *(Make sure this has your active Bot Token and API credentials!)*
* `config.py`
* `database.py`
* `encryption.py`
* `bot.py`
* `flask_app.py`

### 3. Install Dependencies
Open a new **Bash console** on PythonAnywhere and run:
```bash
cd ~/mysite
pip install -r requirements.txt --user
```

### 4. Setup the Web App (Flask Webhook)
1. Go to the **Web** tab on PythonAnywhere.
2. Click **Add a new web app**, choose **Manual Configuration** (select Python 3.10+).
3. Under the **Code** section, open your **WSGI configuration file** link (e.g. `/var/www/YOUR_USERNAME_pythonanywhere_com_wsgi.py`).
4. Replace the contents of that file with:
   ```python
   import sys
   import os

   path = '/home/YOUR_USERNAME/mysite'
   if path not in sys.path:
       sys.path.append(path)

   from flask_app import app as application
   ```
5. Click **Save**.
6. Edit `config.json` on PythonAnywhere and configure `WEBHOOK_URL` to:
   `https://YOUR_USERNAME.pythonanywhere.com`
7. In the Web tab, click **Reload** (green button).
8. Register your webhook by visiting this URL in your web browser:
   `https://YOUR_USERNAME.pythonanywhere.com/set_webhook`
   * It should reply with: `✅ Webhook successfully configured`.

### 5. Setup the Reminder Trigger
Since PythonAnywhere web servers go to sleep when not active, we use a free external cron service to check our database for reminders:
1. Go to [cron-job.org](https://cron-job.org) and register a free account.
2. Create a new cron job:
   * **URL:** `https://YOUR_USERNAME.pythonanywhere.com/check_reminders?token=sare_secret_token_98351`
   * **Schedule:** Every 1 minute.
3. Save the job.

Done! The bot is now running in the cloud 24/7. When any user forwards a message to it, it will encrypt it and save it. Every minute, `cron-job.org` triggers the checker to deliver outstanding reminders.

---

## 🤖 Bot Commands inside Telegram

* `/start` — Welcome introduction and guide
* `/sync` — Initiates secure, temporary client sync to import historical "Saved Messages"
* `/cancel` — Aborts an active `/sync` flow and cleans up session keys
* `/list` — Displays active unarchived saved items with details, tags, and inline card controls
* `/tags` — Displays all active tags and allows filtering saved messages
* `/search <query>` — Performs real-time in-memory text search across encrypted contents and tags
* `/timezone <timezone>` — Configures your timezone (e.g., `/timezone Europe/Paris` or `/timezone +3`) so that date parsing matches your exact clock
* `/help` — Displays setup manual and help menu
