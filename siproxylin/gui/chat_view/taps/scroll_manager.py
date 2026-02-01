"""
Scroll Manager - Auto-scroll and scroll button management.

Handles:
- Scroll-to-bottom floating button
- Auto-scroll detection
- Button visibility based on scroll position
"""

import logging
from PySide6.QtWidgets import QPushButton


logger = logging.getLogger('siproxylin.chat_view.scroll_manager')


class ScrollManager:
    """
    Manages scroll behavior and scroll-to-bottom button.

    Args:
        message_area: QListView displaying messages
        message_container: Parent widget for floating button
    """

    def __init__(self, message_area, message_container, message_widget=None):
        """Initialize scroll manager with message area and container."""
        self.message_area = message_area
        self.message_container = message_container
        self.message_widget = message_widget  # Reference to MessageDisplayWidget for clearing highlights

        # Create scroll-to-bottom button (floating)
        self.scroll_to_bottom_btn = QPushButton("⬇")
        self.scroll_to_bottom_btn.setObjectName("scrollToBottomButton")
        self.scroll_to_bottom_btn.setFixedSize(40, 40)
        self.scroll_to_bottom_btn.clicked.connect(self._scroll_to_bottom)
        self.scroll_to_bottom_btn.hide()  # Hidden by default

        # Position button at bottom-right using geometry (will be set in resizeEvent)
        self.scroll_to_bottom_btn.setParent(message_container)

        # Connect scroll bar to check position
        scrollbar = self.message_area.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll_changed)

    def _is_near_bottom(self, threshold=100):
        """
        Check if scroll position is near bottom.

        Args:
            threshold: Distance from bottom in pixels to consider "near" (default 100)

        Returns:
            True if near bottom or no scrollbar
        """
        scrollbar = self.message_area.verticalScrollBar()
        if not scrollbar.isVisible():
            return True  # No scrollbar = always at bottom

        current = scrollbar.value()
        maximum = scrollbar.maximum()
        return (maximum - current) <= threshold

    def _on_scroll_changed(self, value):
        """Handle scroll position changes to show/hide scroll-to-bottom button."""
        if self._is_near_bottom():
            self.scroll_to_bottom_btn.hide()
        else:
            self.scroll_to_bottom_btn.show()
            self._position_scroll_button()

    def _scroll_to_bottom(self):
        """Scroll to bottom when button is clicked - also clears highlight and returns to live zone."""
        # If there's a highlight, clear it and reload live messages
        if self.message_widget and hasattr(self.message_widget, 'clear_highlight_and_return_to_live'):
            self.message_widget.clear_highlight_and_return_to_live()
        else:
            # Fallback: just scroll to bottom
            self.message_area.scrollToBottom()

    def _position_scroll_button(self):
        """Position scroll-to-bottom button at bottom-right of message area."""
        # Position button 10px from bottom-right
        container_width = self.message_area.width()
        container_height = self.message_area.height()

        x = container_width - self.scroll_to_bottom_btn.width() - 10
        y = container_height - self.scroll_to_bottom_btn.height() - 10

        self.scroll_to_bottom_btn.move(x, y)
        self.scroll_to_bottom_btn.raise_()  # Bring to front

    def on_resize(self):
        """Called when parent widget is resized to reposition button."""
        self._position_scroll_button()
