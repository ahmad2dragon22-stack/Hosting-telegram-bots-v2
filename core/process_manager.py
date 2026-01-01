import asyncio
import os
import sys
import subprocess
import logging
import time
from database.config_manager import get_config, save_config
from utils.file_utils import get_bot_path

logger = logging.getLogger(__name__)

class BotProcessManager:
    """Manages the lifecycle and state of a single hosted bot."""
    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self.config_all = get_config()
        self.config = self.config_all.get(bot_id, {})
        self.process = None
        self.log_buffer = []
        self.log_task = None
        self.start_time = self.config.get('start_time')
        
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
            env['BOT_TOKEN'] = self.config.get('token', '')
            
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
        del ACTIVE_MANAGERS[bot_id]