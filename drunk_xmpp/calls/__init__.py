"""
DrunkXMPP Calls Module - Audio/Video Calling Support

This module provides complete XMPP calling functionality:
- XEP-0353: Jingle Message Initiation (propose/proceed/accept/reject)
- XEP-0166: Jingle (base signaling framework)
- XEP-0167: Jingle RTP Sessions (audio/video)
- XEP-0176: Jingle ICE-UDP Transport
- XEP-0320: DTLS-SRTP encryption

Architecture:
- mixin.py: CallsMixin for XEP-0353 message handlers
- jingle.py: Jingle IQ stanza handlers (session negotiation)
- sdp.py: SDP ↔ Jingle XML conversion
- media.py: GStreamer media pipeline management
"""

from .mixin import CallsMixin

__all__ = ['CallsMixin']
