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
from datetime import datetime
from pathlib import Path

from pyrogram import Client, filters, types
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from pyrogram.errors import MessageNotModified

# ========================
# CONFIGURATION & SECURITY
# ========================
# Replace with your actual credentials or set as environment variables
API_ID = 21576842  # Your API ID
API_HASH = "11a8869ea6ff51ab87bcf291101a8556"
BOT_TOKEN = "8004754960:AAE_jGAX52F_vh7NwxI6nha94rngL6umy3U"
ADMIN_IDS = [8049455831, 87654321]  # Whitelist of Telegram User IDs

# Constants
BASE_DIR = Path("hosted_bots")
BASE_DIR.mkdir(exist_ok=True)
CONFIG_FILE = "system_config.json"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========================
# STATE MANAGEMENT
# ========================
class BotManager:
    def __init__(self):
        self.bots = {}  # bot_id: {process, token, name, status, start_time}
        self.config = self.load_config()
        self.app = Client("MasterBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        return {"active_bots": {}}

    def save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=4)

    async def install_dependencies(self, code_path):
        """Attempts to parse imports and install them via pip."""
        try:
            with open(code_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            imports = []
            for line in lines:
                if line.startswith("import ") or line.startswith("from "):
                    pkg = line.split()[1].split('.')[0]
                    if pkg not in sys.modules and pkg not in ["os", "sys", "asyncio", "json", "pathlib", "time", "subprocess"]:
                        imports.append(pkg)
            
            for pkg in set(imports):
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
                except Exception as e:
                    logger.error(f"Failed to install {pkg}: {e}")
        except Exception as e:
            logger.error(f"Dep analysis failed: {e}")

    async def start_bot_process(self, bot_id):
        bot_data = self.config["active_bots"].get(bot_id)
        if not bot_data: return False

        bot_dir = BASE_DIR / bot_id
        main_file = bot_dir / "main.py"
        
        if not main_file.exists():
            # Fallback to the only .py file if main.py doesn't exist
            py_files = list(bot_dir.glob("*.py"))
            if not py_files: return False
            main_file = py_files[0]

        await self.install_dependencies(main_file)

        env = os.environ.copy()
        env["BOT_TOKEN"] = bot_data["token"]

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable, str(main_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(bot_dir),
                env=env
            )
            self.bots[bot_id] = {
                "process": process,
                "start_time": datetime.now().isoformat(),
                "status": "running"
            }
            return True
        except Exception as e:
            logger.error(f"Start failed for {bot_id}: {e}")
            return False

    async def stop_bot_process(self, bot_id):
        if bot_id in self.bots:
            proc = self.bots[bot_id]["process"]
            try:
                proc.terminate()
                await proc.wait()
            except:
                pass
            del self.bots[bot_id]
            return True
        return False

manager = BotManager()

# ========================
# KEYBOARDS
# ========================
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 إدارة البوتات", callback_data="list_bots")],
        [InlineKeyboardButton("➕ رفع بوت جديد", callback_data="add_bot")],
        [InlineKeyboardButton("📊 حالة النظام", callback_data="system_status")]
    ])

def bot_control_kb(bot_id, is_running):
    status_btn = InlineKeyboardButton("⏹ إيقاف" if is_running else "▶ تشغيل", 
                                      callback_data=f"toggle_{bot_id}")
    return InlineKeyboardMarkup([
        [status_btn, InlineKeyboardButton("🔄 تحديث", callback_data=f"restart_{bot_id}")],
        [InlineKeyboardButton("📁 إدارة الملفات", callback_data=f"files_{bot_id}_/")],
        [InlineKeyboardButton("📝 السجلات (Logs)", callback_data=f"logs_{bot_id}")],
        [InlineKeyboardButton("🗑 حذف البوت", callback_data=f"delete_confirm_{bot_id}")],
        [InlineKeyboardButton("⬅ رجوع", callback_data="list_bots")]
    ])

def file_manager_kb(bot_id, current_path):
    bot_dir = BASE_DIR / bot_id
    full_path = (bot_dir / current_path.strip("/")).resolve()
    
    # Sandboxing check
    if not str(full_path).startswith(str(bot_dir.resolve())):
        full_path = bot_dir

    buttons = []
    
    # List Directories first
    try:
        items = os.listdir(full_path)
        for item in sorted(items):
            item_path = full_path / item
            icon = "📁" if item_path.is_dir() else "📄"
            cb_path = f"{current_path.rstrip('/')}/{item}"
            buttons.append([InlineKeyboardButton(f"{icon} {item}", callback_data=f"files_{bot_id}_{cb_path}")])
    except:
        pass

    nav_btns = [InlineKeyboardButton("📤 رفع ملف", callback_data=f"upload_{bot_id}_{current_path}")]
    if current_path != "/":
        parent = "/".join(current_path.rstrip("/").split("/")[:-1]) or "/"
        nav_btns.append(InlineKeyboardButton("⬅ رجوع", callback_data=f"files_{bot_id}_{parent}"))
    else:
        nav_btns.append(InlineKeyboardButton("⬅ القائمة", callback_data=f"manage_{bot_id}"))
    
    buttons.append(nav_btns)
    return InlineKeyboardMarkup(buttons)

# ========================
# HANDLERS
# ========================
@manager.app.on_message(filters.command("start") & filters.user(ADMIN_IDS))
async def start_cmd(_, message: Message):
    await message.reply_text(
        "👋 أهلاً بك في نظام استضافة البوتات المتطور.\n\nاستخدم الأزرار أدناه للتحكم:",
        reply_markup=main_menu_kb()
    )

@manager.app.on_callback_query(filters.user(ADMIN_IDS))
async def cb_handler(client: Client, query: CallbackQuery):
    data = query.data
    
    if data == "list_bots":
        btns = []
        for bid, bdata in manager.config["active_bots"].items():
            status = "🟢" if bid in manager.bots else "🔴"
            btns.append([InlineKeyboardButton(f"{status} {bdata['name']}", callback_data=f"manage_{bid}")])
        btns.append([InlineKeyboardButton("⬅ رجوع", callback_data="back_main")])
        await query.edit_message_text("🤖 قائمة البوتات المستضافة:", reply_markup=InlineKeyboardMarkup(btns))

    elif data == "back_main":
        await query.edit_message_text("قائمة التحكم الرئيسية:", reply_markup=main_menu_kb())

    elif data == "add_bot":
        await query.edit_message_text("📤 من فضلك أرسل ملف البوت (.py أو .zip):")
        # Logic for file upload handled in message handler
        
    elif data.startswith("manage_"):
        bot_id = data.split("_")[1]
        bot_data = manager.config["active_bots"].get(bot_id)
        is_running = bot_id in manager.bots
        status_text = "متصل ✅" if is_running else "متوقف ❌"
        uptime = "N/A"
        if is_running:
            start = datetime.fromisoformat(manager.bots[bot_id]["start_time"])
            uptime = str(datetime.now() - start).split('.')[0]

        text = (f"🤖 **إدارة البوت:** {bot_data['name']}\n"
                f"🆔 **ID:** `{bot_id}`\n"
                f"📊 **الحالة:** {status_text}\n"
                f"⏱ **مدة التشغيل:** {uptime}")
        await query.edit_message_text(text, reply_markup=bot_control_kb(bot_id, is_running))

    elif data.startswith("toggle_"):
        bot_id = data.split("_")[1]
        if bot_id in manager.bots:
            await manager.stop_bot_process(bot_id)
            await query.answer("تم إيقاف البوت ⏹")
        else:
            success = await manager.start_bot_process(bot_id)
            await query.answer("تم تشغيل البوت ▶" if success else "فشل التشغيل ⚠️")
        await cb_handler(client, query) # Refresh

    elif data.startswith("files_"):
        parts = data.split("_")
        bot_id = parts[1]
        path = parts[2]
        await query.edit_message_text(f"📁 مدير الملفات: `{path}`", reply_markup=file_manager_kb(bot_id, path))

    elif data.startswith("logs_"):
        bot_id = data.split("_")[1]
        if bot_id in manager.bots:
            proc = manager.bots[bot_id]["process"]
            # Simplified: just showing status. Real log streaming requires reading the pipe.
            await query.answer("سجلات البوت تعمل في الخلفية...", show_alert=True)
        else:
            await query.answer("البوت متوقف، لا توجد سجلات حالية.", show_alert=True)

    elif data == "system_status":
        total_bots = len(manager.config["active_bots"])
        running = len(manager.bots)
        usage = shutil.disk_usage("/")
        text = (f"📊 **حالة النظام**\n\n"
                f"🤖 إجمالي البوتات: {total_bots}\n"
                f"🟢 نشط الآن: {running}\n"
                f"💽 المساحة: {usage.used // (2**30)}GB / {usage.total // (2**30)}GB")
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ رجوع", callback_data="back_main")]]))

# ========================
# UPLOAD LOGIC
# ========================
@manager.app.on_message(filters.document & filters.user(ADMIN_IDS))
async def handle_upload(client: Client, message: Message):
    if not message.document.file_name.endswith(('.py', '.zip')):
        return await message.reply("❌ الملف غير مدعوم. أرسل .py أو .zip")

    status_msg = await message.reply("⏳ معالجة الملف...")
    bot_id = f"bot_{message.id}"
    bot_dir = BASE_DIR / bot_id
    bot_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = await message.download(file_name=str(bot_dir / message.document.file_name))
    
    if message.document.file_name.endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(bot_dir)
        os.remove(file_path)
    elif message.document.file_name != "main.py":
        os.rename(file_path, bot_dir / "main.py")

    # Ask for Token
    await status_msg.delete()
    token_msg = await message.reply("🔑 أرسل توكن البوت لتفعيله:", reply_markup=types.ForceReply(selective=True))
    
    # Store temporary state for token response
    # In a real app, use a proper state machine
    @manager.app.on_message(filters.reply & filters.user(ADMIN_IDS), group=1)
    async def get_token(c, m: Message):
        if m.reply_to_message.id == token_msg.id:
            token = m.text.strip()
            manager.config["active_bots"][bot_id] = {
                "name": message.document.file_name,
                "token": token,
                "added_at": datetime.now().isoformat()
            }
            manager.save_config()
            await m.reply(f"✅ تم الإعداد بنجاح! معرف البوت: `{bot_id}`", reply_markup=main_menu_kb())
            await manager.start_bot_process(bot_id)

# ========================
# RUNTIME
# ========================
async def main():
    logger.info("Starting Master Hosting Bot...")
    await manager.app.start()
    
    # Auto-resume bots
    for bot_id in manager.config["active_bots"]:
        logger.info(f"Resuming bot: {bot_id}")
        await manager.start_bot_process(bot_id)
        
    logger.info("Platform is online.")
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass