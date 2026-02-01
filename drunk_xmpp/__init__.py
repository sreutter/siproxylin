"""
DRUNK-XMPP - Privacy-focused XMPP client library

For detailed navigation guide showing which module contains which functionality,
see the full documentation at the top of client.py

This is a work-in-progress refactoring. Currently all code is in client.py.
Future: Code will be split into focused modules (muc.py, messaging.py, etc.)
"""

# Import main class, OMEMO storage, and metadata class
from .client import DrunkXMPP, OMEMOStorage, MessageMetadata

# Import registration functions (XEP-0077)
from .registration import (
    create_registration_session,
    query_registration_form,
    submit_registration,
    close_registration_session,
    change_password,
    delete_account
)

__version__ = "1.0.0-refactoring"
__all__ = [
    "DrunkXMPP",
    "OMEMOStorage",
    "MessageMetadata",
    "create_registration_session",
    "query_registration_form",
    "submit_registration",
    "close_registration_session",
    "change_password",
    "delete_account"
]
