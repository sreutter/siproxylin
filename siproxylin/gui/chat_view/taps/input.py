"""
Message Input Field - Text input with typing indicators.

Provides the message input field with:
- Up arrow to edit last message
- Chat state notifications (XEP-0085: composing, paused, active)
- Typing pause detection (30s timeout)
"""

import logging
from PySide6.QtWidgets import QTextEdit
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QKeyEvent


logger = logging.getLogger('siproxylin.chat_view.input')


class MessageInputField(QTextEdit):
    """Custom input field that intercepts Up arrow when empty to load last message for editing."""

    arrow_up_in_empty_field = Signal()
    # Signals for chat state notifications (XEP-0085)
    composing_state = Signal()  # User started typing
    paused_state = Signal()     # User paused typing (30s timeout)
    active_state = Signal()     # User is active (sent message or cleared field)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Chat state tracking (XEP-0085)
        self.last_chat_state = None  # Track last sent state to avoid duplicates
        self.is_composing = False    # Track if we're currently in composing state

        # Timer for paused state (fires after 30s of no typing)
        self.pause_timer = QTimer(self)
        self.pause_timer.setSingleShot(True)
        self.pause_timer.timeout.connect(self._on_typing_paused)

        # Connect to text changes to track typing
        self.textChanged.connect(self._on_text_changed)

    def _on_text_changed(self):
        """Handle text changes to send composing/paused states."""
        text = self.toPlainText()

        # If field is now empty, send active state and reset
        if not text:
            if self.is_composing:
                logger.debug("Input cleared - sending active state")
                self.is_composing = False
                self.pause_timer.stop()
                self.active_state.emit()
            return

        # User is typing - send composing on first keystroke
        if not self.is_composing:
            logger.debug("Started composing - sending composing state")
            self.is_composing = True
            self.composing_state.emit()

        # Restart pause timer (30 seconds)
        self.pause_timer.stop()
        self.pause_timer.start(30000)  # 30 seconds

    def _on_typing_paused(self):
        """Timer callback - user paused typing for 30 seconds."""
        if self.is_composing:
            logger.debug("Typing paused (30s timeout) - sending paused state")
            self.is_composing = False
            self.paused_state.emit()

    def reset_chat_state(self):
        """Reset chat state after sending a message."""
        self.is_composing = False
        self.pause_timer.stop()
        logger.debug("Chat state reset (message sent)")

    def keyPressEvent(self, event: QKeyEvent):
        """Override to catch arrow-up in empty field."""
        # Check if this is arrow-up with no modifiers
        if event.key() == Qt.Key_Up and not event.modifiers():
            # Check if field is completely empty
            if not self.toPlainText():
                logger.debug("Arrow-up in empty field - emitting signal")
                self.arrow_up_in_empty_field.emit()
                return  # Consume event, don't pass to QTextEdit

        # All other keys: normal behavior
        super().keyPressEvent(event)
