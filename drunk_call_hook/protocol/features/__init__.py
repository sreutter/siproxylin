"""
WebRTC Feature Handlers for Jingle ↔ SDP Conversion

This package contains specialized handlers for WebRTC features that require
special handling during Jingle ↔ SDP conversion.

Each handler encapsulates the logic for a specific WebRTC feature:
- rtcp_mux: RTP/RTCP multiplexing negotiation
- trickle_ice: Trickle ICE candidate timing management
- ssrc: SSRC (Synchronization Source) parsing and filtering
- bundle: BUNDLE group negotiation (future)
"""

from .rtcp_mux import RtcpMuxHandler
from .trickle_ice import TrickleICEHandler, TrickleICEState
from .ssrc import SSRCHandler

__all__ = ['RtcpMuxHandler', 'TrickleICEHandler', 'TrickleICEState', 'SSRCHandler']
