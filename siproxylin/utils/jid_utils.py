"""
JID utility functions for XMPP account management.
"""

import zlib


def generate_resource(bare_jid: str) -> str:
    """
    Generate a unique, deterministic resource identifier for an XMPP account.

    Uses CRC32 checksum of the bare JID to create a unique 8-character hex suffix.
    Format: siproxylin.{8-hex-chars}

    Examples:
        user@example.com -> siproxylin.a3f2b1c4
        alice@jabber.org -> siproxylin.7f8e9d6c

    Args:
        bare_jid: The bare JID (user@domain) without resource

    Returns:
        Resource string (19 characters, compliant with RFC 6122/7622 1023 byte limit)

    Note:
        - CRC32 produces exactly 32 bits = 8 hex characters
        - Same JID always produces same resource (deterministic)
        - Different JIDs produce different resources (good distribution)
    """
    # Calculate CRC32 checksum of the JID
    crc = zlib.crc32(bare_jid.encode('utf-8')) & 0xffffffff  # Ensure unsigned 32-bit

    # Format as 8 lowercase hex characters
    return f"siproxylin.{crc:08x}"
