"""
Contact display data model.

Single source of truth for contact/MUC presentation in roster.
Replaces fragile string parsing with clean data model.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ContactDisplayData:
    """
    Data model for contact/MUC roster display.

    Centralizes all display logic - no more string manipulation!

    Usage:
        # Create data
        data = ContactDisplayData(
            jid="alice@example.com",
            name="Alice",
            account_id=1,
            presence='available',
            unread_count=3,
            call_state='incoming'
        )

        # Get display string
        item.setText(0, data.to_display_string())

        # Update state (no parsing!)
        data.call_state = 'active'
        item.setText(0, data.to_display_string())
    """

    # === Core Identity ===
    jid: str
    name: str
    account_id: int
    item_type: str  # 'contact', 'muc', 'account', 'empty'

    # === Database IDs ===
    roster_id: Optional[int] = None
    bookmark_id: Optional[int] = None

    # === Type Flags ===
    is_muc: bool = False

    # === State Indicators ===
    presence: str = 'unavailable'  # 'available', 'away', 'xa', 'dnd', 'unavailable'
    unread_count: int = 0
    subscription: str = 'both'  # 'both', 'to', 'from', 'none'
    blocked: bool = False
    typing: bool = False
    autojoin: bool = False  # MUC only
    call_state: Optional[str] = None  # None, 'incoming', 'outgoing', 'active'
    participant_count: Optional[int] = None  # MUC only - live participant count

    # === Icon Mappings (Single Source of Truth) ===

    PRESENCE_ICONS = {
        'available': '🟢',  # Green - online
        'away': '🟡',       # Yellow - away
        'xa': '🟠',         # Orange - extended away
        'dnd': '🔴',        # Red - do not disturb
        'unavailable': '⚫' # Gray - offline
    }

    CALL_ICONS = {
        'incoming': '📞',   # Phone (incoming/ringing)
        'outgoing': '📞',   # Phone (outgoing/initiating)
        'active': '📞'      # Phone (connected/active)
    }

    SUBSCRIPTION_ICONS = {
        'both': '',         # Mutual subscription - no indicator needed
        'to': '[→]',        # We can see them
        'from': '[←]',      # They can see us
        'none': '[✗]'       # No subscription
    }

    # ASCII mode subscription icons
    SUBSCRIPTION_ICONS_ASCII = {
        'both': '',         # Mutual subscription - no indicator needed
        'to': '[>]',        # We can see them
        'from': '[<]',      # They can see us
        'none': '[?]'       # No subscription
    }

    # ASCII mode colors - now theme-aware (see get_text_color_ascii)
    # Colors are fetched from app/styles/roster_themes.py based on current theme

    # === Display String Generation ===

    def to_display_string(self, uses_emoji: bool = True) -> str:
        """
        Build display string from data.

        Args:
            uses_emoji: True for emoji icons (🟢👥), False for text indicators ([MUC])

        Format for contacts (emoji):
            [presence] Name (unread) [call] [typing] [subscription] [blocked]

        Format for contacts (text):
            Name (unread) [call] [subscription]

        Format for MUCs:
            👥 Name (unread) [call] [typing] [autojoin]  (emoji)
            [MUC] Name (unread) [call] [autojoin]        (text)

        Returns:
            Formatted display string ready for QTreeWidgetItem
        """
        if uses_emoji:
            return self._to_display_string_classic()
        else:
            return self._to_display_string_ascii()

    def _to_display_string_classic(self) -> str:
        """Generate classic display string with emoji icons."""
        parts = []

        # 1. Type icon (MUC vs contact presence)
        if self.is_muc:
            parts.append('👥')  # Group icon for MUC
        else:
            # Contact presence indicator
            parts.append(self.PRESENCE_ICONS.get(self.presence, '⚫'))

        # 2. Name (required)
        parts.append(self.name)

        # 3. Unread count (if any)
        if self.unread_count > 0:
            parts.append(f"({self.unread_count})")

        # 4. Call indicator (if in call)
        if self.call_state:
            call_icon = self.CALL_ICONS.get(self.call_state, '')
            if call_icon:
                parts.append(call_icon)

        # 5. Typing indicator (if typing)
        if self.typing:
            parts.append('✎')

        # 6. Subscription indicator (contacts only, if not mutual)
        if not self.is_muc and self.subscription != 'both':
            sub_icon = self.SUBSCRIPTION_ICONS.get(self.subscription, '')
            if sub_icon:
                parts.append(sub_icon)

        # 7. Blocked indicator (if blocked)
        if self.blocked:
            parts.append('🚫')

        # 8. Autojoin indicator (MUC only)
        if self.is_muc and self.autojoin:
            parts.append('⭐')

        return ' '.join(parts)

    def _to_display_string_ascii(self) -> str:
        """Generate ASCII display string (text-only, no emojis)."""
        parts = []

        # 1. MUC prefix with autojoin indicator (if MUC)
        if self.is_muc:
            if self.autojoin:
                parts.append('[MUC +]')
            else:
                parts.append('[MUC -]')

        # 2. Name (required)
        parts.append(self.name)

        # 3. Unread count (if any)
        if self.unread_count > 0:
            parts.append(f"({self.unread_count})")

        # 4. Call indicator (if in call)
        if self.call_state:
            parts.append('*')

        # 5. Subscription indicator (contacts only, if not mutual)
        if not self.is_muc and self.subscription != 'both':
            sub_icon = self.SUBSCRIPTION_ICONS_ASCII.get(self.subscription, '')
            if sub_icon:
                parts.append(sub_icon)

        return ' '.join(parts)

    def get_font_style(self) -> dict:
        """
        Get font styling based on state.

        Returns:
            Dictionary with 'bold', 'italic', 'underline' flags
        """
        return {
            'bold': self.unread_count > 0,      # Bold if unread messages
            'italic': self.typing,               # Italic if contact is typing
            'underline': False                   # Reserved for future use
        }

    def get_text_color_ascii(self, theme: str = 'dark') -> Optional[str]:
        """
        Get text color for ASCII mode based on state and theme.

        Priority: Call state > MUC color > Presence

        Args:
            theme: Current theme name ('light', 'dark', 'terminal', 'gruvbox', 'light_gray')

        Returns:
            Hex color string or None for default
        """
        from ...styles.roster_themes import get_roster_colors
        colors = get_roster_colors(theme)

        # Call state takes priority
        if self.call_state:
            return colors['call_active']

        # MUC color (grayish-blue to stand out from contact colors)
        if self.is_muc:
            return colors['muc']

        # Presence colors (for contacts only)
        color_key = f'presence_{self.presence}'
        return colors.get(color_key, colors['presence_unavailable'])

    def get_tooltip(self) -> str:
        """
        Generate tooltip text with detailed information.

        Returns:
            Multi-line tooltip string
        """
        lines = []

        if self.is_muc:
            # MUC tooltip
            lines.append(f"Room: {self.jid}")

            # Participant count (if available)
            if self.participant_count is not None:
                lines.append(f"Participants: {self.participant_count}")

            lines.append(f"Autojoin: {'Yes' if self.autojoin else 'No'}")
            if self.bookmark_id:
                lines.append("Bookmarked: Yes")
            if self.roster_id:
                lines.append("In Roster: Yes")
        else:
            # Contact tooltip
            lines.append(f"JID: {self.jid}")

            # Presence status (human-readable)
            presence_names = {
                'available': 'Available',
                'away': 'Away',
                'xa': 'Extended Away',
                'dnd': 'Do Not Disturb',
                'unavailable': 'Offline'
            }
            lines.append(f"Status: {presence_names.get(self.presence, 'Unknown')}")

            # Subscription
            subscription_names = {
                'both': 'Both (mutual)',
                'to': 'To (we can see them)',
                'from': 'From (they can see us)',
                'none': 'None'
            }
            lines.append(f"Subscription: {subscription_names.get(self.subscription, 'Unknown')}")

            if self.blocked:
                lines.append("Blocked: Yes")

        # Call state
        if self.call_state:
            call_state_names = {
                'incoming': 'Incoming call',
                'outgoing': 'Outgoing call',
                'active': 'Call in progress'
            }
            lines.append(f"Call: {call_state_names.get(self.call_state, 'Active')}")

        # Unread messages
        if self.unread_count > 0:
            lines.append(f"Unread: {self.unread_count}")

        return '\n'.join(lines)

    # === Convenience Methods ===

    def update_presence(self, presence: str):
        """Update presence and return new display string."""
        self.presence = presence
        return self.to_display_string()

    def update_unread(self, count: int):
        """Update unread count and return new display string."""
        self.unread_count = count
        return self.to_display_string()

    def update_typing(self, is_typing: bool):
        """Update typing state and return new display string."""
        self.typing = is_typing
        return self.to_display_string()

    def update_call_state(self, state: Optional[str]):
        """Update call state and return new display string."""
        self.call_state = state
        return self.to_display_string()

    def to_dict(self) -> dict:
        """
        Convert to dictionary for storage in Qt.UserRole.

        Returns:
            Dictionary with all data (for QTreeWidgetItem.setData)
        """
        return {
            'type': self.item_type,
            'account_id': self.account_id,
            'jid': self.jid,
            'roster_id': self.roster_id,
            'bookmark_id': self.bookmark_id,
            'is_muc': self.is_muc,
            'name': self.name,
            'presence': self.presence,
            'unread_count': self.unread_count,
            'subscription': self.subscription,
            'blocked': self.blocked,
            'typing': self.typing,
            'autojoin': self.autojoin,
            'call_state': self.call_state
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ContactDisplayData':
        """
        Create from dictionary (loaded from Qt.UserRole).

        Args:
            data: Dictionary from QTreeWidgetItem.data(0, Qt.UserRole)

        Returns:
            ContactDisplayData instance
        """
        return cls(
            jid=data.get('jid', ''),
            name=data.get('name', ''),
            account_id=data.get('account_id', 0),
            item_type=data.get('type', 'contact'),
            roster_id=data.get('roster_id'),
            bookmark_id=data.get('bookmark_id'),
            is_muc=data.get('is_muc', False),
            presence=data.get('presence', 'unavailable'),
            unread_count=data.get('unread_count', 0),
            subscription=data.get('subscription', 'both'),
            blocked=data.get('blocked', False),
            typing=data.get('typing', False),
            autojoin=data.get('autojoin', False),
            call_state=data.get('call_state')
        )


@dataclass
class AccountDisplayData:
    """
    Data model for account roster display.

    Simplified version for account-level items.
    """

    account_id: int
    bare_jid: str
    name: str  # Alias or JID
    is_connected: bool = False
    total_unread: int = 0

    # ASCII mode colors - now theme-aware (see get_text_color_ascii)
    # Colors are fetched from app/styles/roster_themes.py based on current theme

    def to_display_string(self, uses_emoji: bool = True) -> str:
        """
        Build display string for account.

        Args:
            uses_emoji: True for emoji icons (🏛️), False for text-only

        Format (emoji): [connection_icon] 🏛️  [Name] (unread)
        Format (text): [Name] (unread)
        """
        if uses_emoji:
            return self._to_display_string_classic()
        else:
            return self._to_display_string_ascii()

    def _to_display_string_classic(self) -> str:
        """Generate classic display string with emoji icons."""
        parts = []

        # Connection indicator
        connection_icon = "🔷" if self.is_connected else "◇"  # Blue diamond or hollow diamond
        parts.append(connection_icon)

        # Account icon
        parts.append('🏛️')

        # Name in brackets
        parts.append(f"[{self.name}]")

        # Unread count
        if self.total_unread > 0:
            parts.append(f"({self.total_unread})")

        return ' '.join(parts)

    def _to_display_string_ascii(self) -> str:
        """Generate ASCII display string (text-only, no emojis)."""
        parts = []

        # Name in brackets
        parts.append(f"[{self.name}]")

        # Unread count
        if self.total_unread > 0:
            parts.append(f"({self.total_unread})")

        return ' '.join(parts)

    def get_font_style(self) -> dict:
        """Get font styling for account."""
        return {
            'bold': self.total_unread > 0,
            'italic': False,
            'underline': True  # Accounts always underlined
        }

    def get_text_color_ascii(self, theme: str = 'dark') -> Optional[str]:
        """
        Get text color for ASCII mode based on connection state and theme.

        Args:
            theme: Current theme name ('light', 'dark', 'terminal', 'gruvbox', 'light_gray')

        Returns:
            Hex color string or None for default
        """
        from ...styles.roster_themes import get_roster_colors
        colors = get_roster_colors(theme)

        if self.is_connected:
            return colors['account_connected']
        else:
            return colors['account_disconnected']

    def get_tooltip(self) -> str:
        """
        Generate tooltip text with detailed information.

        Returns:
            Multi-line tooltip string
        """
        lines = []

        lines.append(f"Account: {self.bare_jid}")
        lines.append(f"Status: {'Connected' if self.is_connected else 'Disconnected'}")

        if self.total_unread > 0:
            lines.append(f"Total Unread: {self.total_unread}")

        return '\n'.join(lines)

    def to_dict(self) -> dict:
        """Convert to dictionary for Qt.UserRole."""
        return {
            'type': 'account',
            'account_id': self.account_id,
            'bare_jid': self.bare_jid,
            'name': self.name,
            'is_connected': self.is_connected,
            'total_unread': self.total_unread
        }
