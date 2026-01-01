import os

# بوت التلغرام الأساسي
BOT_TOKEN = "8004754960:AAE_jGAX52F_vh7NwxI6nha94rngL6umy3U"
ADMIN_ID = 8049455831

# المسارات
BOTS_DIR = "hosted_bots"
CONFIG_FILE = "bots_config.json"
BACKUPS_DIR = "bot_backups"

# التأكد من وجود المجلدات
os.makedirs(BOTS_DIR, exist_ok=True)
os.makedirs(BACKUPS_DIR, exist_ok=True)