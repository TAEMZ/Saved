# Deploying on PythonAnywhere (Free tier)

This runs the bot in **webhook mode**. Reminders + stale-item nudges are driven by a
free external cron pinger. **`/sync` will NOT work on the free tier** (Telethon needs
raw socket access the free tier blocks). Everything else works.

Replace `YOURNAME` below with your PythonAnywhere username everywhere it appears.

---

## 1. Upload the files
In the PythonAnywhere **Files** tab, create folder `mysite` and upload:
- `bot.py`
- `flask_app.py`
- `database.py`
- `config.py`
- `config.json`
- `encryption.py`
- `userlang.py`
- `translations.py`
- `requirements.txt`
- `secret.key`  ← important: upload your existing key so saved data stays readable
- `saved_messages.db`  ← optional, only if you want your current items

## 2. Edit config.json
Set WEBHOOK_URL to your site (keep your real token/api values):
```json
"WEBHOOK_URL": "https://YOURNAME.pythonanywhere.com"
```

## 3. Install dependencies
Open a **Bash console** and run:
```bash
cd ~/mysite
pip install --user -r requirements.txt
```

## 4. Create the web app
- **Web** tab → **Add a new web app** → **Manual configuration** → **Python 3.10** (or newer).
- Click the **WSGI configuration file** link and replace its entire contents with:
```python
import sys
path = "/home/YOURNAME/mysite"
if path not in sys.path:
    sys.path.append(path)
from flask_app import app as application
```
- Save, then click the green **Reload** button on the Web tab.

## 5. Register the webhook
Visit this once in your browser:
```
https://YOURNAME.pythonanywhere.com/set_webhook
```
You should see `{"ok": true, "webhook": "...":}`.

## 6. Set up the reminder pinger
- Go to https://cron-job.org (free), create an account.
- New cron job:
  - URL: `https://YOURNAME.pythonanywhere.com/run_jobs?token=sare_secret_token_98351`
  - Schedule: **every 1 minute**
- Save.

(The token must match `WEBHOOK_SECRET_TOKEN` in your config.json.)

## 7. Stop the local test bot
The local polling bot and the PA webhook can't both use the same token.
On the dev machine, stop it:
```bash
pkill -9 -f "python3 bot.py"
```
(If you ever want to go back to local testing, visit `/delete_webhook` first,
then run `python3 bot.py` again.)

---

## Verify
Message your bot `/start` — it should respond. Set a reminder for ~2 minutes and
confirm it fires (cron pings every minute, so it lands within ~1 min of due time).

## Troubleshooting
- **No response to /start:** re-check the WSGI file path, Reload, and that
  `/set_webhook` returned ok. Check the Web tab **error log**.
- **Reminders never fire:** confirm the cron job is enabled and the token matches.
  Check the cron-job.org execution log for 200 responses.
- **/sync fails:** expected on free tier. Needs the paid plan (Always-on task running
  `python3 bot.py` in polling mode instead of webhook).
