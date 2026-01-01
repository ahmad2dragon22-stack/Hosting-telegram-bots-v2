import json
import os
import logging
from config import CONFIG_FILE

logger = logging.getLogger(__name__)

BOT_CONFIG = {}

def load_config():
    """Loads bot configuration from the JSON file."""
    global BOT_CONFIG
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                BOT_CONFIG.update(data)
            logger.info(f"Loaded {len(BOT_CONFIG)} bots from config.")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            BOT_CONFIG = {}
    else:
        BOT_CONFIG = {}
    return BOT_CONFIG

def save_config():
    """Saves bot configuration to the JSON file."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(BOT_CONFIG, f, indent=4)
        logger.info("Bot configuration saved.")
    except Exception as e:
        logger.error(f"Error saving config: {e}")

def get_config():
    return BOT_CONFIG