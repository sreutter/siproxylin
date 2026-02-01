"""
Chat View - Conversation display and interaction.

The tap room where users view and interact with XMPP conversations.

Main Component:
- ChatViewWidget: Main coordinator for chat display

Taps (Internal Components):
- ChatHeaderWidget: Header with contact info and controls
- MessageDisplayWidget: Message list display
- MessageInputField: Text input with typing indicators
- LandingPage: Welcome screen (no conversation)
- ScrollManager: Auto-scroll management
- ContextMenuManager: Right-click menus
- SpellCheckManager: Spell checking UI

Status: Under refactoring - migrating from monolithic chat_view.py
"""

# Import ChatViewWidget from chat_view.py in this package
from .chat_view import ChatViewWidget

__all__ = ['ChatViewWidget']
