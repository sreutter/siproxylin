"""
JID utility functions for XMPP account management.
"""

import secrets


def generate_resource(bare_jid: str) -> str:
    """
    Generate a unique, random resource identifier for an XMPP account.

    Uses cryptographically secure random generator to create a 12-character hex suffix.
    Format: siproxylin.{12-hex-chars}

    Examples:
        user@example.com -> siproxylin.a3f2b1c49e8d
        user@example.com -> siproxylin.7f8e9d6c2a1b  (different on each call)

    Args:
        bare_jid: The bare JID (user@domain) without resource (unused, kept for API compatibility)

    Returns:
        Resource string (23 characters, compliant with RFC 6122/7622 1023 byte limit)

    Note:
        - Uses secrets.token_hex() for cryptographically secure randomness
        - Each call produces a DIFFERENT resource (allows multi-device usage)
        - 12 hex chars = 48 bits of entropy (281 trillion combinations)
        - Prevents resource conflicts when same account used on multiple devices
    """
    # Generate 12 random hex characters (48 bits of entropy)
    random_suffix = secrets.token_hex(6)  # 6 bytes = 12 hex chars

    return f"siproxylin.{random_suffix}"
