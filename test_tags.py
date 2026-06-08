import database

database.init_db()

user_id = 1298481036

# Get messages
msgs = database.get_active_messages(user_id)
print(f"Active messages: {len(msgs)}")

if msgs:
    for msg in msgs:
        print(f"\nMessage ID {msg['id']}:")
        print(f"  Text: {msg['text'][:100] if msg['text'] else 'None'}")
        print(f"  Media: {msg['media_type']}")
        tags = database.get_message_tags(msg['id'])
        print(f"  Tags: {tags}")

# Get all tags
all_tags = database.get_all_tags(user_id)
print(f"\nAll user tags: {all_tags}")
