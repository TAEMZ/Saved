import os
from cryptography.fernet import Fernet

KEY_FILE = os.getenv("SECRET_KEY_PATH", "secret.key")

# Ensure the directory for the key file exists if it is in a subdirectory
key_dir = os.path.dirname(KEY_FILE)
if key_dir and not os.path.exists(key_dir):
    try:
        os.makedirs(key_dir, exist_ok=True)
    except Exception as e:
        print(f"Error creating directory {key_dir} for key file: {e}")

# Ensure we have a secret key file
if os.path.exists(KEY_FILE):
    try:
        with open(KEY_FILE, "rb") as f:
            _key = f.read()
    except Exception as e:
        print(f"Error reading {KEY_FILE}, generating new one: {e}")
        _key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(_key)
else:
    _key = Fernet.generate_key()
    try:
        with open(KEY_FILE, "wb") as f:
            f.write(_key)
    except Exception as e:
        print(f"Error saving {KEY_FILE}: {e}")

_fernet = Fernet(_key)

def encrypt_text(text: str) -> str:
    """Encrypts plaintext text to a secure AES token. Returns empty text as-is."""
    if not text:
        return text
    try:
        return _fernet.encrypt(text.encode('utf-8')).decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}")
        return text

def decrypt_text(encrypted_text: str) -> str:
    """Decrypts an encrypted AES token back to plaintext. Returns empty text as-is."""
    if not encrypted_text:
        return encrypted_text
    try:
        return _fernet.decrypt(encrypted_text.encode('utf-8')).decode('utf-8')
    except Exception as e:
        # If decryption fails, it might be unencrypted text or key mismatch
        print(f"Decryption error: {e}")
        return encrypted_text
