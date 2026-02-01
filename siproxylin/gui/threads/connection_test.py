"""Connection test thread wrapper for non-blocking GUI."""

import logging
import asyncio
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger('siproxylin.connection_test_thread')


class ConnectionTestThread(QThread):
    """Worker thread for testing XMPP connection."""

    # Signal: (success: bool, message: str)
    test_completed = Signal(bool, str)

    def __init__(self, jid, password, server, port, proxy_type=None,
                 proxy_host=None, proxy_port=None, proxy_username=None,
                 proxy_password=None):
        """
        Initialize connection test thread.

        Args:
            jid: Bare JID (user@server.com)
            password: Plain text password
            server: Server address or None for auto-discovery
            port: Port number
            proxy_type: Optional proxy type ('SOCKS5', 'HTTP', or None)
            proxy_host: Optional proxy host
            proxy_port: Optional proxy port
            proxy_username: Optional proxy username
            proxy_password: Optional proxy password
        """
        super().__init__()
        self.jid = jid
        self.password = password
        self.server = server
        self.port = port
        self.proxy_type = proxy_type
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.proxy_username = proxy_username
        self.proxy_password = proxy_password
        self.is_complete = False

    def run(self):
        """Run connection test in separate thread with its own event loop."""
        from ...core.barrels.connection import ConnectionBarrel

        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                ConnectionBarrel.test_connection(
                    self.jid,
                    self.password,
                    self.server,
                    self.port,
                    self.proxy_type,
                    self.proxy_host,
                    self.proxy_port,
                    self.proxy_username,
                    self.proxy_password
                )
            )

            if result['success']:
                server_info = result['server_info'] or "Unknown"
                self.test_completed.emit(True, f"Successfully connected!\nServer: {server_info}")
            else:
                error_msg = result.get('error', 'Unknown error')
                self.test_completed.emit(False, f"Connection failed:\n{error_msg}")

        except Exception as e:
            logger.error(f"Connection test error: {e}")
            self.test_completed.emit(False, f"Test failed:\n{str(e)}")

        finally:
            # Cancel all remaining tasks before closing loop
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                # Give tasks a chance to cancel
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as e:
                logger.debug(f"Task cleanup error (ignored): {e}")
            finally:
                try:
                    loop.close()
                except Exception as e:
                    logger.debug(f"Loop close error (ignored): {e}")
                self.is_complete = True
