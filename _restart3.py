import subprocess, sys, time, os, json, signal, py_compile, importlib

os.chdir('/home/tabflows/tmp/sare')
st = {}

# compile all three modules
for f in ('translations.py', 'userlang.py', 'bot.py'):
    try:
        py_compile.compile(f, doraise=True)
        st[f] = 'compiles'
    except Exception as e:
        st[f] = f'FAIL: {e}'

# import-level sanity (translations key coverage + userlang init)
try:
    import translations as T
    missing = {}
    for code in T.LANG_CODES:
        miss = [k for k in T.EN if k not in T.STR.get(code, {})]
        if miss:
            missing[code] = len(miss)
    st['translation_missing_counts'] = missing  # fall back to EN; informational
    st['n_keys_en'] = len(T.EN)
except Exception as e:
    st['translations_import'] = f'FAIL: {e}'

ok = all(v == 'compiles' for k, v in st.items() if k.endswith('.py'))
if ok:
    for pid in subprocess.run(['pgrep', '-f', 'bot.py'], capture_output=True, text=True).stdout.split():
        try:
            os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass
    time.sleep(2)
    log = open('bot.log', 'w')
    p = subprocess.Popen([sys.executable, 'bot.py'], stdout=log, stderr=subprocess.STDOUT)
    time.sleep(10)
    st['new_pid'] = p.pid
    st['alive'] = p.poll() is None
    st['log_tail'] = open('bot.log').read()[-1500:]

json.dump(st, open('/tmp/RS3.json', 'w'), indent=2, ensure_ascii=False)
print(json.dumps(st, indent=2, ensure_ascii=False))
