import database

database.init_db()

user_id = 6824648273

# Get all tags
tags = database.get_all_tags(user_id)
print(f"Tags for user {user_id}: {tags}\n")

for tag in tags:
    print(f"\nTag: #{tag}")
    print("="*40)
    
    # Get messages with this tag (active only)
    messages = database.get_messages_by_tag(user_id, tag)
    print(f"  Active messages: {len(messages)}")
    
    # Check ALL messages with this tag (including archived)
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT sm.*, sm.is_archived FROM saved_messages sm
        JOIN tags t ON sm.id = t.message_id
        WHERE sm.chat_id = ? AND t.tag_name = ?
    ''', (user_id, tag))
    all_msgs = cursor.fetchall()
    print(f"  Total messages (inc. archived): {len(all_msgs)}")
    
    for msg in all_msgs:
        status = "ARCHIVED" if msg['is_archived'] else "ACTIVE"
        text = database.encryption.decrypt_text(msg['text']) if msg['text'] else "None"
        print(f"    - ID {msg['id']}: [{status}] {text[:50]}")
