import os
import logging
from telegram import Update
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters
)

from config import BOT_TOKEN, ADMIN_ID, BOTS_DIR, BACKUPS_DIR, USE_WEBHOOK, WEBHOOK_LISTEN, WEBHOOK_PORT, WEBHOOK_PATH, WEBHOOK_URL
from database.config_manager import load_config
from core.health_server import start_health_server

# Handlers
from handlers.start_handler import start_command, main_menu_callback
from handlers.bot_management import (
    bot_list_callback,
    bot_panel_callback,
    handle_bot_action,
    delete_bot_confirm_callback,
    delete_bot_callback,
    view_logs_callback,
    backup_bot_callback,
    upload_bot_prompt_callback,
    handle_bot_file_upload,
    handle_bot_token
)
from handlers.file_manager import (
    file_manager_callback,
    file_actions_callback,
    fm_download_callback,
    fm_delete_confirm_callback,
    fm_delete_callback,
    fm_upload_prompt_callback,
    fm_create_dir_prompt_callback,
    handle_file_manager_text_input,
    handle_file_manager_file_input
)
from handlers.system_handlers import system_status_callback, backups_list_callback

# التهيئة الأساسية للسجلات
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def global_error_handler(update: object, context) -> None:
    """Global error handler for uncaught exceptions in handlers."""
    try:
        logger.exception("Unhandled exception in handler", exc_info=context.error)
    except Exception:
        logger.exception("Failed to log exception in global_error_handler")
    try:
        # notify admin if possible
        if ADMIN_ID:
            msg = f"⚠️ حدث خطأ في النظام: {context.error}"
            await context.bot.send_message(chat_id=ADMIN_ID, text=msg)
    except Exception:
        logger.exception("Failed to notify admin about error")

def main() -> None:
    """Start the bot."""
    # التأكد من وجود المجلدات الضرورية
    os.makedirs(BOTS_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    
    # تحميل الإعدادات
    load_config()
    
    # بناء التطبيق
    application = Application.builder().token(BOT_TOKEN).build()

    # إضافة المعالجات (Handlers)
    
    # الأوامر
    application.add_handler(CommandHandler("start", start_command))
    
    # Callback Queries (Inline Buttons)
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern=r"^MAIN_MENU$"))
    application.add_handler(CallbackQueryHandler(bot_list_callback, pattern=r"^BOT_LIST$"))
    application.add_handler(CallbackQueryHandler(bot_panel_callback, pattern=r"^BOT_PANEL\|"))
    application.add_handler(CallbackQueryHandler(system_status_callback, pattern=r"^SYSTEM_STATUS$"))
    application.add_handler(CallbackQueryHandler(backups_list_callback, pattern=r"^BACKUPS_LIST$"))
    
    application.add_handler(CallbackQueryHandler(handle_bot_action, pattern=r"^(START_BOT|STOP_BOT|RESTART_BOT)\|"))
    application.add_handler(CallbackQueryHandler(delete_bot_confirm_callback, pattern=r"^DELETE_BOT_CONFIRM\|"))
    application.add_handler(CallbackQueryHandler(delete_bot_callback, pattern=r"^DELETE_BOT\|"))
    application.add_handler(CallbackQueryHandler(view_logs_callback, pattern=r"^VIEW_LOGS\|"))
    application.add_handler(CallbackQueryHandler(backup_bot_callback, pattern=r"^BACKUP_BOT\|"))
    
    application.add_handler(CallbackQueryHandler(upload_bot_prompt_callback, pattern=r"^UPLOAD_BOT$"))
    
    application.add_handler(CallbackQueryHandler(file_manager_callback, pattern=r"^FILE_MANAGER\|"))
    application.add_handler(CallbackQueryHandler(file_actions_callback, pattern=r"^FILE_ACTIONS\|"))
    application.add_handler(CallbackQueryHandler(fm_download_callback, pattern=r"^FM_DOWNLOAD\|"))
    application.add_handler(CallbackQueryHandler(fm_delete_confirm_callback, pattern=r"^FM_DELETE_CONFIRM\|"))
    application.add_handler(CallbackQueryHandler(fm_delete_callback, pattern=r"^FM_DELETE\|"))
    application.add_handler(CallbackQueryHandler(fm_upload_prompt_callback, pattern=r"^FM_UPLOAD_PROMPT\|"))
    application.add_handler(CallbackQueryHandler(fm_create_dir_prompt_callback, pattern=r"^FM_CREATE_DIR_PROMPT\|"))
    
    # الرسائل (Messages)
    # ملاحظة: تم استخدام فلاتر ADMIN_ID لضمان الأمان
    admin_filter = filters.User(ADMIN_ID)
    
    # ترتيب المعالجات مهم جداً لتجنب التداخل
    application.add_handler(MessageHandler(
        filters.Document.ALL & admin_filter, 
        handle_bot_file_upload
    ), group=1)
    
    application.add_handler(MessageHandler(
        filters.TEXT & admin_filter & ~filters.COMMAND, 
        handle_bot_token
    ), group=1)
    
    application.add_handler(MessageHandler(
        filters.TEXT & admin_filter & ~filters.COMMAND, 
        handle_file_manager_text_input
    ), group=2)
    
    application.add_handler(MessageHandler(
        filters.Document.ALL & admin_filter, 
        handle_file_manager_file_input
    ), group=2)
    
    logger.info("Starting Advanced Bot Hosting Platform...")
    
    # تشغيل خادم مراقبة الحالة في خيط منفصل
    start_health_server(port=8000)
    
    logger.info("Health server is running on port 8000")
    
    # بدء تشغيل البوت
    # register global error handler
    application.add_error_handler(global_error_handler)

    if USE_WEBHOOK:
        # إذا لم يُحدد مسار ويب هوك محليًا، استخدم جزء التوكن كمسار افتراضي
        path = WEBHOOK_PATH or f"/{BOT_TOKEN.split(':')[0]}"
        if not WEBHOOK_URL:
            logger.warning("WEBHOOK_URL غير مُحدد؛ سيتم الرجوع إلى Polling بدلاً من Webhook.")
            application.run_polling(allowed_updates=Update.ALL_TYPES)
        else:
            logger.info(f"Starting webhook on {WEBHOOK_LISTEN}:{WEBHOOK_PORT}{path} -> {WEBHOOK_URL}")
            application.run_webhook(listen=WEBHOOK_LISTEN, port=WEBHOOK_PORT, url_path=path, webhook_url=WEBHOOK_URL)
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()