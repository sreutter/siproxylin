"""
Message Input Field - Text input with typing indicators.

Provides the message input field with:
- Up arrow to edit last message
- Chat state notifications (XEP-0085: composing, paused, active)
- Typing pause detection (30s timeout)
"""

import logging
from PySide6.QtWidgets import QTextEdit, QLabel
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
    # Signal for voice request
    voice_request_clicked = Signal()  # User clicked "Request voice" link

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

        # Visitor overlay (shown when user is visitor in moderated room)
        self.visitor_overlay = QLabel(self)
        self.visitor_overlay.setObjectName("visitorOverlay")  # For theme styling
        self.visitor_overlay.setText(
            'You are a visitor in this moderated room. '
            '<a href="#request">Request voice</a> to send messages.'
        )
        self.visitor_overlay.setOpenExternalLinks(False)  # Handle clicks ourselves
        self.visitor_overlay.linkActivated.connect(self._on_voice_request_link_clicked)
        self.visitor_overlay.setAlignment(Qt.AlignCenter)
        self.visitor_overlay.setWordWrap(True)
        self.visitor_overlay.hide()  # Hidden by default

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

    def _on_voice_request_link_clicked(self, link: str):
        """Handle click on 'Request voice' link in visitor overlay."""
        logger.debug("Voice request link clicked")
        self.voice_request_clicked.emit()

    def show_visitor_overlay(self):
        """Show the visitor overlay (user is visitor in moderated room)."""
        # Reset to original text with clickable link
        self.visitor_overlay.setText(
            'You are a visitor in this moderated room. '
            '<a href="#request">Request voice</a> to send messages.'
        )
        self.visitor_overlay.setOpenExternalLinks(False)  # Handle clicks ourselves
        self.visitor_overlay.show()
        self.visitor_overlay.raise_()  # Bring to front
        logger.debug("Visitor overlay shown")

    def hide_visitor_overlay(self):
        """Hide the visitor overlay (user can send messages)."""
        self.visitor_overlay.hide()
        logger.debug("Visitor overlay hidden")

    def update_visitor_overlay_text(self, text: str):
        """
        Update the visitor overlay text (e.g., after request sent or throttled).

        Args:
            text: New text to display
        """
        self.visitor_overlay.setText(text)
        self.visitor_overlay.setOpenExternalLinks(False)  # Disable links when showing status
        logger.debug(f"Visitor overlay text updated: {text}")

    def resizeEvent(self, event):
        """Keep overlay sized to match input field on resize."""
        super().resizeEvent(event)
        # Make overlay same size as input field
        self.visitor_overlay.setGeometry(self.rect())

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
