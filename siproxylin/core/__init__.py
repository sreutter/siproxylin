"""
Core business logic for DRUNK-XMPP-GUI.

Provides access to the account brewery and XMPP account management.
"""

# New brewery structure
from .brewery import AccountBrewery, XMPPAccount, get_account_brewery

# Backwards compatibility aliases (will be removed after full migration)
AccountManager = AccountBrewery
get_account_manager = get_account_brewery

__all__ = [
    # New names (preferred)
    'AccountBrewery',
    'get_account_brewery',
    'XMPPAccount',
    # Old names (backwards compatibility)
    'AccountManager',
    'get_account_manager',
]
