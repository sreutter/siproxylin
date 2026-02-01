"""
Application constants and enums.

Centralized place for all magic strings and enumerated values to avoid inconsistencies.
"""

from enum import Enum


class ProxyType(str, Enum):
    """
    Proxy type enumeration.

    Values match database storage format (uppercase).
    All code should use these constants instead of raw strings.
    """
    NONE = None  # No proxy
    SOCKS5 = "SOCKS5"
    HTTP = "HTTP"

    @classmethod
    def normalize(cls, value):
        """
        Normalize proxy type string to enum value.

        Accepts any case variant and returns the canonical enum value.
        Returns None for invalid/unknown types.

        Examples:
            >>> ProxyType.normalize("socks5")
            ProxyType.SOCKS5
            >>> ProxyType.normalize("SOCKS5")
            ProxyType.SOCKS5
            >>> ProxyType.normalize("http")
            ProxyType.HTTP
            >>> ProxyType.normalize(None)
            None
        """
        if value is None or value == "None":
            return None

        # Try direct enum lookup first
        if isinstance(value, cls):
            return value

        # Normalize string case and lookup
        value_upper = str(value).upper()
        for member in cls:
            if member.value and member.value.upper() == value_upper:
                return member.value

        # Unknown type
        return None

    @classmethod
    def to_db_value(cls, value):
        """
        Convert any proxy type representation to database storage format.

        Args:
            value: ProxyType enum, string, or None

        Returns:
            Canonical string for database storage (uppercase) or None
        """
        normalized = cls.normalize(value)
        return normalized if normalized else None

    @classmethod
    def from_db_value(cls, value):
        """
        Load proxy type from database value.

        Args:
            value: Database value (string or None)

        Returns:
            Canonical string (uppercase) or None
        """
        return cls.normalize(value)

    @classmethod
    def for_display(cls, value):
        """
        Get display-friendly string for UI.

        Args:
            value: ProxyType enum, string, or None

        Returns:
            String suitable for combo boxes, labels, etc.
        """
        normalized = cls.normalize(value)
        return normalized if normalized else "None"


# Message states
class MessageState(int, Enum):
    """Message delivery states for tracking message status."""
    PENDING = 0      # ⌛ Waiting to send
    SENT = 1         # ✓ Server ACK (XEP-0198)
    RECEIVED = 2     # ✓✓ Delivery receipt (XEP-0184)
    READ = 7         # ✔✔ Read/displayed (XEP-0333)
    ERROR = 8        # ⚠ Failed/discarded


# Call states
class CallState(int, Enum):
    """Call states for tracking call status."""
    RINGING = 0       # 📞 Call ringing (proposal sent/received)
    ESTABLISHING = 1  # 🔄 ICE/DTLS negotiation in progress
    IN_PROGRESS = 2   # 📞 Call connected and active
    OTHER_DEVICE = 3  # 📱 Handled on another device (legacy, kept for compatibility)
    ENDED = 4         # ✓ Call ended normally
    DECLINED = 5      # ✗ Call declined/rejected
    MISSED = 6        # ⚠ Call missed (not answered)
    FAILED = 7        # ⚠ Call failed (technical error)
    ANSWERED_ELSEWHERE = 8  # ✓📱 Answered on another device (phone/tablet)
    REJECTED_ELSEWHERE = 9  # ✗📱 Rejected on another device (phone/tablet)


# Call direction
class CallDirection(int, Enum):
    """Call direction."""
    INCOMING = 0      # Call received
    OUTGOING = 1      # Call initiated by us


# Call type
class CallType(int, Enum):
    """Call media type."""
    AUDIO = 0         # Audio-only call
    VIDEO = 1         # Video call (Phase 5)
    SCREEN_SHARE = 2  # Screen sharing (Phase 6)
