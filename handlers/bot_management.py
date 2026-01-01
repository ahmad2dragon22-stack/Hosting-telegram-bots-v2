import os
import shutil
import zipfile
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import BOTS_DIR, ADMIN_ID
import tempfile
import zipfile
import asyncio
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
        reply_markup=keyboard
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
    try:
        if action == "START_BOT":
            message = await manager.start()
        elif action == "STOP_BOT":
            message = await manager.stop()
        elif action == "RESTART_BOT":
            message = await manager.restart()
    except Exception as e:
        logger.exception(f"Error handling bot action {action} for {bot_id}: {e}")
        message = "❌ حدث خطأ أثناء تنفيذ العملية. راجع السجلات."

    text, keyboard = get_bot_panel_keyboard(bot_id)
    # تأكد من أن النص آمن للإرسال (تجنب تعقيدات Markdown)
    try:
        safe_message = str(message)
        combined_text = f"{text}\n\n--- رسالة النظام ---\n{safe_message}"
        await query.edit_message_text(
            text=combined_text,
            reply_markup=keyboard
        )
    except Exception:
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard)
        except Exception:
            pass

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
    
    try:    
        message = update.message
        
        if not message.document:
            await message.reply_text("❌ يرجى إرسال ملف (py. أو zip.) وليس نصاً.")
            return
            
        file_id = message.document.file_id
        file_name = message.document.file_name
        file_size = getattr(message.document, 'file_size', None)

        # Reject overly large uploads early (50 MB limit)
        if file_size and file_size > 50 * 1024 * 1024:
            await message.reply_text("❌ الملف كبير جداً. الحد المسموح: 50 ميغابايت.")
            return
        
        if not (file_name.endswith('.py') or file_name.endswith('.zip')):
            await message.reply_text("❌ صيغة الملف غير مدعومة. يرجى إرسال ملف .py أو .zip.")
            return
            
        new_file = await context.bot.get_file(file_id)
        # save to a safe temporary path
        safe_name = file_name.replace('/', '_').replace('..', '_')
        temp_dir = tempfile.mkdtemp(prefix=f'temp_upload_{message.from_user.id}_', dir=BOTS_DIR)
        temp_path = os.path.join(temp_dir, safe_name)
        await new_file.download_to_drive(custom_path=temp_path)
        
        context.user_data['temp_bot_file'] = temp_path
        context.user_data['bot_name'] = file_name.replace('.py', '').replace('.zip', '')
        context.user_data['temp_dir'] = temp_dir
        
        # فحص التوكن في خيط منفصل لتجنب حجب حلقة الأحداث
        found_token = await asyncio.to_thread(find_token_in_files, temp_path)
        
        if found_token:
            context.user_data['state'] = 'AWAITING_BOT_TOKEN'
            context.user_data['found_token'] = found_token
            
            reply_text = (
                f"✅ تم استقبال الملف: {file_name}\n"
                f"✅ تم العثور على التوكن تلقائياً\n\n"
                f"اختر:\n"
                f"1️⃣ أرسل 'نعم' أو 'yes' لاستخدام التوكن المكتشف\n"
                f"2️⃣ أرسل توكن مختلف إذا أردت تغييره"
            )
            await message.reply_text(reply_text)
        else:
            context.user_data['state'] = 'AWAITING_BOT_TOKEN'
            reply_text = (
                f"✅ تم استقبال الملف: {file_name}\n\n"
                "❌ لم يتم العثور على توكن في الملفات.\n"
                "يرجى إرسال توكن (Token) البوت الجديد يدوياً.\n"
                "ملاحظة: التوكن لن يظهر في سجلات الدردشة."
            )
            await message.reply_text(reply_text)
    except Exception as e:
        logger.error(f"Error in handle_bot_file_upload: {e}", exc_info=True)
        try:
            await message.reply_text(f"❌ حدث خطأ: تواصل مع المسؤول")
        except:
            pass

async def handle_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the bot token and finalizes deployment."""
    if context.user_data.get('state') != 'AWAITING_BOT_TOKEN':
        return
    
    try:
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
        
        # التحقق من صيغة التوكن
        try:
            parts = token.split(':')
            if not (len(parts) == 2 and parts[0].isdigit() and len(parts[1]) > 10):
                await update.message.reply_text("❌ التوكن المدخل لا يبدو صحيحاً. يرجى إرسال التوكن الصحيح.")
                return
        except (ValueError, AttributeError, IndexError):
            await update.message.reply_text("❌ التوكن المدخل لا يبدو صحيحاً. يرجى إرسال التوكن الصحيح.")
            return
            
        bot_id = token.split(':')[0]
        BOT_CONFIG = get_config()
        
        if bot_id in BOT_CONFIG:
            await update.message.reply_text("❌ البوت بهذا التوكن موجود بالفعل. يرجى استخدام توكن آخر", reply_markup=get_main_menu_keyboard())
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            context.user_data.clear()
            return
            
        bot_root = get_bot_path(bot_id)
        os.makedirs(bot_root, exist_ok=True)

        # استخراج أو نقل الملفات بأمان داخل مجلد مؤقت ثم نقلها
        temp_dir_for_upload = os.path.dirname(temp_path)
        message_text = ""

        # تنفيذ عمليات الملفات الثقيلة في خيط منفصل لتجنب حجب الحلقة
        def _install_files(src_path: str, dest_root: str, name: str) -> str:
            # يعالج كل من ملف zip أو ملف py مفرد
            if src_path.endswith('.zip'):
                try:
                    with zipfile.ZipFile(src_path, 'r') as zip_ref:
                        for member in zip_ref.namelist():
                            if member.startswith('/') or '..' in member:
                                raise zipfile.BadZipFile('Unsafe zip member')
                        extract_dir = tempfile.mkdtemp(prefix='extract_', dir=os.path.dirname(src_path))
                        zip_ref.extractall(extract_dir)

                    for root, dirs, files in os.walk(extract_dir):
                        rel = os.path.relpath(root, extract_dir)
                        target_dir = os.path.join(dest_root, rel) if rel != '.' else dest_root
                        os.makedirs(target_dir, exist_ok=True)
                        for f in files:
                            src = os.path.join(root, f)
                            dst = os.path.join(target_dir, f)
                            shutil.move(src, dst)

                    try:
                        shutil.rmtree(extract_dir)
                    except Exception:
                        pass

                    return f"✅ تم استخراج ملفات البوت {name} بنجاح."
                except zipfile.BadZipFile:
                    raise
            else:
                dst_file = os.path.join(dest_root, f"{name}.py")
                shutil.move(src_path, dst_file)
                return f"✅ تم رفع ملف البوت {name} بنجاح."

        try:
            message_text = await asyncio.to_thread(_install_files, temp_path, bot_root, bot_name)
        except zipfile.BadZipFile:
            await update.message.reply_text("❌ ملف ZIP تالف أو يحتوي أسماء غير آمنة. يرجى إرسال ملف صحيح.")
            if os.path.exists(bot_root):
                shutil.rmtree(bot_root)
            return
        except Exception as e:
            logger.exception(f"Error installing files for bot {bot_id}: {e}")
            if os.path.exists(bot_root):
                shutil.rmtree(bot_root)
            await update.message.reply_text(f"❌ فشل معالجة الملف: {e}")
            return

        # حفظ إعدادات البوت
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
        
        # cleanup temp dir if exists
        try:
            tmp = context.user_data.get('temp_dir')
            if tmp and os.path.exists(tmp):
                shutil.rmtree(tmp)
        except Exception:
            pass
        context.user_data.clear()
        
        # محاولة تشغيل البوت بشكل غير حاجِس لحلقة الأحداث
        try:
            manager = get_manager(bot_id)
            start_task = asyncio.create_task(manager.start())
            # اعطِ عملية البدء فرصة قصيرة لاكتشاف فشل فوري
            await asyncio.sleep(0.1)
            if start_task.done():
                try:
                    start_result = start_task.result()
                except Exception as start_err:
                    logger.error(f"Error starting bot {bot_id}: {start_err}")
                    start_result = f"⚠️ فشل أثناء تشغيل البوت"
            else:
                start_result = "🔁 جاري تشغيل البوت في الخلفية..."
        except Exception as start_err:
            logger.error(f"Error scheduling start for bot {bot_id}: {start_err}")
            start_result = f"⚠️ لم يتم تشغيل البوت تلقائياً"
        
        # إنشاء رسالة بسيطة بدون Markdown لتجنب مشاكل الترميز
        try:
            text, keyboard = get_bot_panel_keyboard(bot_id)
            combined_text = f"{message_text}\n\n{text}\n\n{start_result}"
            combined_text = combined_text.encode('utf-8', errors='ignore').decode('utf-8')
            await update.message.reply_text(
                text=combined_text,
                reply_markup=keyboard
            )
        except Exception as reply_err:
            logger.error(f"Error sending reply: {reply_err}")
            try:
                await update.message.reply_text(
                    f"{message_text}\n\n✅ تم نشر البوت بنجاح",
                    reply_markup=get_main_menu_keyboard()
                )
            except:
                pass
        
    except Exception as e:
        logger.error(f"Deployment error: {e}", exc_info=True)
        try:
            if 'bot_root' in locals() and os.path.exists(bot_root):
                shutil.rmtree(bot_root)
        except:
            pass
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
        except:
            pass
        
        try:
            await update.message.reply_text(f"❌ فشل نشر البوت", reply_markup=get_main_menu_keyboard())
        except:
            pass
        
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
                text=f"✅ تم إنشاء نسخة احتياطية بنجاح.\nالمسار: {backup_path}",
                reply_markup=get_bot_list_keyboard()
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
        text=f"⚠️ تحذير! هل أنت متأكد من حذف البوت {name}؟\nسيتم إيقاف البوت وحذف جميع ملفاته نهائياً.",
        reply_markup=InlineKeyboardMarkup(keyboard)
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
            text=f"🗑 تم حذف البوت {bot_id} وجميع ملفاته بنجاح.",
            reply_markup=get_main_menu_keyboard()
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
        
    text = f"📄 سجلات البوت {BOT_CONFIG[bot_id].get('name', bot_id)} (آخر 50 سطر):\n\n{logs}"
           
    keyboard = [
        [InlineKeyboardButton("🔄 تحديث السجلات", callback_data=f"VIEW_LOGS|{bot_id}")],
        [InlineKeyboardButton("⬅ رجوع للوحة التحكم", callback_data=f"BOT_PANEL|{bot_id}")]
    ]
    
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )