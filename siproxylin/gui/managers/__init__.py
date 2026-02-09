"""
GUI Manager classes for MainWindow.

Managers handle specific subsystems to keep MainWindow focused and maintainable.
"""

from .call_manager import CallManager
from .notification_manager import NotificationManager
from .menu_manager import MenuManager
from .subscription_manager import SubscriptionManager
from .message_manager import MessageManager
from .dialog_manager import DialogManager

__all__ = [
    'CallManager',
    'NotificationManager',
    'MenuManager',
    'SubscriptionManager',
    'MessageManager',
    'DialogManager',
]
