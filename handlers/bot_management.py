import os
import shutil
import zipfile
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import BOTS_DIR, ADMIN_ID
from database.config_manager import get_config, save_config
from core.process_manager import get_manager, delete_manager
from utils.file_utils import get_bot_path, get_bot_size, create_backup, find_token_in_files
from handlers.start_handler import get_main_menu_keyboard

logger = logging.getLogger(__name__)

def get_bot_list_keyboard() -> InlineKeyboardMarkup:
    """Generates the list of hosted bots keyboard."""
    BOT_CONFIG = get_config()
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
    
    BOT_CONFIG = get_config()
    text = "🤖 قائمة البوتات المستضافة:\n\n"
    if not BOT_CONFIG:
        text += "لا توجد بوتات مستضافة حالياً. استخدم '➕ رفع بوت جديد' للبدء."
        
    await query.edit_message_text(
        text=text,
        reply_markup=get_bot_list_keyboard()
    )

def get_bot_panel_keyboard(bot_id: str) -> tuple[str, InlineKeyboardMarkup]:
    """Generates the control panel for a specific bot."""
    BOT_CONFIG = get_config()
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
    BOT_CONFIG = get_config()
    
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
    BOT_CONFIG = get_config()
    
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
    BOT_CONFIG = get_config()
    
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

async def backup_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Creates a backup of the bot."""
    query = update.callback_query
    await query.answer("جاري إنشاء النسخة الاحتياطية...")
    
    bot_id = query.data.split('|')[1]
    BOT_CONFIG = get_config()
    
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
    BOT_CONFIG = get_config()
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
    BOT_CONFIG = get_config()
    
    if bot_id not in BOT_CONFIG:
        await query.edit_message_text("❌ البوت غير موجود.")
        return
        
    manager = get_manager(bot_id)
    await manager.stop()
    
    bot_path = get_bot_path(bot_id)
    try:
        if os.path.exists(bot_path):
            shutil.rmtree(bot_path)
        
        del BOT_CONFIG[bot_id]
        delete_manager(bot_id)
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
    BOT_CONFIG = get_config()
    
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