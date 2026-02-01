"""
Version information for Siproxylin.

This file contains version and build information.
Update this file for releases or use environment variables for CI/CD.
"""

import os

# Version info - update for releases
VERSION = os.getenv('SIPROXYLIN_VERSION', '0.0.3')
BUILD_CODENAME = os.getenv('SIPROXYLIN_CODENAME', 'Bottled')
APP_NAME = 'Siproxylin'

# XEPs supported by this client
# Keep this list updated when adding new XEP support
SUPPORTED_XEPS = [
    ('0030', 'Service Discovery'),
    ('0045', 'Multi-User Chat'),
    ('0054', 'vcard-temp'),
    ('0077', 'In-Band Registration'),
    ('0084', 'User Avatar (PEP)'),
    ('0085', 'Chat State Notifications'),
    ('0092', 'Software Version'),
    ('0115', 'Entity Capabilities'),
    ('0153', 'vCard-Based Avatars'),
    ('0158', 'CAPTCHA Forms'),
    ('0184', 'Message Delivery Receipts'),
    ('0191', 'Blocking Command'),
    ('0198', 'Stream Management'),
    ('0199', 'XMPP Ping'),
    ('0215', 'External Service Discovery'),
    ('0221', 'Media Element'),
    ('0231', 'Bits of Binary'),
    ('0280', 'Message Carbons'),
    ('0308', 'Last Message Correction'),
    ('0313', 'Message Archive Management'),
    ('0333', 'Chat Markers'),
    ('0353', 'Jingle Message Initiation'),
    ('0359', 'Unique and Stable Stanza IDs'),
    ('0363', 'HTTP File Upload'),
    ('0384', 'OMEMO Encryption (0.3.0 & 0.8.0+)'),
    ('0402', 'PEP Native Bookmarks'),
    ('0421', 'Occupant ID (MUC)'),
    ('0444', 'Message Reactions'),
    ('0461', 'Message Replies'),
]


def get_version_string():
    """Get formatted version string."""
    return f"{APP_NAME} {VERSION}"


def get_full_version_info():
    """Get full version info dictionary."""
    return {
        'app_name': APP_NAME,
        'version': VERSION,
        'codename': BUILD_CODENAME,
        'xeps': SUPPORTED_XEPS
    }
