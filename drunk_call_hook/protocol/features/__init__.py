"""
WebRTC Feature Handlers for Jingle ↔ SDP Conversion

This package contains specialized handlers for WebRTC features that require
special handling during Jingle ↔ SDP conversion.

Each handler encapsulates the logic for a specific WebRTC feature:
- rtcp_mux: RTP/RTCP multiplexing negotiation
- trickle_ice: Trickle ICE candidate timing management
- bundle: BUNDLE group negotiation (future)
- ssrc: SSRC parameter filtering (future)
"""

from .rtcp_mux import RtcpMuxHandler
from .trickle_ice import TrickleICEHandler, TrickleICEState

__all__ = ['RtcpMuxHandler', 'TrickleICEHandler', 'TrickleICEState']
