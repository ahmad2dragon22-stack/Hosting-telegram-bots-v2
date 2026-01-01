import asyncio
import os
import sys
import subprocess
import logging
import time
import gc
import signal
from typing import Optional
from database.config_manager import get_config, save_config
from utils.file_utils import get_bot_path

logger = logging.getLogger(__name__)


class BotProcessManager:
    """Manages the lifecycle and state of a single hosted bot."""
    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self.config_all = get_config()
        self.config = self.config_all.get(bot_id, {})
        self.process: Optional[asyncio.subprocess.Process] = None
        self.log_buffer: list[str] = []
        self.log_task: Optional[asyncio.Task] = None
        self.monitor_task: Optional[asyncio.Task] = None
        self.start_time = self.config.get('start_time')

    async def start(self) -> str:
        """Starts the bot process."""
        if self.process and self.process.returncode is None:
            return "البوت قيد التشغيل بالفعل."

        try:
            bot_root = get_bot_path(self.bot_id)

            # اكتشاف ملف الدخول: تحقق من أسماء شائعة ثم ابحث داخل الملفات عن نقطة الدخول
            def _find_main_script(root_path: str) -> str | None:
                candidates = ['main.py', 'bot.py', 'run.py', 'app.py']
                for name in candidates:
                    p = os.path.join(root_path, name)
                    if os.path.isfile(p):
                        return p

                # ابحث عن ملفات تحتوي على نقطة الدخول أو استخدام تطبيقات بوت
                for r, _, files in os.walk(root_path):
                    for f in files:
                        if not f.endswith('.py'):
                            continue
                        fp = os.path.join(r, f)
                        try:
                            with open(fp, 'r', encoding='utf-8', errors='ignore') as fh:
                                content = fh.read()
                                if '__main__' in content or 'Application.builder' in content or 'Updater' in content:
                                    return fp
                        except Exception:
                            continue

                # أخيراً، أي ملف py في الجذر
                for f in os.listdir(root_path):
                    if f.endswith('.py'):
                        return os.path.join(root_path, f)

                return None

            script_path = _find_main_script(bot_root)

            if not script_path:
                self.config['status'] = 'error'
                save_config()
                return "❌ لم يتم العثور على ملف بايثون رئيسي لتشغيله."

            env = os.environ.copy()
            env['BOT_TOKEN'] = self.config.get('token', '')
            env['PYTHONUNBUFFERED'] = '1'
            # حاول تعطيل الوصول لـ GPU في البوت المستضاف إن لم يكن مطلوباً
            env.setdefault('CUDA_VISIBLE_DEVICES', '')

            # استخدم وضع التشغيل غير المخبأ (-u) لتحسين إخراج السجلات الفوري
            args = [sys.executable, '-u', script_path]

            # استخدم setsid لبدء مجموعة عمليات جديدة حتى يسهل إيقافها لاحقاً
            preexec = None if os.name == 'nt' else os.setsid

            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=bot_root,
                env=env,
                preexec_fn=preexec
            )

            self.config['status'] = 'starting'
            self.config['pid'] = self.process.pid
            self.start_time = time.time()
            self.config['start_time'] = self.start_time
            save_config()

            # تنظيف الذاكرة
            gc.collect()

            if self.log_task is None:
                self.log_task = asyncio.create_task(self._capture_logs())
            if self.log_task is None:
                self.log_task = asyncio.create_task(self._capture_logs())
            if self.monitor_task is None:
                self.monitor_task = asyncio.create_task(self._monitor_process())

            # تحقق قصير متزامن: انتظر لحظة صغيرة للتأكد من أن العملية لم تنهَر فوراً
            await asyncio.sleep(0.5)
            if self.process.returncode is not None:
                # اجمع بعض رسائل الخطأ المبكرة إن وُجدت وأعد الحالة
                stderr_text = ""
                try:
                    stderr = await self.process.stderr.read()
                    if stderr:
                        stderr_text = stderr.decode('utf-8', errors='ignore').strip()
                except Exception:
                    pass

                self.config['status'] = 'crashed'
                self.config['pid'] = None
                save_config()
                logger.error(f"Bot {self.bot_id} exited immediately with code {self.process.returncode}. Stderr: {stderr_text}")
                return f"❌ فشل تشغيل البوت. خرجت العملية فوراً. رسالة الخطأ:
{stderr_text[:800]}"
            logger.exception(f"Error starting bot {self.bot_id}: {e}")
            self.config['status'] = 'error'
            save_config()
            return "❌ فشل تشغيل البوت"

    async def stop(self) -> str:
        """Stops the bot process."""
        if self.process and self.process.returncode is None:
            try:
                # محاولة إيقاف البوت بلطف أولاً
                if os.name != 'nt':
                    try:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    except Exception:
                        self.process.terminate()
                else:
                    self.process.terminate()

                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    # إذا لم يتوقف، قتله بقوة
                    try:
                        if os.name != 'nt':
                            os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                        else:
                            self.process.kill()
                    except Exception:
                        pass
                    await self.process.wait()

                self.config['status'] = 'stopped'
                self.config['pid'] = None
                save_config()

                # إلغاء المهام الآمنة
                if self.log_task:
                    self.log_task.cancel()
                    self.log_task = None
                if self.monitor_task:
                    self.monitor_task.cancel()
                    self.monitor_task = None

                gc.collect()

                return "⏹ تم إيقاف البوت بنجاح."
            except Exception as e:
                logger.exception(f"Error stopping bot {self.bot_id}: {e}")
                return "❌ فشل إيقاف البوت"

        return "البوت متوقف بالفعل."

    async def restart(self) -> str:
        """Restarts the bot process."""
        await self.stop()
        await asyncio.sleep(2)
        return await self.start()

    async def _capture_logs(self) -> None:
        """Captures stdout and stderr from the running process."""
        try:
            while self.process and self.process.returncode is None:
                try:
                    # قراءة الأسطر بصبر قصير لتجنب حجب الحلقة
                    stdout_line = await asyncio.wait_for(self.process.stdout.readline(), timeout=0.5)
                    if stdout_line:
                        line = stdout_line.decode('utf-8', errors='ignore').strip()
                        if line:
                            self.log_buffer.append(f"[STDOUT] {line}")

                    stderr_line = await asyncio.wait_for(self.process.stderr.readline(), timeout=0.5)
                    if stderr_line:
                        line = stderr_line.decode('utf-8', errors='ignore').strip()
                        if line:
                            self.log_buffer.append(f"[STDERR] {line}")

                    # تقليم الذاكرة الاحتياطية
                    if len(self.log_buffer) > 500:
                        self.log_buffer = self.log_buffer[-500:]
                        gc.collect()

                except asyncio.TimeoutError:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.exception(f"Log capture error for {self.bot_id}: {e}")
                    await asyncio.sleep(1)
        except Exception as e:
            logger.exception(f"Unexpected error in _capture_logs: {e}")

    async def _monitor_process(self) -> None:
        """Monitors the process and handles auto-restart on crash."""
        try:
            if not self.process:
                return
            await self.process.wait()

            return_code = self.process.returncode

            if return_code != 0 and return_code not in (None, -15, -9):
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

            gc.collect()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"Unexpected error in _monitor_process: {e}")

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


ACTIVE_MANAGERS: dict[str, BotProcessManager] = {}


def get_manager(bot_id: str) -> BotProcessManager:
    """Gets or creates a BotProcessManager instance for a bot."""
    if bot_id not in ACTIVE_MANAGERS:
        BOT_CONFIG = get_config()
        if bot_id not in BOT_CONFIG:
            raise ValueError(f"Bot ID {bot_id} not found.")

        manager = BotProcessManager(bot_id)
        ACTIVE_MANAGERS[bot_id] = manager

        if BOT_CONFIG[bot_id].get('status') == 'running':
            asyncio.create_task(manager.start())

    return ACTIVE_MANAGERS[bot_id]


def delete_manager(bot_id: str):
    if bot_id in ACTIVE_MANAGERS:
        manager = ACTIVE_MANAGERS.pop(bot_id)
        try:
            if manager.process and manager.process.returncode is None:
                asyncio.create_task(manager.stop())
        except Exception:
            pass