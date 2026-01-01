import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import BOTS_DIR, BACKUPS_DIR
from database.config_manager import get_config

logger = logging.getLogger(__name__)

async def system_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays global system status."""
    query = update.callback_query
    await query.answer()
    
    BOT_CONFIG = get_config()
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
    )
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