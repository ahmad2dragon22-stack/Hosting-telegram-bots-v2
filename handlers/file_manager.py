import os
import shutil
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.config_manager import get_config
from utils.file_utils import get_bot_path
from handlers.bot_management import get_bot_panel_keyboard

logger = logging.getLogger(__name__)

def get_file_manager_keyboard(bot_id: str, current_path: str) -> tuple[str, InlineKeyboardMarkup]:
    """Generates the file manager keyboard for a specific path."""
    BOT_CONFIG = get_config()
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
            
        # Manually updating query data to navigate back
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
        
        # Simulating callback to refresh FM
        context.user_data.clear()
        
        # Using a dummy query to refresh the interface
        text, keyboard = get_file_manager_keyboard(bot_id, current_path)
        await update.message.reply_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        
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
        
        # Refresh interface
        text, keyboard = get_file_manager_keyboard(bot_id, current_path)
        await message.reply_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        
    except Exception as e:
        await message.reply_text(f"❌ فشل رفع الملف: {e}")