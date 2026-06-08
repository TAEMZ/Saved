# Known Issues & Limitations

## `/sync` Imported Media Cannot Be Viewed

### Problem
When you use `/sync` to import messages from Telegram's "Saved Messages", photos, videos, and documents **cannot be re-displayed** using `/view<id>`.

### Why This Happens
- `/sync` uses **Telethon** library to fetch your Saved Messages history
- Telethon provides media in a different format than Telegram Bot API
- The bot cannot get the `file_id` needed to re-send media through Bot API
- These messages don't have `telegram_message_id` either since they're from a different chat

### What Works
✅ **Text and captions** from synced messages work perfectly  
✅ **Tags and reminders** work on synced messages  
✅ **NEW photos/videos sent directly** to the bot work 100%

### Workaround
If you need to view synced media:
1. Open Telegram
2. Go to your "Saved Messages"  
3. Find the original message
4. **Forward it to the bot** (this saves it with full media support)
5. Archive the old synced version

### Technical Details
- Synced messages have: `has_telegram_id=False, has_file_id=False`
- Direct messages have: `has_telegram_id=True, has_file_id=True`

### Possible Future Fix
To fix this, the bot would need to:
1. Download each media file during sync (slow, uses bandwidth)
2. Re-upload it through Bot API to get a `file_id`
3. Store the new `file_id`

This would make `/sync` much slower (especially for 100 messages with media), so it's not implemented yet.

---

## Summary
**Use `/sync` to import text/links quickly**  
**Forward important photos/videos directly to the bot for full media support**
