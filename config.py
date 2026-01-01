import os

# بوت التلغرام الأساسي
BOT_TOKEN = "8004754960:AAE_jGAX52F_vh7NwxI6nha94rngL6umy3U"
ADMIN_ID = 8049455831

# المسارات
BOTS_DIR = "hosted_bots"
CONFIG_FILE = "bots_config.json"
BACKUPS_DIR = "bot_backups"

# Webhook configuration (set USE_WEBHOOK=True and provide WEBHOOK_URL to enable)
USE_WEBHOOK = False
WEBHOOK_LISTEN = '0.0.0.0'
WEBHOOK_PORT = 8443
# المسار الذي يستقبل الويب هوك محلياً (يمكن ترك None لاستخدام التوكن كمسار)
WEBHOOK_PATH = None
# عنوان URL الخارجي (مثال: https://example.com/your-path) المطلوب لتسجيل الويب هوك على تلغرام
WEBHOOK_URL = None

# التأكد من وجود المجلدات
os.makedirs(BOTS_DIR, exist_ok=True)
os.makedirs(BACKUPS_DIR, exist_ok=True)