"""
TrickleICEHandler - Handles trickle ICE timing issues

This module manages the timing challenges associated with trickle ICE, particularly
when peers send offers with zero candidates and rely entirely on transport-info
messages to deliver ICE candidates.

Background:
-----------
Trickle ICE (XEP-0176) allows ICE candidates to be sent incrementally via
transport-info messages instead of including all candidates in the session-initiate.

This creates a race condition:
1. Peer sends session-initiate with SDP containing 0 candidates
2. We call setRemoteDescription(offer) with 0 candidates
3. ICE checking starts with 0 remote candidates
4. ~400ms later, candidates arrive via transport-info
5. Too late - ICE checks already started with incomplete candidate list

The Problem:
------------
Conversations.im sends "trickle-only" offers (0 candidates in SDP) and expects
the answerer to wait for transport-info before creating an answer. If we create
the answer immediately, ICE connectivity fails due to the race condition.

The Solution:
-------------
Detect trickle-only offers and defer answer creation until the first
transport-info arrives (or a timeout expires as a safety mechanism).

References:
-----------
- XEP-0176: Jingle ICE-UDP Transport Method (Trickle ICE)
- https://xmpp.org/extensions/xep-0176.html
"""

import asyncio
import logging
from enum import Enum
from typing import Dict, Optional, Callable, Any


class TrickleICEState(Enum):
    """States for trickle ICE handling."""
    NORMAL = "normal"                      # Has candidates in offer (>0)
    WAITING_FOR_CANDIDATES = "waiting"     # 0 candidates, waiting for transport-info
    CANDIDATES_ARRIVED = "arrived"         # Candidates arrived via transport-info
    TIMEOUT = "timeout"                    # Timeout waiting for candidates


class TrickleICEHandler:
    """
    Handles trickle ICE timing issues for deferred answer creation.

    Problem: Conversations.im sends offers with 0 candidates in SDP,
    relying entirely on transport-info. If we call setRemoteDescription
    immediately, ICE starts with 0 candidates, then candidates arrive 400ms later.

    Solution: Detect trickle-only offers, defer answer creation until
    first transport-info arrives (or timeout).
    """

    def __init__(self, timeout_seconds: float = 5.0, logger: Optional[logging.Logger] = None):
        """
        Initialize TrickleICEHandler.

        Args:
            timeout_seconds: How long to wait for candidates before proceeding anyway
            logger: Optional logger instance
        """
        self.timeout = timeout_seconds
        self.logger = logger or logging.getLogger(__name__)
        self._pending_offers: Dict[str, Dict[str, Any]] = {}  # {session_id: {sdp, state, data, timer_task}}

    def should_defer_answer(self, sdp: str) -> bool:
        """
        Should we defer answer creation for this offer?

        Args:
            sdp: SDP offer string

        Returns:
            True if SDP has 0 candidates (trickle-only offer)
        """
        candidate_count = sdp.count('a=candidate:')
        is_trickle_only = candidate_count == 0

        if is_trickle_only:
            self.logger.info(f"[TRICKLE-ICE] Detected trickle-only offer (0 candidates)")
        else:
            self.logger.info(f"[TRICKLE-ICE] Normal offer ({candidate_count} candidates)")

        return is_trickle_only

    def defer_answer(self, session_id: str, sdp: str, peer_jid: str,
                     media_types: list, on_timeout: Callable) -> None:
        """
        Defer answer creation until candidates arrive.

        Args:
            session_id: Session ID
            sdp: SDP offer (stored for later)
            peer_jid: Peer JID (stored for later)
            media_types: Media types from offer (stored for later)
            on_timeout: Async callback if timeout expires before candidates arrive
        """
        # Store offer data
        self._pending_offers[session_id] = {
            'sdp': sdp,
            'peer_jid': peer_jid,
            'media_types': media_types,
            'state': TrickleICEState.WAITING_FOR_CANDIDATES
        }

        self.logger.info(f"[TRICKLE-ICE] Deferring answer creation for {session_id}")

        # Schedule timeout
        async def timeout_handler():
            await asyncio.sleep(self.timeout)
            if session_id in self._pending_offers:
                pending = self._pending_offers[session_id]
                if pending['state'] == TrickleICEState.WAITING_FOR_CANDIDATES:
                    self.logger.warning(f"[TRICKLE-ICE] Timeout waiting for candidates for {session_id} - proceeding anyway")
                    pending['state'] = TrickleICEState.TIMEOUT
                    await on_timeout(session_id)

        task = asyncio.create_task(timeout_handler())
        self._pending_offers[session_id]['timer_task'] = task

    def candidates_arrived(self, session_id: str) -> bool:
        """
        Notify that candidates arrived via transport-info.

        Args:
            session_id: Session ID

        Returns:
            True if we were waiting for them (answer should be created now)
        """
        if session_id not in self._pending_offers:
            return False

        pending = self._pending_offers[session_id]
        if pending['state'] == TrickleICEState.WAITING_FOR_CANDIDATES:
            self.logger.info(f"[TRICKLE-ICE] First candidates arrived for {session_id}, triggering deferred answer creation")

            # Cancel timeout
            if 'timer_task' in pending:
                pending['timer_task'].cancel()

            pending['state'] = TrickleICEState.CANDIDATES_ARRIVED
            return True

        return False

    def get_deferred_offer(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get deferred offer data and clean up.

        Args:
            session_id: Session ID

        Returns:
            Dict with keys: 'sdp', 'peer_jid', 'media_types', 'state'
            or None if session not found
        """
        if session_id not in self._pending_offers:
            return None

        data = self._pending_offers[session_id]
        del self._pending_offers[session_id]

        return {
            'sdp': data['sdp'],
            'peer_jid': data['peer_jid'],
            'media_types': data['media_types'],
            'state': data['state']
        }

    def is_deferred(self, session_id: str) -> bool:
        """
        Check if answer creation is currently deferred for this session.

        Args:
            session_id: Session ID

        Returns:
            True if answer is deferred (waiting for candidates or timed out)
        """
        return session_id in self._pending_offers

    def cancel_deferred(self, session_id: str) -> None:
        """
        Cancel deferred answer creation (e.g., if call is terminated).

        Args:
            session_id: Session ID
        """
        if session_id in self._pending_offers:
            pending = self._pending_offers[session_id]

            # Cancel timeout task
            if 'timer_task' in pending:
                pending['timer_task'].cancel()

            del self._pending_offers[session_id]
            self.logger.info(f"[TRICKLE-ICE] Cancelled deferred answer for {session_id}")
