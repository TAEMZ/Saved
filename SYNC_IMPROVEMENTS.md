# /sync Improvements - Incremental Sync

## What Changed

### Before:
- `/sync` fetched ALL messages every time
- Very slow if you have 1000s of messages
- Downloads same photos over and over

### After (Incremental Sync):
- **First sync:** Fetches all messages, saves highest message ID
- **Subsequent syncs:** Only fetches NEW messages since last sync
- **Much faster!** Only processes what's new

## How It Works

### Database Changes:
- Added `last_sync_message_id` column to `user_settings` table
- Stores the highest Telegram message ID seen during sync
- Automatically migrates existing databases

### Sync Logic:
```python
# First sync (last_sync_id = 0)
client.iter_messages('me')  # Fetch ALL

# Next sync (last_sync_id = 12345)
client.iter_messages('me', min_id=12345)  # Only fetch messages AFTER 12345
```

## User Experience

### First Sync:
```
📥 First Sync Complete!

Imported 247 messages.
📎 Uploaded 45 media files
⏭️ Skipped 12 large files

💡 Next time you run /sync, I'll only fetch new messages!
```

### Incremental Sync:
```
📥 Incremental Sync Complete!

Imported 8 messages.
📎 Uploaded 2 media files
⏭️ Skipped 1 large files

💡 Next time you run /sync, I'll only fetch new messages!
```

## Performance Impact

### Example: User with 1000 saved messages

**First sync:**
- Fetches: 1000 messages
- Time: ~5-10 minutes (with media)

**After saving 10 new messages, run /sync again:**
- Fetches: 10 messages (NEW only!)
- Time: ~10 seconds
- **100x faster!** ⚡

## Smart Filtering Remains

Still skips:
- ⏭️ Videos (too large)
- ⏭️ Files over 10MB
- ⏭️ Audio files

Still uploads:
- ✅ All photos
- ✅ Small documents (< 10MB)
- ✅ Voice messages

## Technical Details

### Telethon API:
```python
# min_id parameter: only fetch messages with ID > min_id
async for msg in client.iter_messages('me', min_id=last_sync_id):
    # Process only NEW messages
```

### Database Functions:
- `get_last_sync_message_id(chat_id)` - Get saved ID
- `set_last_sync_message_id(chat_id, message_id)` - Update saved ID

### Message ID Tracking:
- Tracks highest message ID seen during sync
- Saves it at the end
- Next sync starts from that ID + 1

## Future Ideas

Could add:
- `/sync --full` to force re-sync everything
- `/sync --reset` to clear last sync ID
- Show "X new messages" before starting sync
