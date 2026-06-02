import subprocess, sys, time, os, json, signal, re

os.chdir('/home/tabflows/tmp/sare')
status = {}

# kill any running bot.py
out = subprocess.run(['pgrep','-f','bot.py'], capture_output=True, text=True).stdout.split()
killed = []
for pid in out:
    try:
        os.kill(int(pid), signal.SIGTERM); killed.append(pid)
    except Exception:
        pass
status['killed_old'] = killed
time.sleep(2)

# verify the patch is in place
src = open('bot.py').read()
status['no_md_in_list'] = 'reply_text(text, parse_mode="Markdown")' not in src
status['view_handler_underscore'] = r'^/view_(\d+)$' in src

# relaunch
log = open('bot.log','w')
p = subprocess.Popen([sys.executable, 'bot.py'], stdout=log, stderr=subprocess.STDOUT)
time.sleep(9)
status['new_pid'] = p.pid
status['alive'] = p.poll() is None
status['log_tail'] = open('bot.log').read()[-1200:]

json.dump(status, open('/tmp/RESTART.json','w'), indent=2)
print(json.dumps(status, indent=2))
