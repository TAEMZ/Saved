# Deploying on Render (free) + Supabase (free)

Everything works here, including `/sync` (Render allows the socket connections
Telethon needs, unlike PythonAnywhere free). Data lives in Supabase Postgres so it
survives Render's disk wipes.

Architecture: **Render free Web Service (webhook, 1 worker) + cron-job.org pinger.**
The pinger both keeps the free service awake and drives reminders/nudges.

---

## 0. One-time: get the bot code into a GitHub repo
Render deploys from a Git repo. Put the contents of this folder in a private GitHub repo.
Make sure a `.gitignore` excludes local-only files (already provided): `secret.key`,
`*.db`, `venv/`, `__pycache__/`, the `_*.py` test scripts.

Files Render needs (all already here):
`bot.py, flask_app.py, database.py, config.py, config.json, encryption.py,
userlang.py, translations.py, requirements.txt, Procfile, render.yaml`

## 1. Create the Web Service on Render
- render.com → New → **Web Service** → connect your repo.
- It auto-detects `render.yaml`. If asked manually:
  - Environment: **Python 3**
  - Build command: `pip install -r requirements.txt`
  - Start command: `gunicorn flask_app:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`
  - Plan: **Free**, Region: **Frankfurt** (closest to your Supabase eu-central-1)

⚠️ Keep **workers = 1**. The `/sync` flow holds a live Telegram connection in memory;
multiple workers would break it.

## 2. Set environment variables (Render dashboard → your service → Environment)
Add these two **secret** vars (do NOT put them in code/git):

| Key | Value |
|-----|-------|
| `DATABASE_URL` | `postgresql://postgres.fdsfgeizvyklnfncasxd:YOUR-PASSWORD@aws-1-eu-central-1.pooler.supabase.com:5432/postgres` |
| `FERNET_KEY` | `FPDkhkWcQ-FMllPD7Q5Jr6bLREvESD0ETZW0sXleJUw=` |

- `DATABASE_URL`: your Supabase **Session pooler** string (port 5432) with the real password.
- `FERNET_KEY`: the value from your local `secret.key` (so existing encrypted data stays readable).

Save → Render redeploys.

## 3. Tell Telegram where the bot lives
Your service URL is like `https://sare-bot.onrender.com`.
- Put it in `config.json` → `"WEBHOOK_URL": "https://sare-bot.onrender.com"`, commit & push
  (or set a `WEBHOOK_URL` env var — config.py reads env first).
- Then visit once in a browser:
  `https://sare-bot.onrender.com/set_webhook`  →  should return `{"ok": true, ...}`

## 4. Set up the reminder/keep-alive pinger
- cron-job.org (free) → new job:
  - URL: `https://sare-bot.onrender.com/run_jobs?token=sare_secret_token_98351`
  - Every **1 minute**
- This delivers due reminders, runs stale-nudges (self-throttled to every 6h),
  and keeps the free service from sleeping.

(The token must equal `WEBHOOK_SECRET_TOKEN` in config.json.)

## 5. Stop the local bot
Local polling and the Render webhook can't share one token:
```bash
pkill -9 -f "python3 bot.py"
```
(To return to local testing later: visit `/delete_webhook`, then run `python3 bot.py`.)

---

## SECURITY — do this after it works
Your DB password was shared in chat. Rotate it:
1. Supabase → Project Settings → Database → **Reset database password**.
2. Update **only** the `DATABASE_URL` env var in Render with the new password. Save.
The old (exposed) password is now useless.

## Verify
- Message the bot `/start` → it replies.
- Save something, set a reminder for ~2 min → it fires (cron runs each minute).
- Try `/sync` → should connect (this is the feature PA free could not do).

## Troubleshooting
- **No reply to /start:** check Render **Logs**; confirm `/set_webhook` returned ok and
  `DATABASE_URL`/`FERNET_KEY` are set.
- **Reminders never fire:** confirm the cron job runs (cron-job.org execution log = 200)
  and the token matches.
- **DB errors:** make sure you used the **Session pooler** URL (port 5432), not the
  direct IPv6 one.
- **First request after idle is slow:** free services cold-start (~30-50s) when they
  were asleep; the 1-min pinger keeps it warm.
