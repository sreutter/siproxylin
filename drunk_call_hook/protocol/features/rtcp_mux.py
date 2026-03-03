"""
RtcpMuxHandler - Handles rtcp-mux negotiation between SDP and Jingle

This module encapsulates the logic for RTP/RTCP multiplexing (rtcp-mux)
negotiation during Jingle ↔ SDP conversion.

Background:
-----------
rtcp-mux (RFC 5761) allows RTP and RTCP packets to share the same port/component,
reducing the number of ICE candidates needed from 2 (component 1 for RTP,
component 2 for RTCP) down to 1 (component 1 for both).

XEP-0167 (Jingle RTP Sessions) represents this with a simple <rtcp-mux/> element.
SDP represents it with the "a=rtcp-mux" attribute.

Negotiation Rules:
------------------
1. Offer can propose rtcp-mux (optional in both SDP and Jingle)
2. Answer MUST echo rtcp-mux if and only if it accepts it
3. Both sides must support it, or neither uses it
4. If negotiated, only component=1 candidates are needed
5. Legacy clients may still send component=2 candidates for compatibility

Conversations.im Compatibility:
------------------------------
Conversations.im sends both component=1 and component=2 candidates even when
rtcp-mux is present, for backward compatibility with clients that don't support it.
We accept both components but webrtcbin only uses component=1 when rtcp-mux is active.

References:
-----------
- RFC 5761: Multiplexing RTP Data and Control Packets on a Single Port
- XEP-0167: Jingle RTP Sessions (Section 8: Multiplexing)
- https://xmpp.org/extensions/xep-0167.html#format-mux
"""


class RtcpMuxHandler:
    """
    Handles rtcp-mux negotiation between SDP and Jingle.

    This class provides static methods to determine when rtcp-mux should be
    included in SDP or Jingle based on the negotiation state and peer capabilities.

    All methods are stateless and can be called without instantiation.
    """

    @staticmethod
    def should_add_to_offer_sdp(peer_jid: str = None) -> bool:
        """
        Should we include a=rtcp-mux in SDP offer sent to call service?

        Args:
            peer_jid: The JID of the peer (reserved for future per-peer config)

        Returns:
            True - Always let webrtcbin negotiate rtcp-mux

        Rationale:
            We always include rtcp-mux in offers to the call service (webrtcbin).
            The call service will decide whether to use it based on its capabilities.
            This is the standard WebRTC behavior.
        """
        return True  # Always let webrtcbin decide

    @staticmethod
    def should_add_to_offer_jingle(sdp_has_rtcp_mux: bool) -> bool:
        """
        Should we include <rtcp-mux/> in Jingle session-initiate?

        Args:
            sdp_has_rtcp_mux: Whether the SDP offer from webrtcbin has a=rtcp-mux

        Returns:
            True if SDP has rtcp-mux (echo what webrtcbin wants)

        Rationale:
            We echo whatever webrtcbin put in the SDP. If webrtcbin included
            a=rtcp-mux, it means it supports and wants to negotiate it, so we
            include <rtcp-mux/> in the Jingle offer to the peer.
        """
        return sdp_has_rtcp_mux

    @staticmethod
    def should_add_to_answer_sdp(jingle_has_rtcp_mux: bool) -> bool:
        """
        Should we include a=rtcp-mux in SDP answer to call service?

        Args:
            jingle_has_rtcp_mux: Whether the Jingle offer has <rtcp-mux/>

        Returns:
            True if Jingle offer had rtcp-mux (peer supports it)

        Rationale:
            If the peer included <rtcp-mux/> in their Jingle offer, they support
            it. We include a=rtcp-mux in the SDP we send to webrtcbin so it knows
            the peer supports rtcp-mux and can negotiate it in the answer.
        """
        return jingle_has_rtcp_mux

    @staticmethod
    def should_add_to_answer_jingle(sdp_has_rtcp_mux: bool, offer_had_rtcp_mux: bool) -> bool:
        """
        Should we include <rtcp-mux/> in Jingle session-accept?

        Args:
            sdp_has_rtcp_mux: Whether the SDP answer from webrtcbin has a=rtcp-mux
            offer_had_rtcp_mux: Whether the Jingle offer had <rtcp-mux/>

        Returns:
            True if BOTH offer had it AND SDP answer has it (both sides agree)

        Rationale:
            rtcp-mux is only negotiated if BOTH sides support it. The answer can
            only include rtcp-mux if:
            1. The offer proposed it (offer_had_rtcp_mux)
            2. We accept it (sdp_has_rtcp_mux - webrtcbin accepts it)

            If either condition is false, rtcp-mux is not used.
        """
        return sdp_has_rtcp_mux and offer_had_rtcp_mux

    @staticmethod
    def should_accept_component2_candidate(rtcp_mux_negotiated: bool) -> bool:
        """
        Should we accept component=2 candidates even if rtcp-mux is negotiated?

        Args:
            rtcp_mux_negotiated: Whether rtcp-mux was successfully negotiated

        Returns:
            True - Always accept for compatibility

        Rationale:
            Conversations.im (and possibly other clients) send both component=1
            and component=2 candidates even when rtcp-mux is negotiated, for
            backward compatibility with clients that don't support rtcp-mux.

            We accept both components and pass them to webrtcbin. If rtcp-mux
            is negotiated, webrtcbin will only use component=1. The component=2
            candidates are harmless - they just won't be used.

            This is more robust than trying to filter them out, as it handles
            clients with various compatibility modes.
        """
        return True  # Always accept for Conversations.im compatibility
