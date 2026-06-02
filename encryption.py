"""AES (Fernet) encryption for saved message text.

Key resolution order:
  1. FERNET_KEY environment variable  (use this on Render — survives disk wipes)
  2. secret.key file                  (local development fallback)
  3. generate a new key and try to persist it to secret.key

IMPORTANT: on Render you MUST set FERNET_KEY to the same value as your local
secret.key, otherwise previously-saved items become unreadable.
"""
import os
from cryptography.fernet import Fernet

KEY_FILE = "secret.key"


def _load_key():
    env_key = os.getenv("FERNET_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "rb") as f:
                return f.read()
        except Exception as e:
            print(f"Error reading {KEY_FILE}: {e}")
    key = Fernet.generate_key()
    try:
        with open(KEY_FILE, "wb") as f:
            f.write(key)
    except Exception as e:
        print(f"Error saving {KEY_FILE}: {e}")
    return key


_fernet = Fernet(_load_key())


def encrypt_text(text: str) -> str:
    if not text:
        return text
    try:
        return _fernet.encrypt(text.encode('utf-8')).decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}")
        return text


def decrypt_text(encrypted_text: str) -> str:
    if not encrypted_text:
        return encrypted_text
    try:
        return _fernet.decrypt(encrypted_text.encode('utf-8')).decode('utf-8')
    except Exception as e:
        print(f"Decryption error: {e}")
        return encrypted_text
