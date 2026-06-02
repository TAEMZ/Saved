import subprocess, sys, time, os, signal, json

os.chdir('/home/tabflows/tmp/sare')
st = {}

# Hard-kill EVERY python process running bot.py (any old instances)
pids = subprocess.run(['pgrep', '-f', 'bot.py'], capture_output=True, text=True).stdout.split()
st['found_pids'] = pids
for pid in pids:
    try:
        os.kill(int(pid), signal.SIGKILL)
    except Exception:
        pass
time.sleep(3)
# Confirm none remain
remain = subprocess.run(['pgrep', '-f', 'bot.py'], capture_output=True, text=True).stdout.split()
st['remaining_after_kill'] = remain

# Start exactly one fresh instance
log = open('bot.log', 'w')
p = subprocess.Popen([sys.executable, 'bot.py'], stdout=log, stderr=subprocess.STDOUT)
time.sleep(12)
st['new_pid'] = p.pid
st['alive'] = p.poll() is None
# how many bot.py processes now?
now = subprocess.run(['pgrep', '-f', 'bot.py'], capture_output=True, text=True).stdout.split()
st['running_now'] = now
st['log'] = open('bot.log').read()[-1200:]

json.dump(st, open('/tmp/CR.json', 'w'), indent=2, ensure_ascii=False)
print(json.dumps(st, indent=2, ensure_ascii=False))
