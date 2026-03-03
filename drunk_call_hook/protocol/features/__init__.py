"""
WebRTC Feature Handlers for Jingle ↔ SDP Conversion

This package contains specialized handlers for WebRTC features that require
special handling during Jingle ↔ SDP conversion.

Each handler encapsulates the logic for a specific WebRTC feature:
- rtcp_mux: RTP/RTCP multiplexing negotiation
- trickle_ice: Trickle ICE candidate handling (future)
- bundle: BUNDLE group negotiation (future)
- ssrc: SSRC parameter filtering (future)
"""

from .rtcp_mux import RtcpMuxHandler

__all__ = ['RtcpMuxHandler']
