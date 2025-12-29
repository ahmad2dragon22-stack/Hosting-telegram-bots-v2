import os
import sys
import shutil
import zipfile
import subprocess
import logging
import sqlite3
import psutil
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ==========================================
# إعدادات التسجيل والنظام
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOTS_DIR = os.path.join(BASE_DIR, "hosted_bots")
DB_PATH = os.path.join(BASE_DIR, "database.db")

if not os.path.exists(BOTS_DIR):
    os.makedirs(BOTS_DIR)

# ==========================================
# نظام التخزين المتقدم (SQLite)
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bots 
                 (id TEXT PRIMARY KEY, name TEXT, path TEXT, date TEXT, status TEXT, pid INTEGER)''')
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else None

def get_bot(bot_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM bots WHERE id=?", (bot_id,))
    bot = c.fetchone()
    conn.close()
    return bot

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def add_bot(bot_id, name, path):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute("INSERT INTO bots (id, name, path, date, status) VALUES (?, ?, ?, ?, ?)", 
              (bot_id, name, path, date, "stopped"))
    conn.commit()
    conn.close()

def get_all_bots():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM bots")
    rows = c.fetchall()
    conn.close()
    return rows

def update_bot_status(bot_id, status, pid=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if pid is not None:
        c.execute("UPDATE bots SET status=?, pid=? WHERE id=?", (status, pid, bot_id))
    else:
        c.execute("UPDATE bots SET status=? WHERE id=?", (status, bot_id))
    conn.commit()
    conn.close()

def delete_bot_db(bot_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM bots WHERE id=?", (bot_id,))
    conn.commit()
    conn.close()

init_db()

# ==========================================
# وظائف إدارة العمليات والمكتبات
# ==========================================
def install_requirements(bot_path):
    req_file = os.path.join(bot_path, "requirements.txt")
    if os.path.exists(req_file):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
            return True
        except Exception as e:
            logger.error(f"Error installing requirements: {e}")
            return False
    return True

def start_bot_process(bot_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT path, name FROM bots WHERE id=?", (bot_id,))
    res = c.fetchone()
    conn.close()
    if not res: return False
    
    bot_path, bot_name = res
    main_file = os.path.join(bot_path, "main.py")
    if not os.path.exists(main_file):
        py_files = [f for f in os.listdir(bot_path) if f.endswith('.py') and f != "bot.py"]
        if py_files: main_file = os.path.join(bot_path, py_files[0])
        else: return False

    try:
        install_requirements(bot_path)
        process = subprocess.Popen(
            [sys.executable, main_file],
            cwd=bot_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True
        )
        update_bot_status(bot_id, "running", process.pid)
        return True
    except Exception as e:
        logger.error(f"Error starting bot {bot_id}: {e}")
        return False

def stop_bot_process(bot_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT pid FROM bots WHERE id=?", (bot_id,))
    res = c.fetchone()
    conn.close()
    
    if res and res[0]:
        try:
            parent = psutil.Process(res[0])
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    update_bot_status(bot_id, "stopped", 0)
    return True

# ==========================================
# واجهات الأزرار (Keyboards)
# ==========================================
def main_menu_kb():
    keyboard = [
        [InlineKeyboardButton("🚀 رفع بوت جديد", callback_data="upload_bot")],
        [InlineKeyboardButton("🖥️ لوحة التحكم", callback_data="dashboard")],
        [InlineKeyboardButton("🛡️ الحماية والنظام", callback_data="settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

def dashboard_kb():
    bots = get_all_bots()
    keyboard = []
    for bot in bots:
        status_icon = "🟢" if bot[4] == "running" else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status_icon} {bot[1]}", callback_data=f"manage_{bot[0]}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def bot_manage_kb(bot_id, status):
    toggle_text = "🛑 إيقاف" if status == "running" else "▶️ تشغيل"
    keyboard = [
        [InlineKeyboardButton(toggle_text, callback_data=f"toggle_{bot_id}"),
         InlineKeyboardButton("🔄 تحديث", callback_data=f"update_{bot_id}")],
        [InlineKeyboardButton("📂 الملفات", callback_data=f"files_{bot_id}_/")],
        [InlineKeyboardButton("🗑️ حذف البوت", callback_data=f"delete_{bot_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="dashboard")]
    ]
    return InlineKeyboardMarkup(keyboard)

def file_manager_kb(bot_id, current_path):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT path FROM bots WHERE id=?", (bot_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="dashboard")]])
    bot_path = row[0]
    conn.close()
    
    full_path = os.path.normpath(os.path.join(bot_path, current_path.lstrip("/")))
    keyboard = []
    try:
        items = os.listdir(full_path)
        for item in sorted(items):
            item_path = os.path.join(full_path, item)
            rel_path = os.path.relpath(item_path, bot_path).replace("\\", "/")
            if os.path.isdir(item_path):
                keyboard.append([InlineKeyboardButton(f"📁 {item}", callback_data=f"files_{bot_id}_/{rel_path}")])
            else:
                keyboard.append([InlineKeyboardButton(f"📄 {item}", callback_data=f"fop_{bot_id}_/{rel_path}")])
    except: pass

    keyboard.append([
        InlineKeyboardButton("📤 رفع ملف", callback_data=f"fupl_{bot_id}_{current_path}"),
        InlineKeyboardButton("📁 جديد", callback_data=f"fnew_{bot_id}_{current_path}")
    ])
    
    if current_path != "/":
        back_path = os.path.dirname(current_path.rstrip("/"))
        if not back_path.startswith("/"): back_path = "/" + back_path
        keyboard.append([InlineKeyboardButton("⬅️ مجلد أعلى", callback_data=f"files_{bot_id}_{back_path}")])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع للتحكم", callback_data=f"manage_{bot_id}")])
    return InlineKeyboardMarkup(keyboard)

# ==========================================
# معالجات الأحداث (Handlers)
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = get_setting("admin_id")
    user_id = update.effective_user.id

    if admin_id is None:
        set_setting("admin_id", user_id)
        admin_id = user_id

    if str(admin_id) != str(user_id):
        return

    await update.message.reply_text("👋 أهلاً بك في نظام استضافة البوتات المتطور.\nيمكنك إدارة بوتاتك بالكامل من هنا.", reply_markup=main_menu_kb())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    admin_id = get_setting("admin_id")
    
    if str(user_id) != str(admin_id):
        await query.answer("❌ غير مصرح لك", show_alert=True)
        return

    data = query.data
    await query.answer()

    if data == "main_menu":
        await query.edit_message_text("👋 أهلاً بك في نظام استضافة البوتات المتطور.\nيمكنك إدارة بوتاتك بالكامل من هنا.", reply_markup=main_menu_kb())
    
    elif data == "dashboard":
        await query.edit_message_text("🖥️ قائمة البوتات المستضافة حالياً:", reply_markup=dashboard_kb())

    elif data == "upload_bot":
        await query.edit_message_text("📤 أرسل الآن ملف البوت (.py) أو ملف مضغوط (.zip):\nسيتم فك الضغط وتجهيز البيئة تلقائياً.", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data="main_menu")]]))

    elif data.startswith("manage_"):
        bot_id = data.split("_")[1]
        bot = get_bot(bot_id)
        if not bot:
            await query.answer("❌ البوت غير موجود", show_alert=True)
            return
        text = f"🤖 **البوت:** {bot[1]}\n📅 الرفع: {bot[3]}\n📊 الحالة: {'🟢 يعمل' if bot[4] == 'running' else '🔴 متوقف'}"
        await query.edit_message_text(text, reply_markup=bot_manage_kb(bot_id, bot[4]), parse_mode="Markdown")

    elif data.startswith("toggle_"):
        bot_id = data.split("_")[1]
        bot = get_bot(bot_id)
        if not bot:
            await query.answer("❌ البوت غير موجود", show_alert=True)
            return

        status = bot[4]

        if status == "running":
            stop_bot_process(bot_id)
        else:
            start_bot_process(bot_id)

        # تحديث الواجهة
        bot = get_bot(bot_id)
        text = f"🤖 **البوت:** {bot[1]}\n📅 الرفع: {bot[3]}\n📊 الحالة: {'🟢 يعمل' if bot[4] == 'running' else '🔴 متوقف'}"
        await query.edit_message_text(text, reply_markup=bot_manage_kb(bot_id, bot[4]), parse_mode="Markdown")

    elif data.startswith("files_"):
        parts = data.split("_")
        bot_id = parts[1]
        current_path = "_".join(parts[2:])
        await query.edit_message_text(f"📂 **مدير الملفات**\nالمسار: `{current_path}`", reply_markup=file_manager_kb(bot_id, current_path), parse_mode="Markdown")

    elif data.startswith("delete_"):
        bot_id = data.split("_")[1]
        stop_bot_process(bot_id)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT path FROM bots WHERE id=?", (bot_id,))
        row = c.fetchone()
        path = row[0] if row else None
        conn.close()
        try:
            if path:
                shutil.rmtree(path)
        except: pass
        delete_bot_db(bot_id)
        await query.edit_message_text("🖥️ قائمة البوتات المستضافة حالياً:", reply_markup=dashboard_kb())

    elif data == "settings":
        await query.edit_message_text("🛡️ **نظام الحماية والتحكم**\n\n- قاعدة البيانات: SQLite (نشطة)\n- عزل العمليات: مفعل\n- التثبيت التلقائي للمكتبات: مفعل\n- حماية المسؤول: نشطة", 
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]), parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = get_setting("admin_id")
    if str(update.effective_user.id) != str(admin_id): return
    
    doc = update.message.document
    bot_name = doc.file_name.rsplit('.', 1)[0]
    bot_id = str(int(datetime.now().timestamp()))
    bot_path = os.path.join(BOTS_DIR, bot_id)
    os.makedirs(bot_path, exist_ok=True)

    status_msg = await update.message.reply_text("⏳ جاري معالجة الملف...")
    new_file = await context.bot.get_file(doc.file_id)
    download_path = os.path.join(bot_path, doc.file_name)
    try:
        # compatibility: prefer async download_to_drive(), fallback to download()
        if hasattr(new_file, "download_to_drive"):
            await new_file.download_to_drive(download_path)
        else:
            # some versions provide async download()
            if hasattr(new_file, "download"):
                await new_file.download(download_path)
            else:
                # last resort: call synchronous download method in thread
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, new_file.download, download_path)
    except Exception as e:
        await status_msg.edit_text(f"❌ خطأ في التحميل: {e}")
        return
    
    if doc.file_name.endswith(".zip"):
        try:
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(bot_path)
            os.remove(download_path)
            await status_msg.edit_text(f"✅ تم فك ضغط ورفع البوت `{bot_name}`")
        except Exception as e:
            await status_msg.edit_text(f"❌ خطأ في فك الضغط: {e}")
            return
    else:
        await status_msg.edit_text(f"✅ تم رفع ملف البوت `{bot_name}`")
    
    add_bot(bot_id, bot_name, bot_path)
    await update.message.reply_text("🚀 البوت جاهز! يمكنك إدارته من لوحة التحكم.", reply_markup=dashboard_kb())

# ==========================================
# التشغيل الرئيسي
# ==========================================
def main():
    token = os.getenv("8519726834:AAHbe2DFx-fa299YfkK14YNYAm1kuMXA8Sk")
    if not token:
        print("❌ خطأ: يجب تعيين BOT_TOKEN في متغيرات البيئة.")
        return

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("🚀 البوت يعمل الآن بنجاح...")
    application.run_polling()

if __name__ == "__main__":
    main()
