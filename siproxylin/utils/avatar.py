"""
Avatar utilities for DRUNK-XMPP-GUI.

Handles loading, rendering, and caching of contact avatars.
"""

import logging
from typing import Optional
from PySide6.QtGui import QPixmap, QPainter, QBrush, QColor, QPainterPath, QFont
from PySide6.QtCore import Qt, QRect

from ..db.database import get_db


logger = logging.getLogger('siproxylin.avatar')


class AvatarCache:
    """LRU cache for avatar pixmaps to avoid repeated DB queries and rendering."""

    def __init__(self, max_size: int = 100):
        self._cache = {}  # {(jid, size): QPixmap}
        self._max_size = max_size
        self._access_order = []  # Track access order for LRU eviction

    def get(self, jid: str, size: int) -> Optional[QPixmap]:
        """Get cached avatar pixmap."""
        key = (jid, size)
        if key in self._cache:
            # Move to end (most recently used)
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None

    def put(self, jid: str, size: int, pixmap: QPixmap):
        """Store avatar pixmap in cache."""
        key = (jid, size)

        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size and key not in self._cache:
            oldest = self._access_order.pop(0)
            del self._cache[oldest]

        self._cache[key] = pixmap
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

    def invalidate(self, jid: str):
        """Invalidate all cached sizes for a JID (when avatar updates)."""
        keys_to_remove = [k for k in self._cache.keys() if k[0] == jid]
        for key in keys_to_remove:
            del self._cache[key]
            self._access_order.remove(key)
        logger.debug(f"Invalidated {len(keys_to_remove)} cached avatars for {jid}")

    def clear(self):
        """Clear entire cache."""
        self._cache.clear()
        self._access_order.clear()


# Global avatar cache
_avatar_cache = AvatarCache()


def get_avatar_cache() -> AvatarCache:
    """Get the global avatar cache instance."""
    return _avatar_cache


def load_avatar_from_db(account_id: int, jid: str) -> Optional[bytes]:
    """
    Load avatar data from database for a JID.

    Args:
        account_id: Account ID
        jid: Bare JID of contact

    Returns:
        Avatar data as bytes, or None if not found
    """
    db = get_db()

    # Get jid_id
    jid_row = db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (jid,))
    if not jid_row:
        return None

    jid_id = jid_row['id']

    # Try to get avatar (prefer PEP type=1, fallback to vCard type=0)
    avatar_row = db.fetchone("""
        SELECT data FROM contact_avatar
        WHERE jid_id = ? AND account_id = ?
        ORDER BY type DESC
        LIMIT 1
    """, (jid_id, account_id))

    if avatar_row and avatar_row['data']:
        return avatar_row['data']

    return None


def create_circular_avatar(pixmap: QPixmap, size: int) -> QPixmap:
    """
    Create a circular avatar from a square pixmap.

    Args:
        pixmap: Source pixmap
        size: Output size (diameter)

    Returns:
        Circular avatar pixmap
    """
    # Scale pixmap to size while maintaining aspect ratio
    scaled = pixmap.scaled(
        size, size,
        Qt.KeepAspectRatioByExpanding,
        Qt.SmoothTransformation
    )

    # Create circular mask
    output = QPixmap(size, size)
    output.fill(Qt.transparent)

    painter = QPainter(output)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    # Create circular path
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)

    # Clip to circle and draw image
    painter.setClipPath(path)

    # Center the image if it's larger than the circle
    x_offset = (scaled.width() - size) // 2
    y_offset = (scaled.height() - size) // 2
    painter.drawPixmap(-x_offset, -y_offset, scaled)

    painter.end()

    return output


def create_initials_avatar(jid: str, size: int, bg_color: Optional[QColor] = None) -> QPixmap:
    """
    Create an avatar with initials from JID.

    Args:
        jid: Bare JID (e.g., "user@domain.com" or "room@conference.domain.com")
        size: Avatar size (diameter)
        bg_color: Background color (auto-generated if None)

    Returns:
        Avatar pixmap with initials
    """
    # Extract local part before @
    local_part = jid.split('@')[0] if '@' in jid else jid

    # Generate initials (first 2 characters, uppercase)
    initials = local_part[:2].upper()

    # Generate color from JID if not provided
    if bg_color is None:
        # Simple hash-based color generation
        hash_val = sum(ord(c) for c in jid)
        hue = (hash_val * 137) % 360  # Golden angle for good distribution
        bg_color = QColor.fromHsv(hue, 180, 200)  # Pastel colors

    # Create circular avatar
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Draw circle
    painter.setBrush(QBrush(bg_color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)

    # Draw initials
    painter.setPen(QColor(255, 255, 255))  # White text
    font = QFont()
    font.setPixelSize(int(size * 0.4))  # 40% of avatar size
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignCenter, initials)

    painter.end()

    return pixmap


def get_avatar_pixmap(account_id: int, jid: str, size: int = 40) -> QPixmap:
    """
    Get avatar pixmap for a JID, with fallback to initials.
    Uses cache to avoid repeated DB queries and rendering.

    Args:
        account_id: Account ID
        jid: Bare JID
        size: Avatar size in pixels (diameter)

    Returns:
        Avatar pixmap (either from photo or initials)
    """
    # Check cache first
    cache = get_avatar_cache()
    cached = cache.get(jid, size)
    if cached:
        return cached

    # Try to load from database
    avatar_data = load_avatar_from_db(account_id, jid)

    if avatar_data:
        try:
            # Ensure we have bytes, not memoryview (SQLite BLOB handling)
            avatar_bytes = bytes(avatar_data) if not isinstance(avatar_data, bytes) else avatar_data

            pixmap = QPixmap()
            if not pixmap.loadFromData(avatar_bytes):
                # loadFromData returns False on failure but doesn't raise exception
                first_bytes_hex = avatar_bytes[:20].hex() if len(avatar_bytes) >= 20 else avatar_bytes.hex()
                logger.warning(f"Failed to load avatar image for {jid}: "
                              f"loadFromData returned False (invalid image format?), "
                              f"data length: {len(avatar_bytes)} bytes, "
                              f"first 20 bytes (hex): {first_bytes_hex}")
            else:
                # Create circular version
                circular = create_circular_avatar(pixmap, size)
                cache.put(jid, size, circular)
                logger.debug(f"Loaded avatar for {jid} from DB ({len(avatar_data)} bytes)")
                return circular
        except Exception as e:
            logger.error(f"Exception loading avatar for {jid}: {e}", exc_info=True)

    # Fallback to initials
    initials_avatar = create_initials_avatar(jid, size)
    cache.put(jid, size, initials_avatar)
    logger.debug(f"Created initials avatar for {jid}")

    return initials_avatar
