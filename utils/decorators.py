from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_ID

def admin_only(func):
    """Decorator to restrict access to admin users."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            if update.effective_message:
                await update.effective_message.reply_text("🚫 أنت لست المسؤول. لا يمكنك استخدام هذا البوت.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper