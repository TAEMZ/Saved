import re

src = open('bot.py').read()
orig = src

# ---------------------------------------------------------------
# FIX 1: bracket-tolerant ID matcher (was failing because Markdown
# strips the [] around [ID: N], so replies never matched).
# ---------------------------------------------------------------
assert r're.search(r"\[ID:\s*(\d+)\]", prompt)' in src
src = src.replace(r're.search(r"\[ID:\s*(\d+)\]", prompt)',
                  r're.search(r"ID:\s*(\d+)", prompt)')

# ---------------------------------------------------------------
# FIX 2: kill the whole Markdown-injection class of bugs.
# Remove every parse_mode="Markdown" and strip ** bold markers.
# User content (URLs with _, etc.) then can't corrupt rendering.
# ---------------------------------------------------------------
n_pm = len(re.findall(r'parse_mode="Markdown"', src))
src = re.sub(r',?\s*parse_mode="Markdown"', '', src)
assert 'parse_mode="Markdown"' not in src
# remove bold markers (no ** operators / **kwargs exist in this file)
assert '**kwargs' not in src and '**args' not in src
n_bold = src.count('**')
src = src.replace('**', '')

# ---------------------------------------------------------------
# FIX 3: richer, more interactive reminder buttons on each card.
# ---------------------------------------------------------------
old_kb = '''    keyboard = [
        [
            InlineKeyboardButton("🕒 1 Hour", callback_data=f"rem:1h:{db_id}"),
            InlineKeyboardButton("🕒 3 Hours", callback_data=f"rem:3h:{db_id}"),
            InlineKeyboardButton("🕒 Tomorrow", callback_data=f"rem:tom:{db_id}"),
        ],
        [
            InlineKeyboardButton("✍️ Custom Time", callback_data=f"rem:cust:{db_id}"),
            InlineKeyboardButton("🏷️ Add Tag", callback_data=f"tag:add:{db_id}"),
        ],
        [
            InlineKeyboardButton("📁 Archive", callback_data=f"arc:{db_id}")
        ]
    ]'''
new_kb = '''    keyboard = [
        [
            InlineKeyboardButton("⏰ 10 min", callback_data=f"rem:10m:{db_id}"),
            InlineKeyboardButton("⏰ 30 min", callback_data=f"rem:30m:{db_id}"),
            InlineKeyboardButton("⏰ 1 hour", callback_data=f"rem:1h:{db_id}"),
        ],
        [
            InlineKeyboardButton("⏰ 3 hours", callback_data=f"rem:3h:{db_id}"),
            InlineKeyboardButton("🌙 Tonight", callback_data=f"rem:tonight:{db_id}"),
            InlineKeyboardButton("☀️ Tomorrow", callback_data=f"rem:tom:{db_id}"),
        ],
        [
            InlineKeyboardButton("✍️ Custom", callback_data=f"rem:cust:{db_id}"),
            InlineKeyboardButton("🏷️ Tag", callback_data=f"tag:add:{db_id}"),
            InlineKeyboardButton("📁 Archive", callback_data=f"arc:{db_id}"),
        ],
    ]'''
assert old_kb in src, "card keyboard block not found"
src = src.replace(old_kb, new_kb)

# ---------------------------------------------------------------
# FIX 4: handle the new reminder presets in the callback handler.
# ---------------------------------------------------------------
old_rem = '''        if time_type == "1h":
            reminder_time = now_utc + timedelta(hours=1)
        elif time_type == "3h":
            reminder_time = now_utc + timedelta(hours=3)
        elif time_type == "tom":
            reminder_time = get_tomorrow_morning_in_utc(tz)
        elif time_type == "cust":'''
new_rem = '''        if time_type == "10m":
            reminder_time = now_utc + timedelta(minutes=10)
        elif time_type == "30m":
            reminder_time = now_utc + timedelta(minutes=30)
        elif time_type == "1h":
            reminder_time = now_utc + timedelta(hours=1)
        elif time_type == "3h":
            reminder_time = now_utc + timedelta(hours=3)
        elif time_type == "tonight":
            reminder_time = parse_relative_time_for_user("tonight", tz)
        elif time_type == "tom":
            reminder_time = get_tomorrow_morning_in_utc(tz)
        elif time_type == "cust":'''
assert old_rem in src, "rem callback block not found"
src = src.replace(old_rem, new_rem)

# ---------------------------------------------------------------
# FIX 5: add a 10-min snooze option on delivered reminders.
# ---------------------------------------------------------------
old_snz_btns = '''            InlineKeyboardButton("⏰ Snooze 1 Hour", callback_data=f"snz:1h:{db_id}"),
            InlineKeyboardButton("⏰ Snooze Tomorrow", callback_data=f"snz:tom:{db_id}"),'''
new_snz_btns = '''            InlineKeyboardButton("⏰ 10 min", callback_data=f"snz:10m:{db_id}"),
            InlineKeyboardButton("⏰ 1 hour", callback_data=f"snz:1h:{db_id}"),
            InlineKeyboardButton("☀️ Tomorrow", callback_data=f"snz:tom:{db_id}"),'''
assert old_snz_btns in src
src = src.replace(old_snz_btns, new_snz_btns)

old_snz_logic = '''        if snooze_type == "1h":
            reminder_time = now_utc + timedelta(hours=1)
            duration_str = "1 hour"'''
new_snz_logic = '''        if snooze_type == "10m":
            reminder_time = now_utc + timedelta(minutes=10)
            duration_str = "10 minutes"
        elif snooze_type == "1h":
            reminder_time = now_utc + timedelta(hours=1)
            duration_str = "1 hour"'''
assert old_snz_logic in src
src = src.replace(old_snz_logic, new_snz_logic)

open('bot.py', 'w').write(src)
print(f"OK: removed {n_pm} parse_mode, {n_bold} bold-pairs; all blocks patched")
