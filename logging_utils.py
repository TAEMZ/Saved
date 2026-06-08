import logging
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def log_message(user_id, message_type, content=None, extra=None):
    """Log a message with user context."""
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "type": message_type,
        "content": content[:100] if content else None  # Truncate long content
    }
    if extra:
        log_data.update(extra)
    
    logger.info(f"MSG[{user_id}]: {message_type} - {content[:50] if content else ''}")

def log_error(user_id, error_type, message):
    """Log an error with user context."""
    logger.error(f"ERR[{user_id}]: {error_type} - {message}")

def log_reminder(user_id, message_id):
    """Log a reminder being sent."""
    logger.info(f"REM[{user_id}]: Sent reminder for message {message_id}")
