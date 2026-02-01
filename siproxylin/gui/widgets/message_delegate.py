"""
Custom delegate for rendering chat message bubbles.

Uses QPainter to draw rounded rectangles - the only way to get actual
rounded corners in Qt without using QWebEngineView.
"""

from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from PySide6.QtCore import Qt, QSize, QRect, QPoint, QUrl, QRegularExpression
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics, QPainterPath, QTextDocument, QAbstractTextDocumentLayout, QSyntaxHighlighter, QTextCharFormat

from ...styles.bubble_themes import get_bubble_colors


class XEP0393Highlighter(QSyntaxHighlighter):
    """Syntax highlighter for XEP-0393 Message Styling (visual formatting only)."""

    def __init__(self, document):
        super().__init__(document)

        # Bold: *text*
        self.bold_fmt = QTextCharFormat()
        self.bold_fmt.setFontWeight(QFont.Bold)

        # Italic: _text_
        self.italic_fmt = QTextCharFormat()
        self.italic_fmt.setFontItalic(True)

        # Strikethrough: ~text~
        self.strike_fmt = QTextCharFormat()
        self.strike_fmt.setFontStrikeOut(True)

        # Monospace: `text`
        self.mono_fmt = QTextCharFormat()
        mono_font = QFont("monospace")
        self.mono_fmt.setFont(mono_font)

        # XEP-0393 pattern: (^|\s)MARKER(\S|\S.*?\S)MARKER
        # Matches: start/space + marker + (single non-ws OR non-ws...non-ws) + marker
        self.patterns = [
            (QRegularExpression(r'(^|\s)(\*)(\S|\S.*?\S)\2'), self.bold_fmt, 2),      # *bold*
            (QRegularExpression(r'(^|\s)(_)(\S|\S.*?\S)\2'), self.italic_fmt, 2),     # _italic_
            (QRegularExpression(r'(^|\s)(~)(\S|\S.*?\S)\2'), self.strike_fmt, 2),     # ~strike~
            (QRegularExpression(r'(^|\s)(`)(\S|\S.*?\S)\2'), self.mono_fmt, 2),       # `code`
        ]

    def highlightBlock(self, text):
        """Apply formatting to text block."""
        for regex, fmt, group_offset in self.patterns:
            match_iter = regex.globalMatch(text)
            while match_iter.hasNext():
                match = match_iter.next()
                # Apply format to group 3 (the inner text, excluding markers)
                # Group 0 = whole match, Group 1 = ^|\s, Group 2 = marker, Group 3 = content
                start = match.capturedStart(3)
                length = match.capturedLength(3)
                self.setFormat(start, length, fmt)


class MessageBubbleDelegate(QStyledItemDelegate):
    """Delegate for rendering chat messages as rounded bubbles."""

    # User roles for storing message data
    ROLE_DIRECTION = Qt.UserRole + 1  # 0=received, 1=sent
    ROLE_BODY = Qt.UserRole + 2
    ROLE_TIMESTAMP = Qt.UserRole + 3
    ROLE_ENCRYPTED = Qt.UserRole + 4
    ROLE_MARKED = Qt.UserRole + 5
    ROLE_TYPE = Qt.UserRole + 6  # 0=chat, 1=groupchat, 2=error
    ROLE_NICKNAME = Qt.UserRole + 7  # MUC sender nickname
    # File transfer roles
    ROLE_FILE_PATH = Qt.UserRole + 8
    ROLE_FILE_NAME = Qt.UserRole + 9
    ROLE_MIME_TYPE = Qt.UserRole + 10
    ROLE_FILE_SIZE = Qt.UserRole + 11
    ROLE_FILE_ICON = Qt.UserRole + 12       # Pre-computed icon emoji
    ROLE_FILE_SIZE_TEXT = Qt.UserRole + 13  # Pre-computed formatted size
    ROLE_IS_CARBON = Qt.UserRole + 14       # 0=regular, 1=carbon (sent from another device)
    ROLE_MESSAGE_ID = Qt.UserRole + 15      # XMPP message ID for editing (message_id, origin_id, or stanza_id)
    ROLE_QUOTED_BODY = Qt.UserRole + 16     # Quoted message body for XEP-0461 replies (if available)
    ROLE_CONTENT_ITEM_ID = Qt.UserRole + 17 # content_item.id for reactions (XEP-0444)
    # Call roles (Phase 4)
    ROLE_CALL_STATE = Qt.UserRole + 18      # CallState enum value
    ROLE_CALL_DURATION = Qt.UserRole + 19   # Duration in seconds (or None if ongoing)
    ROLE_CALL_TYPE = Qt.UserRole + 20       # 0=audio, 1=video
    # Day separator role (Phase 4 UX)
    ROLE_IS_SEPARATOR = Qt.UserRole + 21    # True if this is a day separator item
    ROLE_SEPARATOR_TEXT = Qt.UserRole + 22  # Text to display (e.g., "Today", "Yesterday", "Fri, 29 Jan")
    ROLE_TIMESTAMP_RAW = Qt.UserRole + 23   # Raw Unix timestamp (for Info dialog full date/time)

    def __init__(self, parent=None, theme_name='dark', db=None, account_id=None):
        super().__init__(parent)

        # Database reference for querying reactions
        self.db = db
        self.account_id = account_id

        # Cache for loaded images and documents
        self._pixmap_cache = {}  # {file_path: QPixmap}
        self._doc_cache = {}      # {cache_key: (QTextDocument, width, height)}
        self._reaction_cache = {}  # {content_item_id: [(emoji, count), ...]}

        # Highlight state for search results
        self.highlighted_index = None  # QModelIndex to highlight temporarily

        # Bubble styling
        self.bubble_radius = 12
        self.padding = 10
        self.margin_vertical = 2  # Small vertical spacing between bubbles
        self.margin_vertical_file = 6  # Larger spacing for file attachments

        # Edge margins in millimeters (converted to pixels assuming ~96 DPI)
        # 7mm ≈ 26px, 10mm ≈ 38px at 96 DPI
        self.margin_left = 26   # 7mm from left edge
        self.margin_right = 38  # 10mm from right edge

        # Bubbles can be wide - up to 50% of available width
        self.max_bubble_width_ratio = 0.50
        self.spacing_between_text_and_time = 4

        # Load colors from theme
        self.set_theme(theme_name)

    def set_theme(self, theme_name: str):
        """
        Update bubble colors for a theme.

        Args:
            theme_name: Theme name ('light', 'dark', 'terminal', 'gruvbox', 'light_gray')
        """
        colors = get_bubble_colors(theme_name)
        self.sent_bg_color = colors['sent_bg']
        self.sent_text_color = colors['sent_text']
        self.received_bg_color = colors['received_bg']
        self.received_text_color = colors['received_text']
        self.timestamp_color = colors['timestamp']
        self.marker_read_color = colors['marker_read']
        self.unencrypted_sent_bg_color = colors['unencrypted_sent_bg']
        self.unencrypted_received_bg_color = colors['unencrypted_received_bg']

    def clear_reaction_cache(self):
        """Clear the reaction cache (call when messages are reloaded)."""
        self._reaction_cache.clear()

    def set_account(self, account_id):
        """
        Set the current account ID for querying reactions.

        Args:
            account_id: Current account ID
        """
        self.account_id = account_id
        self.clear_reaction_cache()  # Clear cache when switching accounts

    def _get_file_icon(self, mime_type):
        """Get appropriate emoji icon for file type."""
        if not mime_type:
            return "📎"

        mime_lower = mime_type.lower()

        # Images (shouldn't reach here, but just in case)
        if mime_lower.startswith('image/'):
            return "🖼"
        # Audio
        elif mime_lower.startswith('audio/'):
            return "🎵"
        # Video
        elif mime_lower.startswith('video/'):
            return "🎬"
        # Archives
        elif mime_lower in ('application/zip', 'application/x-rar', 'application/x-tar',
                           'application/gzip', 'application/x-7z-compressed'):
            return "📦"
        # PDFs
        elif mime_lower == 'application/pdf':
            return "📕"
        # Documents
        elif mime_lower in ('application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                           'application/vnd.oasis.opendocument.text', 'text/plain'):
            return "📄"
        # Spreadsheets
        elif mime_lower in ('application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                           'application/vnd.oasis.opendocument.spreadsheet'):
            return "📊"
        # Default
        else:
            return "📎"

    def _format_file_size(self, size_bytes):
        """Format file size in human-readable format."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def _get_reactions(self, content_item_id):
        """
        Get reactions for a content item.

        Returns list of unique emojis from the 3 most recent reactions (no counting).

        Args:
            content_item_id: ID from content_item table

        Returns:
            List of emoji strings, e.g. ['❤️', '👍', '😂']
        """
        if not self.db or not content_item_id or not self.account_id:
            return []

        # Check cache
        if content_item_id in self._reaction_cache:
            return self._reaction_cache[content_item_id]

        # Query all reactions for this content item, ordered by most recent
        # Filter by account_id to handle multi-account setups correctly
        reactions = self.db.fetchall("""
            SELECT emojis, time
            FROM reaction
            WHERE content_item_id = ? AND account_id = ?
            ORDER BY time DESC
        """, (content_item_id, self.account_id))

        if not reactions:
            self._reaction_cache[content_item_id] = []
            return []

        # Collect unique emojis from the most recent reactions
        # Format: each row has comma-separated emojis like "❤️,👍"
        seen_emojis = []

        for row in reactions:
            emojis_str = row['emojis']

            if not emojis_str:
                continue

            # Split comma-separated emojis
            emojis = [e.strip() for e in emojis_str.split(',') if e.strip()]

            for emoji in emojis:
                # Add unique emojis, preserving order by recency
                if emoji not in seen_emojis:
                    seen_emojis.append(emoji)

                # Stop after collecting 3 unique emojis
                if len(seen_emojis) >= 3:
                    break

            if len(seen_emojis) >= 3:
                break

        # Cache result
        self._reaction_cache[content_item_id] = seen_emojis
        return seen_emojis

    def _get_content_document(self, body, is_file, file_path, file_name, mime_type, font, text_width, text_color=None):
        """Get or create cached QTextDocument for content."""
        # Create cache key (v6 = with text_color)
        cache_key = ('v6', body if not is_file else file_path, text_width, font.toString(), text_color.name() if text_color else None)

        if cache_key in self._doc_cache:
            return self._doc_cache[cache_key]

        # Create new document
        doc = QTextDocument()
        doc.setDefaultFont(font)

        if is_file:
            from pathlib import Path
            if mime_type and mime_type.startswith('image/') and file_path and Path(file_path).exists():
                file_url = QUrl.fromLocalFile(file_path).toString()
                html = f'<img src="{file_url}" style="max-width: 300px;" />'
            else:
                # Non-image file: will be rendered with custom paint, not QTextDocument
                # Return dummy dimensions - actual rendering happens in paint()
                html = f'<p>📎 {file_name or "file"}</p>'
            doc.setHtml(html)
            content_size = doc.size()
            width = int(content_size.width())
            height = int(content_size.height())
        else:
            # For text: use QSyntaxHighlighter for XEP-0393 formatting
            # Wrap in HTML with color if provided
            if text_color:
                # HTML-escape the body text, convert newlines to <br />, and wrap with color
                from html import escape
                escaped_body = escape(body).replace('\n', '<br />')
                html_body = f'<span style="color: {text_color.name()};">{escaped_body}</span>'
                doc.setHtml(html_body)
            else:
                doc.setPlainText(body)
            # Attach highlighter to apply XEP-0393 formatting
            highlighter = XEP0393Highlighter(doc)

            # Get the natural width needed for text without wrapping
            # idealWidth() can be unreliable, so we use a large width first
            doc.setTextWidth(10000)  # Very large width to prevent wrapping
            natural_size = doc.size()
            natural_width = int(natural_size.width())

            # If natural width fits within max, use it; otherwise wrap
            if natural_width <= text_width:
                width = natural_width
                height = int(natural_size.height())
            else:
                # Text is too wide, enable wrapping at max width
                doc.setTextWidth(text_width)
                wrapped_size = doc.size()
                # Get actual width of wrapped content (width of longest line)
                ideal_width = doc.idealWidth()
                width = int(ideal_width) if ideal_width > 0 else text_width
                height = int(wrapped_size.height())

        result = (doc, width, height)
        self._doc_cache[cache_key] = result
        return result

    def _is_image_file(self, mime_type):
        """Check if file is an image type."""
        return mime_type and mime_type.startswith('image/')

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        """Paint a message bubble or day separator."""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # Check if this is a day separator
        is_separator = index.data(self.ROLE_IS_SEPARATOR)
        if is_separator:
            self._paint_day_separator(painter, option, index)
            painter.restore()
            return

        # Get message data
        direction = index.data(self.ROLE_DIRECTION)
        body = index.data(self.ROLE_BODY) or ""
        timestamp = index.data(self.ROLE_TIMESTAMP) or ""
        encrypted = index.data(self.ROLE_ENCRYPTED) or False
        marked = index.data(self.ROLE_MARKED) or 0
        msg_type = index.data(self.ROLE_TYPE) or 0
        nickname = index.data(self.ROLE_NICKNAME) or ""

        # File transfer data
        file_path = index.data(self.ROLE_FILE_PATH)
        file_name = index.data(self.ROLE_FILE_NAME)
        mime_type = index.data(self.ROLE_MIME_TYPE)
        file_size = index.data(self.ROLE_FILE_SIZE)
        file_icon = index.data(self.ROLE_FILE_ICON)         # Pre-computed
        file_size_text = index.data(self.ROLE_FILE_SIZE_TEXT)  # Pre-computed

        # Carbon copy flag
        is_carbon = index.data(self.ROLE_IS_CARBON) or False

        # Content item ID for reactions
        content_item_id = index.data(self.ROLE_CONTENT_ITEM_ID)

        # Call data (Phase 4)
        call_state = index.data(self.ROLE_CALL_STATE)
        call_duration = index.data(self.ROLE_CALL_DURATION)
        call_type = index.data(self.ROLE_CALL_TYPE)

        # Check content type
        is_call = call_state is not None
        is_file = bool(file_path) and not is_call

        # === Render calls as separate widgets (not message bubbles) ===
        if is_call:
            self._paint_call_widget(painter, option, index, call_state, call_duration, call_type, direction, timestamp)
            painter.restore()
            return

        # Build timestamp text (without markers - we'll draw them separately)
        timestamp_text = timestamp
        if encrypted:
            timestamp_text += " 🔒"

        # For non-image files, prepend file size to timestamp (right-aligned together)
        if is_file and not self._is_image_file(mime_type):
            if file_size_text:
                timestamp_text = f"({file_size_text})  {timestamp_text}"

        # Determine marker text for sent messages
        # Carbons (sent from another device) show 🗎 instead of delivery markers
        marker_text = ""
        if direction == 1:
            if is_carbon:
                # Carbon copy (sent from another device) - show document icon
                marker_text = "🗎"
            elif is_file:
                # Files don't show markers (state is tracked in file_transfer table, not via marked field)
                pass
            elif marked == 0:
                marker_text = "⌛"      # PENDING (not yet sent/acked) - hourglass
            elif marked == 1:
                marker_text = "✓"       # SENT (server ACK) - light single check
            elif marked == 2:
                marker_text = "✓✓"      # RECEIVED (delivery receipt) - light double check
            elif marked == 7:
                marker_text = "✔✔"      # READ (displayed marker) - heavy/bold double check
            elif marked == 8:
                marker_text = "⚠"       # ERROR (won't send)

        # Get reactions for this message
        reactions = self._get_reactions(content_item_id)

        # Calculate bubble rect (needs to know about file content and reactions)
        bubble_rect = self._calculate_bubble_rect(
            painter, option.rect, body, timestamp_text, marker_text, direction, msg_type, nickname,
            is_file, file_path, file_name, mime_type, reactions
        )

        # Draw bubble background
        # Use red-tinted colors for unencrypted messages
        if not encrypted:
            bg_color = self.unencrypted_sent_bg_color if direction == 1 else self.unencrypted_received_bg_color
        else:
            bg_color = self.sent_bg_color if direction == 1 else self.received_bg_color

        path = QPainterPath()
        path.addRoundedRect(bubble_rect, self.bubble_radius, self.bubble_radius)
        painter.fillPath(path, bg_color)

        # Draw text
        text_rect = bubble_rect.adjusted(
            self.padding, self.padding, -self.padding, -self.padding
        )

        # Save the base font to avoid state bleeding
        base_font = QFont(painter.font())

        # For MUC messages (groupchat), draw nickname first (only for received messages)
        current_y_offset = 0
        if msg_type == 1 and direction == 0 and nickname:  # groupchat, received, has nickname
            # Nickname: bold, slightly smaller, dimmed color
            nickname_font = QFont(base_font)
            nickname_font.setBold(True)
            nickname_font.setPointSize(base_font.pointSize() - 1)
            painter.setFont(nickname_font)

            # Use timestamp color for nickname (dimmed)
            painter.setPen(self.timestamp_color)

            nickname_rect = QRect(text_rect)
            nickname_rect.setHeight(QFontMetrics(nickname_font).height())

            painter.drawText(
                nickname_rect,
                Qt.AlignLeft | Qt.AlignTop,
                f"{nickname}:"
            )

            # Update offset for body text
            current_y_offset = nickname_rect.height() + 6  # 6px spacing

        # Message body - normal weight, full color
        text_color = self.sent_text_color if direction == 1 else self.received_text_color
        painter.setPen(text_color)
        painter.setFont(base_font)  # Reset to base font (not bold)

        body_rect = QRect(text_rect)
        body_rect.setTop(text_rect.top() + current_y_offset)
        body_rect.setHeight(text_rect.height() - self._get_timestamp_height(painter) - current_y_offset)

        # Calculate max text width (same as _calculate_bubble_rect to ensure consistent wrapping)
        available_width = option.rect.width() - self.margin_left - self.margin_right
        max_bubble_width = int(available_width * self.max_bubble_width_ratio)
        max_text_width = max_bubble_width - 2 * self.padding

        if is_file:
            # Files: distinguish between images and other files
            if self._is_image_file(mime_type):
                # Images: use QTextDocument for inline display
                doc, _, _ = self._get_content_document(body, is_file, file_path, file_name, mime_type, base_font, max_text_width, text_color)
                painter.save()
                painter.translate(body_rect.topLeft())
                doc.drawContents(painter)
                painter.restore()
            else:
                # Non-image files:
                # Line 1: [Icon] filename.ext (left-aligned)
                # Line 2: (size) + timestamp + encryption (right-aligned, shared with timestamp rendering below)
                # Use pre-computed values (file_icon, file_size_text)

                painter.setFont(base_font)
                fm = QFontMetrics(base_font)

                # Line 1: Icon + filename
                icon_str = file_icon or "📎"
                display_name = file_name or "file"

                # Measure icon width
                icon_width = fm.horizontalAdvance(icon_str + " ")

                # Available width for filename
                available_filename_width = body_rect.width() - icon_width

                # Truncate filename if too long
                if fm.horizontalAdvance(display_name) > available_filename_width:
                    display_name = fm.elidedText(display_name, Qt.ElideMiddle, available_filename_width)

                filename_line = f"{icon_str} {display_name}"
                filename_rect = QRect(body_rect.left(), body_rect.top(), body_rect.width(), fm.height())
                painter.drawText(
                    filename_rect,
                    Qt.AlignLeft | Qt.AlignTop,
                    filename_line
                )

                # Line 2: File size will be prepended to timestamp
                # Modify timestamp_text to include file size
                # This will be rendered by the timestamp code below (right-aligned)
                # We need to update timestamp_text BEFORE the timestamp rendering section

                # Store the file size to prepend to timestamp later
                # (will be handled in timestamp section below)

                # Reset font for timestamp rendering
                painter.setFont(base_font)
        else:
            # Regular text: use QTextDocument for XEP-0393 formatting
            # Use max_text_width (same as _calculate_bubble_rect) for consistent wrapping
            doc, _, _ = self._get_content_document(body, is_file, file_path, file_name, mime_type, base_font, max_text_width, text_color)
            painter.save()
            painter.translate(body_rect.topLeft())
            doc.drawContents(painter)
            painter.restore()

        # Timestamp - smaller, dimmed color
        painter.setPen(self.timestamp_color)
        timestamp_font = QFont(base_font)
        timestamp_font.setPointSize(base_font.pointSize() - 2)
        painter.setFont(timestamp_font)

        timestamp_rect = QRect(text_rect)
        timestamp_rect.setTop(body_rect.bottom() + self.spacing_between_text_and_time)

        painter.drawText(
            timestamp_rect,
            Qt.AlignRight | Qt.AlignTop,
            timestamp_text
        )

        # Draw markers separately with monospace font and custom color
        if marker_text:
            # Use monospace font for tighter spacing
            marker_font = QFont("monospace", timestamp_font.pointSize())
            marker_font.setStyleHint(QFont.Monospace)
            marker_fm = QFontMetrics(marker_font)
            painter.setFont(marker_font)

            # Use different color for read markers
            if marked == 7:
                painter.setPen(self.marker_read_color)
            else:
                painter.setPen(self.timestamp_color)

            # Calculate exact positions:
            # 1. Timestamp is right-aligned, so it ends at timestamp_rect.right()
            # 2. Measure timestamp width to find where it starts
            # 3. Place markers to the LEFT of timestamp start (since right-aligned layout)
            timestamp_fm = QFontMetrics(timestamp_font)
            timestamp_width = timestamp_fm.horizontalAdvance(timestamp_text)
            timestamp_start_x = timestamp_rect.right() - timestamp_width

            marker_width = marker_fm.horizontalAdvance(marker_text)
            marker_x = timestamp_start_x - marker_width - 3  # 3px gap

            marker_rect = QRect(
                marker_x,
                timestamp_rect.top(),
                marker_width,
                timestamp_rect.height()
            )

            painter.drawText(
                marker_rect,
                Qt.AlignLeft | Qt.AlignTop,
                marker_text
            )

        # Draw reactions on same line as timestamp, left-aligned (if any)
        if reactions:
            painter.setPen(self.timestamp_color)
            reaction_font = QFont(base_font)
            reaction_font.setPointSize(base_font.pointSize() - 1)
            painter.setFont(reaction_font)

            # Build reaction text: just emojis without spaces "❤️👍😂"
            reaction_text = "".join(reactions)

            # Draw reactions left-aligned on same line as timestamp
            # Timestamp/markers are right-aligned, reactions are left-aligned
            # This matches the bubble width calculation which accounts for both
            reaction_rect = QRect(text_rect)
            reaction_rect.setTop(body_rect.bottom() + self.spacing_between_text_and_time)

            painter.drawText(
                reaction_rect,
                Qt.AlignLeft | Qt.AlignTop,
                reaction_text
            )

        # Draw highlight overlay for search results
        if self.highlighted_index and self.highlighted_index == index:
            # Draw a semi-transparent yellow overlay over the entire item area
            highlight_color = QColor(255, 255, 0, 60)  # Yellow with alpha
            painter.fillRect(option.rect, highlight_color)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        """Calculate the size needed for this message bubble or separator."""
        # Check if this is a day separator
        is_separator = index.data(self.ROLE_IS_SEPARATOR)
        if is_separator:
            # Separator height: text + padding
            return QSize(option.rect.width(), 40)

        # Get message data
        direction = index.data(self.ROLE_DIRECTION)
        body = index.data(self.ROLE_BODY) or ""
        timestamp = index.data(self.ROLE_TIMESTAMP) or ""
        encrypted = index.data(self.ROLE_ENCRYPTED) or False
        marked = index.data(self.ROLE_MARKED) or 0
        msg_type = index.data(self.ROLE_TYPE) or 0
        nickname = index.data(self.ROLE_NICKNAME) or ""

        # File transfer data
        file_path = index.data(self.ROLE_FILE_PATH)
        file_name = index.data(self.ROLE_FILE_NAME)
        mime_type = index.data(self.ROLE_MIME_TYPE)

        # Call data (Phase 4)
        call_state = index.data(self.ROLE_CALL_STATE)
        call_duration = index.data(self.ROLE_CALL_DURATION)
        call_type = index.data(self.ROLE_CALL_TYPE)

        # Check content type
        is_call = call_state is not None
        is_file = bool(file_path) and not is_call

        # Carbon copy flag
        is_carbon = index.data(self.ROLE_IS_CARBON) or False

        # Build timestamp text (without markers - same as paint())
        timestamp_text = timestamp
        if encrypted:
            timestamp_text += " 🔒"

        # Determine marker text for width calculation (same logic as paint())
        marker_text = ""
        if direction == 1:
            if is_carbon:
                marker_text = "🗎"      # CARBON (sent from another device)
            elif is_file:
                pass  # Files don't show markers
            elif marked == 0:
                marker_text = "⌛"      # PENDING
            elif marked == 1:
                marker_text = "✓"       # SENT
            elif marked == 2:
                marker_text = "✓✓"      # RECEIVED
            elif marked == 7:
                marker_text = "✔✔"      # READ
            elif marked == 8:
                marker_text = "⚠"       # ERROR

        # Calculate text dimensions
        font = option.font
        fm = QFontMetrics(font)

        # Calculate available width (accounting for left and right margins)
        available_width = option.rect.width() - self.margin_left - self.margin_right
        max_bubble_width = int(available_width * self.max_bubble_width_ratio)
        text_width = max_bubble_width - 2 * self.padding

        # Calculate content height - use QTextDocument for consistency with paint()
        if is_call:
            # Calls: bubble + timestamp below
            call_height = fm.height() + 2 * self.padding  # Bubble height
            timestamp_font = QFont(font)
            timestamp_font.setPointSize(font.pointSize() - 2)
            timestamp_fm = QFontMetrics(timestamp_font)
            timestamp_height = timestamp_fm.height() + 4  # +4 for spacing
            total_height = call_height + timestamp_height + 8  # +8 for vertical padding
            return QSize(option.rect.width(), total_height)
        elif is_file and not self._is_image_file(mime_type):
            # Non-image files: just 1 line for icon+filename
            # (size is on timestamp line, handled separately)
            text_rect_height = fm.height()
        else:
            # Text and images: use cached QTextDocument
            _, _, text_rect_height = self._get_content_document(
                body, is_file, file_path, file_name, mime_type, font, text_width
            )

        # Add timestamp height
        timestamp_font = QFont(font)
        timestamp_font.setPointSize(font.pointSize() - 2)
        timestamp_fm = QFontMetrics(timestamp_font)
        timestamp_height = timestamp_fm.height()

        # Add nickname height for MUC received messages
        nickname_height = 0
        if msg_type == 1 and direction == 0 and nickname:  # groupchat, received, has nickname
            nickname_font = QFont(font)
            nickname_font.setBold(True)
            nickname_font.setPointSize(nickname_font.pointSize() - 1)
            nickname_fm = QFontMetrics(nickname_font)
            nickname_height = nickname_fm.height() + 6  # 6px spacing

        # Use larger vertical margin for file attachments (non-images)
        vertical_margin = self.margin_vertical_file if (is_file and not self._is_image_file(mime_type)) else self.margin_vertical

        total_height = (
            text_rect_height +
            self.spacing_between_text_and_time +
            timestamp_height +
            nickname_height +
            2 * self.padding +
            2 * vertical_margin
        )

        return QSize(option.rect.width(), total_height)

    def _calculate_bubble_rect(self, painter, item_rect, body, timestamp_text, marker_text, direction, msg_type, nickname,
                               is_file=False, file_path=None, file_name=None, mime_type=None, reactions=None):
        """Calculate the rectangle for the bubble."""
        font = painter.font()
        fm = QFontMetrics(font)

        # Calculate available width and max bubble width
        available_width = item_rect.width() - self.margin_left - self.margin_right
        max_bubble_width = int(available_width * self.max_bubble_width_ratio)
        text_width = max_bubble_width - 2 * self.padding

        # Calculate content dimensions using QTextDocument (consistent with paint())
        _, text_rect_width, text_rect_height = self._get_content_document(
            body, is_file, file_path, file_name, mime_type, font, text_width
        )

        # Calculate timestamp width
        timestamp_font = QFont(font)
        timestamp_font.setPointSize(font.pointSize() - 2)
        timestamp_fm = QFontMetrics(timestamp_font)
        timestamp_width = timestamp_fm.horizontalAdvance(timestamp_text)

        # Calculate marker width (using monospace font)
        marker_width = 0
        if marker_text:
            marker_font = QFont("monospace", timestamp_font.pointSize())
            marker_font.setStyleHint(QFont.Monospace)
            marker_fm = QFontMetrics(marker_font)
            marker_width = marker_fm.horizontalAdvance(marker_text) + 2  # +2 for spacing

        # Calculate reaction width (same font as timestamp)
        reaction_width = 0
        if reactions:
            # reactions is now a list of emoji strings (no counts)
            reaction_text = "".join(reactions)
            reaction_width = timestamp_fm.horizontalAdvance(reaction_text)

        # Calculate nickname width for MUC received messages
        nickname_width = 0
        nickname_height = 0
        if msg_type == 1 and direction == 0 and nickname:  # groupchat, received, has nickname
            nickname_font = QFont(font)
            nickname_font.setBold(True)
            nickname_font.setPointSize(nickname_font.pointSize() - 1)
            nickname_fm = QFontMetrics(nickname_font)
            nickname_width = nickname_fm.horizontalAdvance(f"{nickname}:")
            nickname_height = nickname_fm.height() + 6  # 6px spacing

        # Bubble width is max of content, nickname, and (reactions + timestamp + marker on same line)
        # Reactions are left-aligned, timestamp+markers are right-aligned
        bottom_line_width = reaction_width + timestamp_width + marker_width + 10  # +10 for spacing between them
        # For files (especially images), use actual content width; for text, allow up to max
        bubble_content_width = max(text_rect_width, bottom_line_width, nickname_width)

        if is_file:
            # Files: use exact content width (images are already constrained by max-width CSS)
            bubble_width = bubble_content_width + 2 * self.padding
        else:
            # Text: allow wrapping up to max_bubble_width
            bubble_width = min(bubble_content_width + 2 * self.padding, max_bubble_width)

        # Bubble height
        timestamp_height = timestamp_fm.height()
        bubble_height = (
            text_rect_height +
            self.spacing_between_text_and_time +
            timestamp_height +
            nickname_height +
            2 * self.padding
        )

        # Position bubble (right for sent, left for received)
        if direction == 1:  # Sent - align right with 10mm margin
            x = item_rect.right() - bubble_width - self.margin_right
        else:  # Received - align left with 7mm margin
            x = item_rect.left() + self.margin_left

        y = item_rect.top() + self.margin_vertical

        return QRect(x, y, bubble_width, bubble_height)

    def _get_timestamp_height(self, painter):
        """Get the height needed for timestamp."""
        font = painter.font()
        timestamp_font = QFont(font)
        timestamp_font.setPointSize(font.pointSize() - 1)
        fm = QFontMetrics(timestamp_font)
        return fm.height() + self.spacing_between_text_and_time

    def _paint_call_widget(self, painter, option, index, call_state, call_duration, call_type, direction, timestamp):
        """
        Paint call widget as a separate container (not a message bubble).

        Design:
        - Wider than message bubbles (60% vs 50%)
        - Gray background with black outline
        - Status icon shows call state (colored)
        - Direction-aligned: outgoing right, incoming left
        """
        from ...core.constants import CallState

        # Map call state to colored status icon
        state_display = {
            CallState.RINGING.value: ("📞", "Ringing", None),
            CallState.ESTABLISHING.value: ("📞", "Connecting", None),
            CallState.IN_PROGRESS.value: ("📞", "Connected", None),
            CallState.OTHER_DEVICE.value: ("📱", "Other Device", None),
            CallState.ENDED.value: ("✓", "Call", Qt.darkGreen),
            CallState.DECLINED.value: ("✗", "Declined", Qt.red),
            CallState.MISSED.value: ("⚠", "Missed", QColor(255, 140, 0)),  # Orange
            CallState.FAILED.value: ("⚠", "Failed", Qt.red),
            CallState.ANSWERED_ELSEWHERE.value: ("✓", "Answered on other device", Qt.darkGreen),
            CallState.REJECTED_ELSEWHERE.value: ("✗", "Rejected on other device", Qt.red),
        }

        status_icon, state_text, icon_color = state_display.get(call_state, ("📞", "Call", None))

        # Direction text
        direction_text = "Incoming" if direction == 0 else "Outgoing"

        # Duration text
        if call_duration is not None:
            if call_duration >= 3600:
                hours = call_duration // 3600
                minutes = (call_duration % 3600) // 60
                seconds = call_duration % 60
                duration_text = f"{hours:d}h {minutes:02d}m {seconds:02d}s"
            elif call_duration >= 60:
                minutes = call_duration // 60
                seconds = call_duration % 60
                duration_text = f"{minutes:d}m {seconds:02d}s"
            else:
                duration_text = f"{call_duration:d}s"
        else:
            duration_text = ""  # No answer or ongoing

        # Build call text: "📞 Incoming Call • 22s"
        if duration_text:
            call_text = f"📞 {direction_text} {state_text} • {duration_text}"
        else:
            call_text = f"📞 {direction_text} {state_text}"

        # Calculate bubble dimensions
        font = painter.font()
        fm = QFontMetrics(font)

        # Call bubbles use natural text width (like message bubbles)
        text_width = fm.horizontalAdvance(call_text)
        bubble_width = text_width + 2 * self.padding + 40  # +40 for status icon + spacing
        bubble_height = fm.height() + 2 * self.padding

        # Position bubble based on direction
        if direction == 1:  # Outgoing - right aligned
            bubble_x = option.rect.right() - self.margin_right - bubble_width
        else:  # Incoming - left aligned
            bubble_x = option.rect.left() + self.margin_left

        bubble_y = option.rect.top() + 4

        bubble_rect = QRect(bubble_x, bubble_y, bubble_width, bubble_height)

        # Draw bubble background (gray) with border
        from ...styles.theme_manager import get_theme_manager
        theme_manager = get_theme_manager()

        if theme_manager.current_theme == 'dark':
            bg_color = QColor(60, 60, 60)  # Dark gray
            border_color = QColor(100, 100, 100)  # Lighter gray border
            text_color = QColor(220, 220, 220)  # Light text
        else:
            bg_color = QColor(240, 240, 240)  # Light gray
            border_color = QColor(180, 180, 180)  # Darker gray border
            text_color = QColor(40, 40, 40)  # Dark text

        # Draw rounded rectangle
        path = QPainterPath()
        path.addRoundedRect(bubble_rect, self.bubble_radius, self.bubble_radius)
        painter.fillPath(path, bg_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawPath(path)

        # Draw call text
        text_rect = bubble_rect.adjusted(self.padding, self.padding, -self.padding - 25, -self.padding)
        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, call_text)

        # Draw colored status icon on the right
        status_rect = QRect(
            bubble_rect.right() - 22,
            bubble_rect.top() + self.padding,
            20,
            fm.height()
        )
        if icon_color:
            painter.setPen(icon_color)
        painter.drawText(status_rect, Qt.AlignCenter, status_icon)

        # Draw timestamp below
        timestamp_font = QFont(font)
        timestamp_font.setPointSize(font.pointSize() - 2)
        painter.setFont(timestamp_font)

        timestamp_fm = QFontMetrics(timestamp_font)
        timestamp_y = bubble_rect.bottom() + 4
        timestamp_rect = QRect(bubble_x, timestamp_y, bubble_width, timestamp_fm.height())

        painter.setPen(self.timestamp_color)
        painter.drawText(timestamp_rect, Qt.AlignCenter, timestamp)

    def _paint_day_separator(self, painter, option, index):
        """
        Paint a day separator line with centered text.
        Format: "----------- Today -----------"
        """
        separator_text = index.data(self.ROLE_SEPARATOR_TEXT) or ""

        # Setup font - small, dimmed
        font = painter.font()
        separator_font = QFont(font)
        separator_font.setPointSize(font.pointSize() - 2)
        painter.setFont(separator_font)
        fm = QFontMetrics(separator_font)

        # Use timestamp color for dimmed appearance
        painter.setPen(self.timestamp_color)

        # Calculate text width
        text_width = fm.horizontalAdvance(separator_text)
        padding = 10  # Space between text and lines

        # Center text horizontally
        text_x = (option.rect.width() - text_width) // 2
        text_y = option.rect.top() + (option.rect.height() + fm.height()) // 2

        # Draw text
        painter.drawText(text_x, text_y, separator_text)

        # Draw lines on both sides
        line_y = option.rect.top() + option.rect.height() // 2
        left_line_end = text_x - padding
        right_line_start = text_x + text_width + padding

        # Left line
        if left_line_end > option.rect.left():
            painter.drawLine(option.rect.left() + 20, line_y, left_line_end, line_y)

        # Right line
        if right_line_start < option.rect.right():
            painter.drawLine(right_line_start, line_y, option.rect.right() - 20, line_y)
