import database
import json

database.init_db()

conn = database.get_connection()
cursor = conn.cursor()

# Get recent media messages
cursor.execute('''
    SELECT id, chat_id, media_type, media_file_id, telegram_message_id, text
    FROM saved_messages 
    WHERE media_type != "text" 
    ORDER BY id DESC 
    LIMIT 10
''')

messages = cursor.fetchall()

print(f"Found {len(messages)} media messages:\n")

for msg in messages:
    msg_dict = dict(msg)
    print(f"ID: {msg_dict['id']}")
    print(f"  Chat ID: {msg_dict['chat_id']}")
    print(f"  Media Type: {msg_dict['media_type']}")
    print(f"  Has file_id: {bool(msg_dict['media_file_id'])}")
    print(f"  Has telegram_message_id: {bool(msg_dict['telegram_message_id'])}")
    if msg_dict['media_file_id']:
        print(f"  File ID: {msg_dict['media_file_id'][:50]}...")
    if msg_dict['telegram_message_id']:
        print(f"  Message ID: {msg_dict['telegram_message_id']}")
    print()

# Check one specific message
print("\n" + "="*60)
print("Checking message ID 138 specifically:")
print("="*60)
cursor.execute('SELECT * FROM saved_messages WHERE id = 138')
row = cursor.fetchone()
if row:
    msg = dict(row)
    print(f"Media Type: {msg['media_type']}")
    print(f"File ID: {msg['media_file_id']}")
    print(f"Telegram Message ID: {msg['telegram_message_id']}")
    print(f"Text: {database.encryption.decrypt_text(msg['text'])[:100] if msg['text'] else 'None'}")
else:
    print("Message 138 not found")
