from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.decorators import admin_only

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