import json
import logging
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer
from datetime import datetime
from database.config_manager import get_config

logger = logging.getLogger(__name__)

class HealthCheckHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            BOT_CONFIG = get_config()
            total_bots = len(BOT_CONFIG)
            running_bots = sum(1 for config in BOT_CONFIG.values() if config.get('status') == 'running')
            
            response = {
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'total_bots': total_bots,
                'running_bots': running_bots,
                'message': 'Bot Hosting Platform is running'
            }
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

    def log_message(self, format, *args):
        logger.debug(f"Health check: {format % args}")

def run_health_server(port: int = 8000):
    server_address = ('0.0.0.0', port)
    try:
        httpd = HTTPServer(server_address, HealthCheckHandler)
        logger.info(f"Health check server started on port {port}")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start health server: {e}")

def start_health_server(port: int = 8000):
    health_thread = threading.Thread(target=run_health_server, args=(port,), daemon=True)
    health_thread.start()
    logger.info(f"Health server thread started (daemon mode)")