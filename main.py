import os
import json
import asyncio
import zipfile
import shutil
import sys
import subprocess
import logging
import re
import time
from functools import wraps
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8004754960:AAE_jGAX52F_vh7NwxI6nha94rngL6umy3U"
ADMIN_ID = 8049455831
BOTS_DIR = "hosted_bots"
CONFIG_FILE = "bots_config.json"
BACKUPS_DIR = "bot_backups"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_CONFIG = {}
FILE_MANAGER_STATE = {}
BOT_STATS = {}

def find_token_in_files(path: str) -> str | None:
    """Searches for a Telegram bot token pattern in .py files within the given path."""
    TOKEN_PATTERN = re.compile(r'(\d+:[a-zA-Z0-9_-]{20,})')
    
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

def load_config():
    """Loads bot configuration from the JSON file."""
    global BOT_CONFIG
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            BOT_CONFIG = {k: v for k, v in data.items()}
        logger.info(f"Loaded {len(BOT_CONFIG)} bots from config.")
    else:
        BOT_CONFIG = {}

def save_config():
    """Saves bot configuration to the JSON file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(BOT_CONFIG, f, indent=4)
    logger.info("Bot configuration saved.")

def admin_only(func):
    """Decorator to restrict access to admin users."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            await update.effective_message.reply_text("🚫 أنت لست المسؤول. لا يمكنك استخدام هذا البوت.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def get_bot_path(bot_id: str, sub_path: str = "") -> str:
    """Returns the absolute sandboxed path for a bot."""
    if '..' in sub_path or sub_path.startswith('/'):
        raise ValueError("Invalid path segment.")
    full_path = os.path.join(BOTS_DIR, bot_id, sub_path)
    if not os.path.abspath(full_path).startswith(os.path.abspath(os.path.join(BOTS_DIR, bot_id))):
        raise ValueError("Directory traversal attempt blocked.")
    return full_path

def create_backup(bot_id: str) -> str | None:
    """Creates a backup of the bot's files."""
    try:
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        bot_path = get_bot_path(bot_id)
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

class BotProcessManager:
    """Manages the lifecycle and state of a single hosted bot."""
    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self.config = BOT_CONFIG[bot_id]
        self.process = None
        self.log_buffer = []
        self.log_task = None
        self.start_time = None
        
    async def start(self):
        """Starts the bot process."""
        if self.process and self.process.returncode is None:
            return "البوت قيد التشغيل بالفعل."

        try:
            bot_root = get_bot_path(self.bot_id)
            main_script = next((f for f in os.listdir(bot_root) if f.endswith('.py')), None)
            
            if not main_script:
                self.config['status'] = 'error'
                save_config()
                return "❌ لم يتم العثور على ملف بايثون رئيسي لتشغيله."

            script_path = os.path.join(bot_root, main_script)
            
            env = os.environ.copy()
            env['BOT_TOKEN'] = self.config['token']
            
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, script_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=bot_root,
                env=env
            )
            
            self.config['status'] = 'running'
            self.config['pid'] = self.process.pid
            self.start_time = time.time()
            self.config['start_time'] = self.start_time
            save_config()
            
            self.log_task = asyncio.create_task(self._capture_logs())
            asyncio.create_task(self._monitor_process())
            
            return f"✅ تم تشغيل البوت بنجاح. PID: {self.process.pid}"
            
        except Exception as e:
            logger.error(f"Error starting bot {self.bot_id}: {e}")
            self.config['status'] = 'error'
            save_config()
            return f"❌ فشل تشغيل البوت: {e}"

    async def stop(self):
        """Stops the bot process."""
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                await self.process.wait()
                self.config['status'] = 'stopped'
                self.config['pid'] = None
                save_config()
                if self.log_task:
                    self.log_task.cancel()
                return "⏹ تم إيقاف البوت بنجاح."
            except Exception as e:
                return f"❌ فشل إيقاف البوت: {e}"
        return "البوت متوقف بالفعل."

    async def restart(self):
        """Restarts the bot process."""
        await self.stop()
        await asyncio.sleep(1)
        return await self.start()

    async def _capture_logs(self):
        """Captures stdout and stderr from the running process."""
        while self.process and self.process.returncode is None:
            try:
                stdout_line = await asyncio.wait_for(self.process.stdout.readline(), timeout=0.1)
                stderr_line = await asyncio.wait_for(self.process.stderr.readline(), timeout=0.1)
                
                if stdout_line:
                    line = stdout_line.decode().strip()
                    self.log_buffer.append(f"[STDOUT] {line}")
                if stderr_line:
                    line = stderr_line.decode().strip()
                    self.log_buffer.append(f"[STDERR] {line}")
                    
                if len(self.log_buffer) > 500:
                    self.log_buffer = self.log_buffer[-500:]
                    
            except asyncio.TimeoutError:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Log capture error for {self.bot_id}: {e}")
                break

    async def _monitor_process(self):
        """Monitors the process and handles auto-restart on crash."""
        await self.process.wait()
        
        return_code = self.process.returncode
        
        if return_code != 0:
            logger.warning(f"Bot {self.bot_id} crashed with code {return_code}. Attempting auto-restart.")
            self.config['status'] = 'crashed'
            save_config()
            
            await asyncio.sleep(5) 
            
            if self.config.get('auto_restart', True):
                await self.start()
                
        else:
            self.config['status'] = 'stopped'
            self.config['pid'] = None
            save_config()
            
    def get_logs(self, limit: int = 50) -> str:
        """Returns the last N lines of the bot's logs."""
        return "\n".join(self.log_buffer[-limit:])
    
    def get_uptime(self) -> str:
        """Returns the bot's uptime as a formatted string."""
        if not self.start_time:
            return "N/A"
        uptime_seconds = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"

ACTIVE_MANAGERS = {}

def get_manager(bot_id: str) -> BotProcessManager:
    """Gets or creates a BotProcessManager instance for a bot."""
    if bot_id not in ACTIVE_MANAGERS:
        if bot_id not in BOT_CONFIG:
            raise ValueError(f"Bot ID {bot_id} not found.")
        
        manager = BotProcessManager(bot_id)
        ACTIVE_MANAGERS[bot_id] = manager
        
        if BOT_CONFIG[bot_id]['status'] == 'running':
            asyncio.create_task(manager.start())
            
    return ACTIVE_MANAGERS[bot_id]

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Generates the main menu keyboard."""
    keyboard = [
        [InlineKeyboardButton("➕ رفع بوت جديد", callback_data="UPLOAD_BOT")],
        [InlineKeyboardButton("🤖 إدارة البوتات", callback_data="BOT_LIST")],
        [InlineKeyboardButton("📊 حالة النظام العامة", callback_data="SYSTEM_STATUS")],
        [InlineKeyboardButton("💾 النسخ الاحتياطية", callback_data="BACKUPS_LIST")],
    ]
    return InlineKeyboardMarkup(keyboard)

@admin_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command."""
    await update.message.reply_text(
        "👋 مرحباً بك في منصة استضافة البوتات المتقدمة (Advanced Bot Hosting Platform).\n\n"
        "يرجى اختيار الإجراء:",
        reply_markup=get_main_menu_keyboard()
    )

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Returns to the main menu by editing the current message."""
    query = update.callback_query
    await query.answer()
    
    text = "👋 مرحباً بك في منصة استضافة البوتات المتقدمة (Advanced Bot Hosting Platform).\n\n" \
           "يرجى اختيار الإجراء:"
           
    await query.edit_message_text(
        text=text,
        reply_markup=get_main_menu_keyboard()
    )

def get_bot_list_keyboard() -> InlineKeyboardMarkup:
    """Generates the list of hosted bots keyboard."""
    keyboard = []
    for bot_id, config in BOT_CONFIG.items():
        status_emoji = "🟢" if config.get('status') == 'running' else "🔴"
        keyboard.append([
            InlineKeyboardButton(f"{status_emoji} {config.get('name', bot_id)}", callback_data=f"BOT_PANEL|{bot_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("⬅ رجوع", callback_data="MAIN_MENU")])
    return InlineKeyboardMarkup(keyboard)

async def bot_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the list of hosted bots."""
    query = update.callback_query
    await query.answer()
    
    text = "🤖 قائمة البوتات المستضافة:\n\n"
    if not BOT_CONFIG:
        text += "لا توجد بوتات مستضافة حالياً. استخدم '➕ رفع بوت جديد' للبدء."
        
    await query.edit_message_text(
        text=text,
        reply_markup=get_bot_list_keyboard()
    )

def get_bot_panel_keyboard(bot_id: str) -> tuple[str, InlineKeyboardMarkup]:
    """Generates the control panel for a specific bot."""
    config = BOT_CONFIG.get(bot_id, {})
    status = config.get('status', 'stopped')
    name = config.get('name', bot_id)
    status_emoji = "🟢" if status == 'running' else ("🔴" if status == 'stopped' else "🟡")
    
    manager = get_manager(bot_id)
    uptime = manager.get_uptime()
    bot_size = get_bot_size(bot_id)
    
    keyboard = [
        [InlineKeyboardButton(f"📁 إدارة الملفات", callback_data=f"FILE_MANAGER|{bot_id}|.")],
        [InlineKeyboardButton(f"📄 عرض السجلات", callback_data=f"VIEW_LOGS|{bot_id}")],
        [InlineKeyboardButton(f"🔄 تحديث (إعادة تشغيل)", callback_data=f"RESTART_BOT|{bot_id}")],
        [InlineKeyboardButton(f"💾 نسخ احتياطي", callback_data=f"BACKUP_BOT|{bot_id}")],
        [InlineKeyboardButton(f"🗑 حذف البوت", callback_data=f"DELETE_BOT_CONFIRM|{bot_id}")],
        [InlineKeyboardButton(f"⬅ رجوع", callback_data="BOT_LIST")]
    ]
    
    if status == 'running':
        keyboard.insert(0, [InlineKeyboardButton("⏹ إيقاف", callback_data=f"STOP_BOT|{bot_id}")])
    else:
        keyboard.insert(0, [InlineKeyboardButton("▶ تشغيل", callback_data=f"START_BOT|{bot_id}")])
        
    text = f"⚙️ لوحة تحكم البوت: **{name}**\n" \
           f"الحالة: {status_emoji} {status.upper()}\n" \
           f"المسار: {get_bot_path(bot_id)}\n" \
           f"PID: {config.get('pid', 'N/A')}\n" \
           f"وقت التشغيل: {uptime}\n" \
           f"حجم البوت: {bot_size:.2f} MB"
           
    return text, InlineKeyboardMarkup(keyboard)

async def bot_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the control panel for a specific bot."""
    query = update.callback_query
    await query.answer()
    
    bot_id = query.data.split('|')[1]
    
    if bot_id not in BOT_CONFIG:
        await query.edit_message_text("❌ البوت غير موجود.")
        return
        
    text, keyboard = get_bot_panel_keyboard(bot_id)
    
    await query.edit_message_text(
        text=text,
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

async def handle_bot_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles start, stop, and restart actions."""
    query = update.callback_query
    await query.answer()
    
    action, bot_id = query.data.split('|')
    
    if bot_id not in BOT_CONFIG:
        await query.edit_message_text("❌ البوت غير موجود.")
        return
        
    manager = get_manager(bot_id)
    
    message = ""
    if action == "START_BOT":
        message = await manager.start()
    elif action == "STOP_BOT":
        message = await manager.stop()
    elif action == "RESTART_BOT":
        message = await manager.restart()
        
    text, keyboard = get_bot_panel_keyboard(bot_id)
    await query.edit_message_text(
        text=f"{text}\n\n--- رسالة النظام ---\n{message}",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

async def backup_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Creates a backup of the bot."""
    query = update.callback_query
    await query.answer("جاري إنشاء النسخة الاحتياطية...")
    
    bot_id = query.data.split('|')[1]
    
    if bot_id not in BOT_CONFIG:
        await query.edit_message_text("❌ البوت غير موجود.")
        return
    
    backup_path = create_backup(bot_id)
    
    if backup_path:
        await query.edit_message_text(
            text=f"✅ تم إنشاء نسخة احتياطية بنجاح.\nالمسار: `{backup_path}`",
            reply_markup=get_bot_list_keyboard(),
            parse_mode='Markdown'
        )
    else:
        await query.edit_message_text(
            text="❌ فشل إنشاء النسخة الاحتياطية.",
            reply_markup=get_bot_list_keyboard()
        )

async def delete_bot_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Asks for confirmation before deleting a bot."""
    query = update.callback_query
    await query.answer()
    
    bot_id = query.data.split('|')[1]
    name = BOT_CONFIG[bot_id].get('name', bot_id)
    
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد الحذف", callback_data=f"DELETE_BOT|{bot_id}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"BOT_PANEL|{bot_id}")]
    ]
    
    await query.edit_message_text(
        text=f"⚠️ **تحذير!** هل أنت متأكد من حذف البوت **{name}**؟\n"
             "سيتم إيقاف البوت وحذف جميع ملفاته نهائياً.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def delete_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deletes the bot and its files."""
    query = update.callback_query
    await query.answer()
    
    bot_id = query.data.split('|')[1]
    
    if bot_id not in BOT_CONFIG:
        await query.edit_message_text("❌ البوت غير موجود.")
        return
        
    manager = get_manager(bot_id)
    await manager.stop()
    
    bot_path = get_bot_path(bot_id)
    try:
        shutil.rmtree(bot_path)
        del BOT_CONFIG[bot_id]
        if bot_id in ACTIVE_MANAGERS:
            del ACTIVE_MANAGERS[bot_id]
            
        save_config()
        
        await query.edit_message_text(
            text=f"🗑 تم حذف البوت **{bot_id}** وجميع ملفاته بنجاح.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await query.edit_message_text(
            text=f"❌ فشل حذف ملفات البوت: {e}",
            reply_markup=get_bot_list_keyboard()
        )

async def view_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the last 50 lines of the bot's logs."""
    query = update.callback_query
    await query.answer()
    
    bot_id = query.data.split('|')[1]
    
    if bot_id not in BOT_CONFIG:
        await query.edit_message_text("❌ البوت غير موجود.")
        return
        
    manager = get_manager(bot_id)
    logs = manager.get_logs(limit=50)
    
    if not logs:
        logs = "لا توجد سجلات حالياً."
        
    text = f"📄 سجلات البوت **{BOT_CONFIG[bot_id].get('name', bot_id)}** (آخر 50 سطر):\n\n" \
           f"```\n{logs}\n```"
           
    keyboard = [
        [InlineKeyboardButton("🔄 تحديث السجلات", callback_data=f"VIEW_LOGS|{bot_id}")],
        [InlineKeyboardButton("⬅ رجوع للوحة التحكم", callback_data=f"BOT_PANEL|{bot_id}")]
    ]
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def upload_bot_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompts the user to upload a file and set the state."""
    query = update.callback_query
    await query.answer()
    
    context.user_data['state'] = 'AWAITING_BOT_FILE'
    
    keyboard = [
        [InlineKeyboardButton("❌ إلغاء", callback_data="MAIN_MENU")]
    ]
    
    await query.edit_message_text(
        text="📤 يرجى الآن إرسال ملف البوت:\n"
             "1. ملف بايثون واحد (.py) \n"
             "2. أو ملف مضغوط (.zip) يحتوي على ملفات البوت.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_bot_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the uploaded file and checks for token automatically."""
    if context.user_data.get('state') != 'AWAITING_BOT_FILE':
        return
        
    message = update.message
    
    if not message.document:
        await message.reply_text("❌ يرجى إرسال ملف (py. أو zip.) وليس نصاً.")
        return
        
    file_id = message.document.file_id
    file_name = message.document.file_name
    
    if not (file_name.endswith('.py') or file_name.endswith('.zip')):
        await message.reply_text("❌ صيغة الملف غير مدعومة. يرجى إرسال ملف .py أو .zip.")
        return
        
    new_file = await context.bot.get_file(file_id)
    temp_path = os.path.join(BOTS_DIR, f"temp_{message.from_user.id}_{file_name}")
    await new_file.download_to_drive(custom_path=temp_path)
    
    context.user_data['temp_bot_file'] = temp_path
    context.user_data['bot_name'] = file_name.replace('.py', '').replace('.zip', '')
    
    found_token = find_token_in_files(temp_path)
    
    if found_token:
        context.user_data['state'] = 'AWAITING_BOT_TOKEN'
        context.user_data['found_token'] = found_token
        
        await message.reply_text(
            f"✅ تم استقبال الملف: **{file_name}**\n"
            f"✅ تم العثور على التوكن تلقائياً في الملفات!\n\n"
            f"التوكن المكتشف: `{found_token[:10]}...`\n\n"
            f"اختر:\n"
            f"1️⃣ أرسل 'نعم' أو 'yes' لاستخدام التوكن المكتشف\n"
            f"2️⃣ أرسل توكن مختلف إذا أردت تغييره",
            parse_mode='Markdown'
        )
    else:
        context.user_data['state'] = 'AWAITING_BOT_TOKEN'
        await message.reply_text(
            f"✅ تم استقبال الملف: **{file_name}**\n\n"
            "❌ لم يتم العثور على توكن في الملفات.\n"
            "يرجى إرسال **توكن (Token)** البوت الجديد يدوياً.\n"
            "ملاحظة: التوكن لن يظهر في سجلات الدردشة.",
            parse_mode='Markdown'
        )

async def handle_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the bot token and finalizes deployment."""
    if context.user_data.get('state') != 'AWAITING_BOT_TOKEN':
        return
        
    user_input = update.message.text.strip().lower()
    temp_path = context.user_data.get('temp_bot_file')
    bot_name = context.user_data.get('bot_name')
    found_token = context.user_data.get('found_token')
    
    if not temp_path:
        await update.message.reply_text("❌ حدث خطأ في عملية الرفع. يرجى البدء من جديد.", reply_markup=get_main_menu_keyboard())
        context.user_data.clear()
        return
    
    if found_token and user_input in ['نعم', 'yes', 'y', 'ن']:
        token = found_token
    else:
        token = user_input
    
    if not (token.split(':')[0].isdigit() and ':' in token and len(token.split(':')[-1]) > 10):
        await update.message.reply_text("❌ التوكن المدخل لا يبدو صحيحاً. يرجى إرسال التوكن الصحيح.")
        return
        
    bot_id = token.split(':')[0]
    
    if bot_id in BOT_CONFIG:
        await update.message.reply_text(f"❌ البوت بهذا التوكن ({bot_id}) موجود بالفعل. يرجى استخدام توكن آخر أو حذف البوت الحالي.", reply_markup=get_main_menu_keyboard())
        if os.path.exists(temp_path):
            os.remove(temp_path)
        context.user_data.clear()
        return
        
    bot_root = get_bot_path(bot_id)
    os.makedirs(bot_root, exist_ok=True)
    
    try:
        if temp_path.endswith('.zip'):
            with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                zip_ref.extractall(bot_root)
            message_text = f"✅ تم استخراج ملفات البوت **{bot_name}** بنجاح."
        else:
            shutil.move(temp_path, os.path.join(bot_root, f"{bot_name}.py"))
            message_text = f"✅ تم رفع ملف البوت **{bot_name}** بنجاح."
            
        BOT_CONFIG[bot_id] = {
            'name': bot_name,
            'token': token,
            'directory': bot_root,
            'status': 'stopped',
            'pid': None,
            'auto_restart': True,
            'created_at': datetime.now().isoformat()
        }
        save_config()
        
        context.user_data.clear()
        
        manager = get_manager(bot_id)
        start_result = await manager.start()
        
        text, keyboard = get_bot_panel_keyboard(bot_id)
        await update.message.reply_text(
            text=f"{message_text}\n\n{text}\n\n--- رسالة النظام ---\n{start_result}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Deployment error for bot {bot_id}: {e}")
        if os.path.exists(bot_root):
            shutil.rmtree(bot_root)
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        await update.message.reply_text(f"❌ فشل نشر البوت: {e}", reply_markup=get_main_menu_keyboard())
        context.user_data.clear()

def get_file_manager_keyboard(bot_id: str, current_path: str) -> tuple[str, InlineKeyboardMarkup]:
    """Generates the file manager keyboard for a specific path."""
    try:
        abs_path = get_bot_path(bot_id, current_path)
    except ValueError:
        abs_path = get_bot_path(bot_id)
        current_path = "."
        
    if not os.path.isdir(abs_path):
        abs_path = get_bot_path(bot_id)
        current_path = "."
        
    items = sorted(os.listdir(abs_path))
    
    keyboard = []
    
    for item in items:
        item_path = os.path.join(abs_path, item)
        is_dir = os.path.isdir(item_path)
        emoji = "📁" if is_dir else "📄"
        
        new_rel_path = os.path.join(current_path, item)
        
        if is_dir:
            callback_data = f"FILE_MANAGER|{bot_id}|{new_rel_path}"
        else:
            callback_data = f"FILE_ACTIONS|{bot_id}|{new_rel_path}"
            
        keyboard.append([InlineKeyboardButton(f"{emoji} {item}", callback_data=callback_data)])
        
    control_buttons = [
        InlineKeyboardButton("📤 رفع ملف", callback_data=f"FM_UPLOAD_PROMPT|{bot_id}|{current_path}"),
        InlineKeyboardButton("📂 إنشاء مجلد", callback_data=f"FM_CREATE_DIR_PROMPT|{bot_id}|{current_path}")
    ]
    
    nav_buttons = []
    if current_path != ".":
        parent_path = os.path.dirname(current_path) or "."
        nav_buttons.append(InlineKeyboardButton("⬆️ مجلد أب", callback_data=f"FILE_MANAGER|{bot_id}|{parent_path}"))
        
    nav_buttons.append(InlineKeyboardButton("⬅ رجوع للوحة التحكم", callback_data=f"BOT_PANEL|{bot_id}"))
    
    keyboard.append(control_buttons)
    keyboard.append(nav_buttons)
    
    text = f"📂 مدير الملفات: **{BOT_CONFIG[bot_id].get('name', bot_id)}**\n" \
           f"المسار الحالي: `{current_path}`"
           
    return text, InlineKeyboardMarkup(keyboard)

async def file_manager_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the file manager interface."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('|')
    bot_id = parts[1]
    current_path = parts[2]
    
    FILE_MANAGER_STATE[query.from_user.id] = {'bot_id': bot_id, 'path': current_path}
    
    try:
        text, keyboard = get_file_manager_keyboard(bot_id, current_path)
        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"File manager error: {e}")
        await query.edit_message_text(
            text=f"❌ حدث خطأ في مدير الملفات: {e}",
            reply_markup=get_bot_panel_keyboard(bot_id)[1]
        )

async def file_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays actions for a specific file."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('|')
    bot_id = parts[1]
    file_path = parts[2]
    
    abs_path = get_bot_path(bot_id, file_path)
    
    keyboard = [
        [InlineKeyboardButton("⬇️ تحميل الملف", callback_data=f"FM_DOWNLOAD|{bot_id}|{file_path}")],
        [InlineKeyboardButton("🗑 حذف الملف", callback_data=f"FM_DELETE_CONFIRM|{bot_id}|{file_path}")],
        [InlineKeyboardButton("⬅ رجوع", callback_data=f"FILE_MANAGER|{bot_id}|{os.path.dirname(file_path) or '.'}")]
    ]
    
    await query.edit_message_text(
        text=f"📄 خيارات الملف: `{file_path}`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def fm_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the file to the user for download."""
    query = update.callback_query
    await query.answer("جاري تجهيز الملف للتحميل...")
    
    parts = query.data.split('|')
    bot_id = parts[1]
    file_path = parts[2]
    
    abs_path = get_bot_path(bot_id, file_path)
    
    try:
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=abs_path,
            caption=f"⬇️ ملف البوت: `{file_path}`"
        )
        await file_actions_callback(update, context)
        
    except Exception as e:
        await query.edit_message_text(f"❌ فشل تحميل الملف: {e}")

async def fm_delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Asks for confirmation before deleting a file/folder."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('|')
    bot_id = parts[1]
    item_path = parts[2]
    
    abs_path = get_bot_path(bot_id, item_path)
    is_dir = os.path.isdir(abs_path)
    
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد الحذف", callback_data=f"FM_DELETE|{bot_id}|{item_path}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"FILE_ACTIONS|{bot_id}|{item_path}")]
    ]
    
    item_type = "المجلد" if is_dir else "الملف"
    
    await query.edit_message_text(
        text=f"⚠️ **تحذير!** هل أنت متأكد من حذف {item_type} **{item_path}**؟\n"
             "سيتم حذف المحتوى نهائياً.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def fm_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deletes the file or folder."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('|')
    bot_id = parts[1]
    item_path = parts[2]
    
    abs_path = get_bot_path(bot_id, item_path)
    parent_path = os.path.dirname(item_path) or "."
    
    try:
        if os.path.isdir(abs_path):
            shutil.rmtree(abs_path)
            message = f"🗑 تم حذف المجلد **{item_path}** بنجاح."
        else:
            os.remove(abs_path)
            message = f"🗑 تم حذف الملف **{item_path}** بنجاح."
            
        query.data = f"FILE_MANAGER|{bot_id}|{parent_path}"
        await file_manager_callback(update, context)
        await query.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        await query.edit_message_text(f"❌ فشل حذف الملف/المجلد: {e}")

async def fm_upload_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompts the user to upload a file to the current directory."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('|')
    bot_id = parts[1]
    current_path = parts[2]
    
    context.user_data['state'] = 'FM_AWAITING_FILE'
    context.user_data['fm_target_bot'] = bot_id
    context.user_data['fm_target_path'] = current_path
    
    keyboard = [
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"FILE_MANAGER|{bot_id}|{current_path}")]
    ]
    
    await query.edit_message_text(
        text=f"📤 يرجى إرسال الملف الذي تريد رفعه إلى المسار:\n`{current_path}`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def fm_create_dir_prompt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompts the user to enter a new directory name."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('|')
    bot_id = parts[1]
    current_path = parts[2]
    
    context.user_data['state'] = 'FM_AWAITING_DIR_NAME'
    context.user_data['fm_target_bot'] = bot_id
    context.user_data['fm_target_path'] = current_path
    
    keyboard = [
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"FILE_MANAGER|{bot_id}|{current_path}")]
    ]
    
    await query.edit_message_text(
        text=f"📂 يرجى إرسال اسم المجلد الجديد الذي تريد إنشاءه في المسار:\n`{current_path}`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_file_manager_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text input for file manager operations."""
    state = context.user_data.get('state')
    bot_id = context.user_data.get('fm_target_bot')
    current_path = context.user_data.get('fm_target_path')
    
    if state != 'FM_AWAITING_DIR_NAME':
        return
        
    dir_name = update.message.text.strip()
    
    if not dir_name:
        await update.message.reply_text("❌ الاسم لا يمكن أن يكون فارغاً.")
        return
        
    if any(c in dir_name for c in ['/', '\\', '..']):
        await update.message.reply_text("❌ اسم المجلد يحتوي على أحرف غير مسموح بها.")
        return
        
    try:
        abs_path = get_bot_path(bot_id, os.path.join(current_path, dir_name))
        os.makedirs(abs_path, exist_ok=True)
        
        await update.message.reply_text(f"✅ تم إنشاء المجلد **{dir_name}** بنجاح.", parse_mode='Markdown')
        
        context.user_data.clear()
        update.callback_query = type('obj', (object,), {'data': f"FILE_MANAGER|{bot_id}|{current_path}", 'answer': lambda *args, **kwargs: asyncio.sleep(0)})()
        await file_manager_callback(update, context)
        
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إنشاء المجلد: {e}")

async def handle_file_manager_file_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles file input for file manager operations."""
    state = context.user_data.get('state')
    bot_id = context.user_data.get('fm_target_bot')
    current_path = context.user_data.get('fm_target_path')
    
    if state != 'FM_AWAITING_FILE':
        return
        
    message = update.message
    
    if not message.document:
        await message.reply_text("❌ يرجى إرسال ملف.")
        return
        
    file_id = message.document.file_id
    file_name = message.document.file_name
    
    try:
        new_file = await context.bot.get_file(file_id)
        target_path = get_bot_path(bot_id, os.path.join(current_path, file_name))
        await new_file.download_to_drive(custom_path=target_path)
        
        await message.reply_text(f"✅ تم رفع الملف **{file_name}** بنجاح إلى المسار:\n`{current_path}`", parse_mode='Markdown')
        
        context.user_data.clear()
        update.callback_query = type('obj', (object,), {'data': f"FILE_MANAGER|{bot_id}|{current_path}", 'answer': lambda *args, **kwargs: asyncio.sleep(0)})()
        await file_manager_callback(update, context)
        
    except Exception as e:
        await message.reply_text(f"❌ فشل رفع الملف: {e}")

async def system_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays global system status."""
    query = update.callback_query
    await query.answer()
    
    total_bots = len(BOT_CONFIG)
    running_bots = sum(1 for config in BOT_CONFIG.values() if config.get('status') == 'running')
    
    total_size = 0
    if os.path.exists(BOTS_DIR):
        for dirpath, dirnames, filenames in os.walk(BOTS_DIR):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
    
    total_size_mb = total_size / (1024 * 1024)
    
    status_text = f"📊 **حالة النظام العامة**\n\n" \
                  f"عدد البوتات المستضافة: {total_bots}\n" \
                  f"البوتات قيد التشغيل: {running_bots}\n" \
                  f"إجمالي مساحة التخزين: {total_size_mb:.2f} ميغابايت\n\n" \
                  f"--- حالة البوتات ---\n"
                  
    for bot_id, config in BOT_CONFIG.items():
        status_emoji = "🟢" if config.get('status') == 'running' else "🔴"
        status_text += f"{status_emoji} {config.get('name', bot_id)} (PID: {config.get('pid', 'N/A')})\n"
        
    keyboard = [
        [InlineKeyboardButton("🔄 تحديث", callback_data="SYSTEM_STATUS")],
        [InlineKeyboardButton("⬅ رجوع", callback_data="MAIN_MENU")]
    ]
    
    await query.edit_message_text(
        text=status_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def backups_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the list of available backups."""
    query = update.callback_query
    await query.answer()
    
    if not os.path.exists(BACKUPS_DIR):
        text = "💾 لا توجد نسخ احتياطية حالياً."
    else:
        backups = os.listdir(BACKUPS_DIR)
        if not backups:
            text = "💾 لا توجد نسخ احتياطية حالياً."
        else:
            text = "💾 النسخ الاحتياطية المتاحة:\n\n"
            for backup in sorted(backups, reverse=True)[:10]:
                text += f"📦 {backup}\n"
    
    keyboard = [
        [InlineKeyboardButton("⬅ رجوع", callback_data="MAIN_MENU")]
    ]
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main() -> None:
    """Start the bot."""
    os.makedirs(BOTS_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    load_config()
    
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^MAIN_MENU$"))
    application.add_handler(CallbackQueryHandler(bot_list_callback, pattern="^BOT_LIST$"))
    application.add_handler(CallbackQueryHandler(bot_panel_callback, pattern="^BOT_PANEL\|"))
    application.add_handler(CallbackQueryHandler(system_status_callback, pattern="^SYSTEM_STATUS$"))
    application.add_handler(CallbackQueryHandler(backups_list_callback, pattern="^BACKUPS_LIST$"))
    
    application.add_handler(CallbackQueryHandler(handle_bot_action, pattern="^(START_BOT|STOP_BOT|RESTART_BOT)\|"))
    application.add_handler(CallbackQueryHandler(delete_bot_confirm_callback, pattern="^DELETE_BOT_CONFIRM\|"))
    application.add_handler(CallbackQueryHandler(delete_bot_callback, pattern="^DELETE_BOT\|"))
    application.add_handler(CallbackQueryHandler(view_logs_callback, pattern="^VIEW_LOGS\|"))
    application.add_handler(CallbackQueryHandler(backup_bot_callback, pattern="^BACKUP_BOT\|"))
    
    application.add_handler(CallbackQueryHandler(upload_bot_prompt_callback, pattern="^UPLOAD_BOT$"))
    
    application.add_handler(CallbackQueryHandler(file_manager_callback, pattern="^FILE_MANAGER\|"))
    application.add_handler(CallbackQueryHandler(file_actions_callback, pattern="^FILE_ACTIONS\|"))
    application.add_handler(CallbackQueryHandler(fm_download_callback, pattern="^FM_DOWNLOAD\|"))
    application.add_handler(CallbackQueryHandler(fm_delete_confirm_callback, pattern="^FM_DELETE_CONFIRM\|"))
    application.add_handler(CallbackQueryHandler(fm_delete_callback, pattern="^FM_DELETE\|"))
    application.add_handler(CallbackQueryHandler(fm_upload_prompt_callback, pattern="^FM_UPLOAD_PROMPT\|"))
    application.add_handler(CallbackQueryHandler(fm_create_dir_prompt_callback, pattern="^FM_CREATE_DIR_PROMPT\|"))
    
    application.add_handler(MessageHandler(filters.Document.ALL & filters.User(ADMIN_ID), handle_bot_file_upload))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_bot_token))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), handle_file_manager_text_input))
    application.add_handler(MessageHandler(filters.Document.ALL & filters.User(ADMIN_ID), handle_file_manager_file_input))
    
    logger.info("Starting Advanced Bot Hosting Platform...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    os.makedirs(BOTS_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    main()
