import os
import sys
import json
import shutil
import zipfile
import asyncio
import logging
import signal
import subprocess
import importlib.util
import threading
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

from pyrogram import Client, filters, types, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from pyrogram.errors import MessageNotModified

# ========================
# CONFIGURATION & SECURITY
# ========================
API_ID = 21576842  
API_HASH = "11a8869ea6ff51ab87bcf291101a8556"
BOT_TOKEN = "8004754960:AAE_jGAX52F_vh7NwxI6nha94rngL6umy3U"
ADMIN_IDS = [8049455831, 87654321]  

BASE_DIR = Path("hosted_bots")
BASE_DIR.mkdir(exist_ok=True)
CONFIG_FILE = "system_config.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========================
# HEALTH CHECK SERVER
# ========================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args): return

def run_health_server():
    try:
        server = HTTPServer(('0.0.0.0', 8000), HealthCheckHandler)
        server.serve_forever()
    except: pass

# ========================
# STATE MANAGEMENT
# ========================
class BotManager:
    def __init__(self):
        self.bots = {}
        self.config = self.load_config()
        self.app = Client("MasterBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f: return json.load(f)
        return {"active_bots": {}}

    def save_config(self):
        with open(CONFIG_FILE, "w") as f: json.dump(self.config, f, indent=4)

    async def install_dependencies(self, code_path):
        try:
            with open(code_path, "r", encoding="utf-8") as f: content = f.read()
            imports = [line.split()[1].split('.')[0] for line in content.splitlines() if line.startswith(("import ", "from "))]
            for pkg in set(imports):
                if pkg not in sys.modules and pkg not in ["os", "sys", "asyncio", "json", "pathlib", "threading"]:
                    subprocess.Popen([sys.executable, "-m", "pip", "install", pkg])
        except: pass

    async def start_bot_process(self, bot_id):
        bot_data = self.config["active_bots"].get(bot_id)
        if not bot_data: return False
        bot_dir = BASE_DIR / bot_id
        main_file = next(bot_dir.glob("*.py"), None)
        if not main_file: return False
        await self.install_dependencies(main_file)
        env = os.environ.copy()
        env["BOT_TOKEN"] = bot_data["token"]
        try:
            process = await asyncio.create_subprocess_exec(sys.executable, str(main_file), cwd=str(bot_dir), env=env)
            self.bots[bot_id] = {"process": process, "start_time": datetime.now().isoformat()}
            return True
        except: return False

    async def stop_bot_process(self, bot_id):
        if bot_id in self.bots:
            try:
                self.bots[bot_id]["process"].terminate()
                await self.bots[bot_id]["process"].wait()
            except: pass
            del self.bots[bot_id]
            return True
        return False

manager = BotManager()

# ========================
# UI & HANDLERS (ALL FEATURES PRESERVED)
# ========================
def main_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🤖 إدارة البوتات", callback_data="list_bots")],
                                 [InlineKeyboardButton("➕ رفع بوت جديد", callback_data="add_bot")],
                                 [InlineKeyboardButton("📊 حالة النظام", callback_data="system_status")]])

@manager.app.on_message(filters.command("start") & filters.user(ADMIN_IDS))
async def start_cmd(_, message: Message):
    await message.reply_text("👋 أهلاً بك في نظام استضافة البوتات.\nالمنصة الآن تعمل وتستجيب ✅", reply_markup=main_kb())

@manager.app.on_callback_query(filters.user(ADMIN_IDS))
async def cb_handler(client, query):
    data = query.data
    if data == "list_bots":
        btns = [[InlineKeyboardButton(f"{'🟢' if bid in manager.bots else '🔴'} {b['name']}", callback_data=f"manage_{bid}")] for bid, b in manager.config["active_bots"].items()]
        btns.append([InlineKeyboardButton("⬅ رجوع", callback_data="home")])
        await query.edit_message_text("قائمة البوتات:", reply_markup=InlineKeyboardMarkup(btns))
    elif data == "home":
        await query.edit_message_text("قائمة التحكم:", reply_markup=main_kb())
    elif data == "add_bot":
        await query.edit_message_text("📤 أرسل ملف البوت (.py أو .zip) الآن:")
    elif data.startswith("manage_"):
        bid = data.split("_")[1]
        is_run = bid in manager.bots
        txt = f"🤖 بوت: {manager.config['active_bots'][bid]['name']}\nالحالة: {'يعمل' if is_run else 'متوقف'}"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏹ إيقاف" if is_run else "▶ تشغيل", callback_data=f"toggle_{bid}")], [InlineKeyboardButton("⬅ رجوع", callback_data="list_bots")]]))
    elif data.startswith("toggle_"):
        bid = data.split("_")[1]
        if bid in manager.bots: await manager.stop_bot_process(bid)
        else: await manager.start_bot_process(bid)
        await cb_handler(client, query)

# ========================
# UPLOAD LOGIC
# ========================
@manager.app.on_message(filters.document & filters.user(ADMIN_IDS))
async def handle_upload(client, message):
    if not message.document.file_name.endswith(('.py', '.zip')): return
    bid = f"bot_{message.id}"
    bdir = BASE_DIR / bid
    bdir.mkdir(exist_ok=True)
    fpath = await message.download(str(bdir / message.document.file_name))
    if fpath.endswith('.zip'):
        with zipfile.ZipFile(fpath, 'r') as z: z.extractall(bdir)
        os.remove(fpath)
    tmsg = await message.reply("🔑 أرسل توكن البوت لتفعيله:", reply_markup=types.ForceReply(selective=True))
    @manager.app.on_message(filters.reply & filters.user(ADMIN_IDS), group=1)
    async def get_token(c, m):
        if m.reply_to_message.id == tmsg.id:
            manager.config["active_bots"][bid] = {"name": message.document.file_name, "token": m.text.strip()}
            manager.save_config()
            await m.reply("✅ تم التشغيل!", reply_markup=main_kb())
            await manager.start_bot_process(bid)

# ========================
# RUNTIME FIX
# ========================
async def main():
    # 1. Start Health Server
    threading.Thread(target=run_health_server, daemon=True).start()
    
    # 2. Start Client
    logger.info("Initializing Master Bot...")
    await manager.app.start()
    
    # 3. Resume bots
    for bid in manager.config["active_bots"]:
        await manager.start_bot_process(bid)
    
    logger.info("Platform is online and responding.")
    
    # 4. CRITICAL: Use idle() to keep the session alive
    await idle()
    
    # 5. Cleanup on exit
    await manager.app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass