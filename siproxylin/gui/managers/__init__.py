"""
GUI Manager classes for MainWindow.

Managers handle specific subsystems to keep MainWindow focused and maintainable.
"""

from .call_manager import CallManager
from .notification_manager import NotificationManager

__all__ = [
    'CallManager',
    'NotificationManager',
]
