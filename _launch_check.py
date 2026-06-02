import subprocess, sys, time, os, json, signal

os.chdir('/home/tabflows/tmp/sare')
status = {}

# 1. deps
try:
    import telegram, telethon, dateparser, pytz, cryptography
    status['deps'] = f"OK telegram={telegram.__version__}"
except Exception as e:
    status['deps'] = f"MISSING: {e}"

# 2. getMe (token valid + username)
try:
    import urllib.request
    with open('config.json') as f:
        tok = json.load(f)['TELEGRAM_BOT_TOKEN']
    with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getMe", timeout=15) as r:
        d = json.load(r)
    status['getMe'] = d.get('ok')
    status['username'] = d.get('result', {}).get('username')
except Exception as e:
    status['getMe'] = f"ERR: {e}"

# 3. launch bot (only if deps OK)
if status['deps'].startswith('OK'):
    log = open('bot.log', 'w')
    p = subprocess.Popen([sys.executable, 'bot.py'], stdout=log, stderr=subprocess.STDOUT)
    time.sleep(10)
    alive = p.poll() is None
    status['bot_pid'] = p.pid
    status['bot_alive_after_10s'] = alive
    with open('bot.log') as f:
        status['bot_log'] = f.read()[-1500:]
else:
    status['bot_pid'] = None
    status['bot_alive_after_10s'] = False

with open('/tmp/STATUS.json', 'w') as f:
    json.dump(status, f, indent=2)
print(json.dumps(status, indent=2))
