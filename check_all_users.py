import database

database.init_db()

user_ids = [1298481036, 6824648273]

for user_id in user_ids:
    print(f"\n{'='*60}")
    print(f"USER ID: {user_id}")
    print('='*60)
    
    msgs = database.get_active_messages(user_id, limit=10)
    print(f"Active messages: {len(msgs)}")
    
    for msg in msgs:
        print(f"\n  Message ID {msg['id']}:")
        print(f"    Text: {msg['text'][:100] if msg['text'] else 'None'}")
        print(f"    Media: {msg['media_type']}")
        tags = database.get_message_tags(msg['id'])
        print(f"    Tags: {tags}")
    
    all_tags = database.get_all_tags(user_id)
    print(f"\n  All tags for this user: {all_tags}")
