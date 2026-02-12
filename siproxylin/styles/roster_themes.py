"""
Roster styling system for contact list display.

Provides complete styling units (RosterStyle) instead of piecemeal color lookups.
Separates concerns: icon style (emoji vs text) and color mode (steady vs dynamic).
"""

from dataclasses import dataclass
from typing import Optional
from PySide6.QtGui import QColor


@dataclass
class RosterStyle:
    """
    Complete roster styling unit.

    Encapsulates all styling concerns for roster display:
    - Icon style (emoji vs text indicators)
    - Color mode (steady theme color vs dynamic presence colors)
    - All colors as QColor objects (ready to use)

    Roster code just uses this - no theme name strings, no mode checks.
    """

    # Icon style
    uses_emoji: bool  # True = emoji (🟢), False = text indicators

    # Color mode
    uses_dynamic_colors: bool  # True = presence colors, False = steady theme color

    # Colors (as QColor objects, ready to use)
    default_text_color: QColor
    presence_available_color: QColor
    presence_away_color: QColor
    presence_xa_color: QColor
    presence_dnd_color: QColor
    presence_unavailable_color: QColor
    muc_color: QColor
    call_active_color: QColor
    account_connected_color: QColor
    account_disconnected_color: QColor

    def get_text_color_for_contact(self, presence: str, is_muc: bool = False,
                                    call_state: Optional[str] = None) -> QColor:
        """
        Get text color for a contact based on state.

        Args:
            presence: Contact presence ('available', 'away', etc.)
            is_muc: Whether this is a MUC
            call_state: Active call state (if any)

        Returns:
            QColor for text
        """
        if not self.uses_dynamic_colors:
            # Steady mode - always use theme default
            return self.default_text_color

        # Dynamic mode - color based on state
        # Priority: Call > Presence (MUCs use presence-based colors too)
        if call_state:
            return self.call_active_color

        # MUCs: blue when joined (available), gray when not joined (unavailable)
        if is_muc:
            if presence == 'available':
                return self.muc_color  # Blue for joined MUCs
            else:
                return self.presence_unavailable_color  # Gray for not-joined MUCs

        # Presence colors for 1-to-1 contacts
        presence_map = {
            'available': self.presence_available_color,
            'away': self.presence_away_color,
            'xa': self.presence_xa_color,
            'dnd': self.presence_dnd_color,
            'unavailable': self.presence_unavailable_color,
        }
        return presence_map.get(presence, self.presence_unavailable_color)

    def get_text_color_for_account(self, connected: bool) -> QColor:
        """
        Get text color for account item.

        Args:
            connected: Whether account is connected

        Returns:
            QColor for text
        """
        if not self.uses_dynamic_colors:
            return self.default_text_color

        return self.account_connected_color if connected else self.account_disconnected_color


ROSTER_THEMES = {
    'light': {
        # Default text color (for classic mode)
        'default_text': '#000000',          # Black text for light background

        # Presence colors (darker for light background)
        'presence_available': '#008800',    # Dark green
        'presence_away': '#aa8800',         # Dark yellow
        'presence_xa': '#aa8800',           # Dark yellow
        'presence_dnd': '#cc0000',          # Dark red
        'presence_unavailable': '#666666',  # Dark gray

        # MUC color
        'muc': '#4477aa',                   # Grayish-blue

        # Call state
        'call_active': '#8866cc',           # Dark purple

        # Account connection
        'account_connected': '#008800',     # Dark green
        'account_disconnected': '#666666',  # Dark gray
    },

    'light_gray': {
        # Default text color (for classic mode)
        'default_text': '#000000',          # Black text for light gray background

        # Presence colors (darker for light gray background)
        'presence_available': '#006600',    # Darker green
        'presence_away': '#997700',         # Darker yellow
        'presence_xa': '#997700',           # Darker yellow
        'presence_dnd': '#bb0000',          # Darker red
        'presence_unavailable': '#555555',  # Darker gray

        # MUC color
        'muc': '#336699',                   # Darker grayish-blue

        # Call state
        'call_active': '#7755bb',           # Darker purple

        # Account connection
        'account_connected': '#006600',     # Darker green
        'account_disconnected': '#555555',  # Darker gray
    },

    'dark': {
        # Default text color (for classic mode)
        'default_text': '#e0e0e0',          # Light gray text for dark background

        # Presence colors (brighter for dark background) - current defaults
        'presence_available': '#00AA00',    # Green
        'presence_away': '#CCAA00',         # Yellow
        'presence_xa': '#CCAA00',           # Yellow
        'presence_dnd': '#CC0000',          # Red
        'presence_unavailable': '#808080',  # Gray

        # MUC color
        'muc': '#6699cc',                   # Bright grayish-blue

        # Call state
        'call_active': '#9370DB',           # Medium purple

        # Account connection
        'account_connected': '#00AA00',     # Green
        'account_disconnected': '#808080',  # Gray
    },

    'terminal': {
        # Default text color (for classic mode)
        'default_text': '#00ff00',          # Bright green for terminal aesthetic

        # Presence colors (bright terminal green aesthetic)
        'presence_available': '#00ff00',    # Bright green
        'presence_away': '#ffff00',         # Bright yellow
        'presence_xa': '#ffff00',           # Bright yellow
        'presence_dnd': '#ff0000',          # Bright red
        'presence_unavailable': '#666666',  # Dark gray

        # MUC color
        'muc': '#00ffff',                   # Bright cyan (terminal aesthetic)

        # Call state
        'call_active': '#ff00ff',           # Bright magenta

        # Account connection
        'account_connected': '#00ff00',     # Bright green
        'account_disconnected': '#666666',  # Dark gray
    },

    'gruvbox': {
        # Default text color (for classic mode)
        'default_text': '#ebdbb2',          # Gruvbox foreground (cream)

        # Presence colors (gruvbox palette)
        'presence_available': '#b8bb26',    # Gruvbox bright green
        'presence_away': '#fabd2f',         # Gruvbox bright yellow
        'presence_xa': '#fabd2f',           # Gruvbox bright yellow
        'presence_dnd': '#fb4934',          # Gruvbox bright red
        'presence_unavailable': '#928374',  # Gruvbox gray

        # MUC color
        'muc': '#83a598',                   # Gruvbox bright blue

        # Call state
        'call_active': '#d3869b',           # Gruvbox bright purple

        # Account connection
        'account_connected': '#b8bb26',     # Gruvbox bright green
        'account_disconnected': '#928374',  # Gruvbox gray
    },
}


def get_roster_colors(theme_name: str) -> dict:
    """
    Get roster colors for a theme.

    Args:
        theme_name: Theme name ('light', 'dark', 'terminal', 'gruvbox', 'light_gray')

    Returns:
        Dictionary with color strings (hex format) for roster styling,
        or default colors if theme not found
    """
    # Default to 'dark' if theme not found
    colors = ROSTER_THEMES.get(theme_name, ROSTER_THEMES['dark'])

    # Return as strings (hex format) - contact_display.py uses QColor() on them
    return colors.copy()


def get_roster_qcolors(theme_name: str) -> dict:
    """
    Get roster colors as QColor objects for a theme.

    Args:
        theme_name: Theme name ('light', 'dark', 'terminal', 'gruvbox', 'light_gray')

    Returns:
        Dictionary with QColor objects for roster styling
    """
    colors = get_roster_colors(theme_name)

    return {
        key: QColor(value) for key, value in colors.items()
    }


def create_roster_style(theme_name: str, uses_emoji: bool = True) -> RosterStyle:
    """
    Create a complete RosterStyle from theme.

    Args:
        theme_name: Theme name ('light', 'dark', etc.)
        uses_emoji: True for classic mode (emoji + steady colors),
                    False for ASCII mode (text indicators + dynamic colors)

    Returns:
        RosterStyle with all colors as QColor objects
    """
    colors = get_roster_colors(theme_name)

    # Classic mode: emoji + steady theme color
    # ASCII mode: text indicators + dynamic presence colors
    uses_dynamic_colors = not uses_emoji

    return RosterStyle(
        uses_emoji=uses_emoji,
        uses_dynamic_colors=uses_dynamic_colors,
        default_text_color=QColor(colors['default_text']),
        presence_available_color=QColor(colors['presence_available']),
        presence_away_color=QColor(colors['presence_away']),
        presence_xa_color=QColor(colors['presence_xa']),
        presence_dnd_color=QColor(colors['presence_dnd']),
        presence_unavailable_color=QColor(colors['presence_unavailable']),
        muc_color=QColor(colors['muc']),
        call_active_color=QColor(colors['call_active']),
        account_connected_color=QColor(colors['account_connected']),
        account_disconnected_color=QColor(colors['account_disconnected']),
    )
