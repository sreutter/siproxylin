"""
Protocol adapters for call signaling.

Currently supports:
- Jingle (XEP-0166/0167) ↔ SDP conversion
"""

from .jingle import JingleAdapter

__all__ = ["JingleAdapter"]
