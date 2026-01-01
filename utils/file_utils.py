import os
import re
import shutil
import logging
from datetime import datetime
import tempfile
import zipfile
from config import BOTS_DIR, BACKUPS_DIR

logger = logging.getLogger(__name__)

def find_token_in_files(path: str) -> str | None:
    """Searches for a Telegram bot token pattern in .py files within the given path."""
    TOKEN_PATTERN = re.compile(r'(\d+:[a-zA-Z0-9_-]{20,})')
    
    # If zip file, extract to temp and scan
    if os.path.isfile(path) and path.endswith('.zip'):
        temp_dir = tempfile.mkdtemp(prefix='scan_zip_', dir=os.path.dirname(path) or None)
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                # Prevent zip-slip by validating names
                for member in zf.namelist():
                    if member.startswith('/') or '..' in member:
                        continue
                zf.extractall(temp_dir)
            # recurse into extracted dir
            return find_token_in_files(temp_dir)
        except Exception as e:
            logger.warning(f"Failed to scan zip for token {path}: {e}")
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
            return None

    if os.path.isfile(path) and path.endswith('.py'):
        files_to_check = [path]
    elif os.path.isdir(path):
        files_to_check = [os.path.join(dirpath, f)
                          for dirpath, _, filenames in os.walk(path)
                          for f in filenames if f.endswith('.py')]
    else:
        return None

    for file_path in files_to_check:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                match = TOKEN_PATTERN.search(content)
                if match:
                    return match.group(1)
        except Exception as e:
            logger.warning(f"Could not read file {file_path}: {e}")
            continue
            
    return None

def get_bot_path(bot_id: str, sub_path: str = "") -> str:
    """Returns the absolute sandboxed path for a bot."""
    if '..' in sub_path or sub_path.startswith('/'):
        raise ValueError("Invalid path segment.")
    
    # Ensure bot_id is safe
    bot_id = str(bot_id).replace('/', '').replace('\\', '')
    
    base_bot_path = os.path.abspath(os.path.join(BOTS_DIR, bot_id))
    full_path = os.path.join(base_bot_path, sub_path)
    
    if not os.path.abspath(full_path).startswith(base_bot_path):
        raise ValueError("Directory traversal attempt blocked.")
    return full_path

def create_backup(bot_id: str) -> str | None:
    """Creates a backup of the bot's files."""
    try:
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        bot_path = get_bot_path(bot_id)
        if not os.path.exists(bot_path):
            return None
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(BACKUPS_DIR, f"{bot_id}_backup_{timestamp}")
        shutil.copytree(bot_path, backup_path)
        logger.info(f"Backup created for bot {bot_id} at {backup_path}")
        return backup_path
    except Exception as e:
        logger.error(f"Failed to create backup for bot {bot_id}: {e}")
        return None

def get_bot_size(bot_id: str) -> float:
    """Returns the size of a bot's directory in MB."""
    try:
        bot_path = get_bot_path(bot_id)
        if not os.path.exists(bot_path):
            return 0.0
            
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(bot_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
        return total_size / (1024 * 1024)
    except Exception as e:
        logger.error(f"Error calculating bot size: {e}")
        return 0.0