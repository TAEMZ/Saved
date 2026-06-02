import subprocess, sys, time, os, json, signal, py_compile

os.chdir('/home/tabflows/tmp/sare')
st = {}

# compile check
try:
    py_compile.compile('bot.py', doraise=True)
    st['compiles'] = True
except Exception as e:
    st['compiles'] = f"FAIL: {e}"

src = open('bot.py').read()
st['no_markdown'] = 'parse_mode="Markdown"' not in src
st['id_regex_loose'] = 'ID:\\s*(\\d+)", prompt)' in src
st['has_10m_btn'] = 'rem:10m:' in src
st['has_tonight'] = 'rem:tonight:' in src

if st['compiles'] is True:
    for pid in subprocess.run(['pgrep','-f','bot.py'], capture_output=True, text=True).stdout.split():
        try: os.kill(int(pid), signal.SIGTERM)
        except Exception: pass
    time.sleep(2)
    log = open('bot.log','w')
    p = subprocess.Popen([sys.executable,'bot.py'], stdout=log, stderr=subprocess.STDOUT)
    time.sleep(9)
    st['new_pid'] = p.pid
    st['alive'] = p.poll() is None
    st['log_tail'] = open('bot.log').read()[-800:]

json.dump(st, open('/tmp/RS2.json','w'), indent=2)
print(json.dumps(st, indent=2))
