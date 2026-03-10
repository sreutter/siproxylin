# Jingle Cleanup & Refactoring Plan

**Status**: Planning
**Date**: 2026-03-02
**Urgency**: HIGH - Current code has scattered fixes that violate ADR principles

**See Also**:
- docs/ADR.md - Rule #5: Use library methods, no manual XML parsing
- drunk_call_hook/protocol/jingle.py - Current 1881-line implementation
- docs/CALLS/4-GRPC-PLAN.md - C++ side (clean)

---

## Current Problems

### 1. SDP ↔ Jingle Conversion Scattered Everywhere

**Current state**: Business logic mixed with conversion logic

- `_sdp_to_jingle()` at line 1298: 257 lines of XML building
- `_jingle_to_sdp()` at line 1556: 126 lines of SDP parsing
- `_extract_offer_details()` at line 1123: 96 lines extracting WebRTC features
- `_echo_offer_features()` at line 1220: 65 lines echoing features

**Problem**: Cannot test conversion independently, hard to debug, violates single responsibility.

### 2. rtcp-mux "Voodoo"

**Evidence of confusion**:

```python
# Line 1390: Check if SDP has rtcp-mux
has_rtcp_mux = any(line.strip() == 'a=rtcp-mux' for line in media_lines)

# Line 1499: Add rtcp-mux to Jingle if SDP has it
if has_rtcp_mux:
    ET.SubElement(description, '{urn:xmpp:jingle:apps:rtp:1}rtcp-mux')
    self.logger.debug(f"Added rtcp-mux to Jingle (from Pion's SDP)")

# Line 1621-1626: CRITICAL comment - DON'T add rtcp-mux to SDP even if Jingle has it!
# CRITICAL: Do NOT add rtcp-mux to SDP even if Jingle has it
# Conversations.im/Monocles expect BOTH component 1 and component 2 candidates
# even when rtcp-mux is present (for backward compatibility)
# By omitting rtcp-mux from SDP, Pion will gather both components
# Then Pion will include rtcp-mux in the SDP answer (negotiation)
# We'll convert that back to Jingle with <rtcp-mux /> in session-accept
```

**Translation**: We're lying to the call service (hiding rtcp-mux in offers), then translating it back. This is brittle and confusing.

**Root cause**: Trying to work around Conversations.im expectations + Pion behavior instead of handling it correctly.

### 3. Trickle ICE Race Condition Workarounds

**Line 255-280**: Defer answer creation if 0 candidates in offer
```python
if candidate_count == 0:
    self.logger.info(f"[TRICKLE-ICE] Offer has 0 candidates - deferring answer until candidates arrive")
    self.sessions[sid]['waiting_for_candidates'] = True
    self.sessions[sid]['sdp_offer'] = sdp_offer  # Store for later

    # Safety timeout: If no candidates arrive within 5 seconds, proceed anyway
    async def candidates_timeout():
        await asyncio.sleep(5.0)
        if sid in self.sessions and self.sessions[sid].get('waiting_for_candidates', False):
            self.logger.warning(f"[TRICKLE-ICE] Timeout waiting for candidates for {sid}")
            self.sessions[sid]['waiting_for_candidates'] = False
            if self.on_candidates_ready:
                await self.on_candidates_ready(sid)
    asyncio.create_task(candidates_timeout())
```

**Problem**: Trying to work around timing issues with asyncio tasks and state flags. Fragile.

**Line 425-444**: Check in transport-info handler if we were waiting
```python
waiting_for_candidates = session.get('waiting_for_candidates', False)
if waiting_for_candidates and len(candidates) > 0:
    self.logger.info(f"[TRICKLE-ICE] First candidates arrived for {sid}, now proceeding")
    session['waiting_for_candidates'] = False
    # Add candidates to Pion FIRST
    if self.on_ice_candidate_received:
        for candidate in candidates:
            await self.on_ice_candidate_received(sid, candidate)
    # NOW trigger deferred answer creation
    if self.on_candidates_ready:
        await self.on_candidates_ready(sid)
    return  # Don't process candidates again below
```

**Problem**: State machine in callbacks, hard to follow control flow.

### 4. Component 1/2 Handling

**Line 401-417**: Accept all components from peer
```python
# Accept ALL components from peer (including component 2)
# Hypothesis: Conversations' nomination logic requires seeing all candidates it sent
# Pion will create cross-component pairs that fail, but same-component pairs should succeed
component = candidate_el.get('component', '1')
```

**Problem**: Accepting component=2 candidates even though we're using rtcp-mux. Wastes resources, confusing.

### 5. Candidate Queuing Logic

**Multiple locations**:
- Line 337-342: Flush pending candidates AFTER setting remote description
- Line 483-493: Queue candidates based on session state
- Line 765-773: Inject candidates into session-initiate (hybrid mode)
- Line 1715-1722: More queuing in _on_bridge_connection_state

**Problem**: Queuing logic duplicated across 4 places, easy to miss edge cases.

### 6. SSRC Parameter Filtering

**Line 1442-1495**: Complex logic to filter SSRC params to match offer
```python
should_add_ssrc = False
allowed_ssrc_params = []
if include_ssrc and session_id and session_id in self.sessions:
    offer_details = self.sessions[session_id].get('offer_details', {})
    should_add_ssrc = offer_details.get('has_ssrc', False)
    allowed_ssrc_params = offer_details.get('ssrc_params', [])

if should_add_ssrc:
    ssrc_info = {}  # {ssrc: {attr_name: attr_value}}
    for line in media_lines:
        if line.startswith('a=ssrc:'):
            # ... 53 lines of parsing and filtering ...
```

**Problem**: Manually parsing SDP a=ssrc lines, filtering params to match what was in offer. Should be abstracted.

### 7. Manual XML Parsing Violates ADR Rule #5

**Examples**:
- Line 167: `jingle = iq.xml.find('{urn:xmpp:jingle:1}jingle')`
- Line 209: `contents = jingle.findall('{urn:xmpp:jingle:1}content')`
- Line 214: `description = content.find('{urn:xmpp:jingle:apps:rtp:1}description')`
- Hundreds more throughout the file

**ADR Rule #5**: "NO manual XML parsing like `msg.find('{urn:xmpp:sid:0}origin-id')`. Use slixmpp's built-in methods."

**Problem**: This is exactly what we're doing, but for Jingle. Slixmpp doesn't have Jingle stanzas built-in, so we violate the spirit of the rule.

---

## Proposed Solution: JingleSDPConverter Class

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     JingleAdapter                            │
│  (Business Logic - unchanged public API)                     │
├──────────────────────────────────────────────────────────────┤
│  - send_offer(), send_answer(), terminate()                  │
│  - Session state management                                  │
│  - Callback wiring                                           │
│  - XEP-0353 message handling                                 │
└─────────────────────────┬────────────────────────────────────┘
                          ↓ uses
┌──────────────────────────────────────────────────────────────┐
│                 JingleSDPConverter                           │
│  (Pure conversion, NO business logic)                        │
├──────────────────────────────────────────────────────────────┤
│  + sdp_to_jingle(sdp: str, offer_context: dict) → Element   │
│  + jingle_to_sdp(jingle: Element, role: str) → str          │
│  + extract_offer_context(jingle: Element) → dict            │
│                                                              │
│  Private helpers:                                            │
│  - _parse_sdp_media_section(lines: List[str]) → MediaDesc   │
│  - _build_jingle_content(media: MediaDesc) → Element        │
│  - _parse_ice_candidate_sdp(line: str) → ICECandidate       │
│  - _build_ice_candidate_jingle(cand: ICECandidate) → Element│
│  - _should_include_component2(config: dict) → bool          │
│  - _normalize_rtcp_mux(sdp: str, for_offer: bool) → str     │
└──────────────────────────────────────────────────────────────┘
                          ↓ uses
┌──────────────────────────────────────────────────────────────┐
│             WebRTC Feature Handlers                          │
│  (Specialized conversion for WebRTC features)                │
├──────────────────────────────────────────────────────────────┤
│  - BundleHandler: BUNDLE group negotiation                   │
│  - RtcpMuxHandler: rtcp-mux negotiation                      │
│  - TrickleICEHandler: Candidate timing, queuing              │
│  - SSRCHandler: SSRC parameter filtering                     │
│  - CodecHandler: Codec params, rtcp-fb                       │
└──────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Pure Functions**: Converter methods are stateless, take input → produce output
2. **No Side Effects**: Don't modify session state, don't send stanzas
3. **Testable**: Can test SDP → Jingle → SDP round-trip without XMPP connection
4. **Explicit Behavior**: No hidden magic, all quirks documented and configurable

---

## Implementation Plan

### Phase 1: Extract Conversion Logic (No Behavior Change)

**Goal**: Move code from JingleAdapter to JingleSDPConverter without changing behavior.

#### Step 1.1: Create JingleSDPConverter Skeleton

**File**: `drunk_call_hook/protocol/jingle_sdp_converter.py`

```python
class JingleSDPConverter:
    """
    Pure converter between SDP and Jingle XML.

    NO business logic, NO side effects, NO state management.
    Pure conversion only.
    """

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

    def jingle_to_sdp(self, jingle: ET.Element, role: str) -> str:
        """
        Convert Jingle XML to SDP.

        Args:
            jingle: <jingle> element from session-initiate or session-accept
            role: "offer" or "answer"

        Returns:
            SDP string
        """
        # Extract from JingleAdapter._jingle_to_sdp()
        pass

    def sdp_to_jingle(self, sdp: str, role: str, offer_context: Optional[dict] = None) -> ET.Element:
        """
        Convert SDP to Jingle XML content elements.

        Args:
            sdp: SDP string (from CreateOffer or CreateAnswer)
            role: "offer" or "answer"
            offer_context: For answers, the context from extract_offer_context()

        Returns:
            <jingle> element with <content> children
        """
        # Extract from JingleAdapter._sdp_to_jingle()
        pass

    def extract_offer_context(self, jingle: ET.Element) -> dict:
        """
        Extract offer details for echoing in answer.

        Args:
            jingle: <jingle> element from session-initiate (offer)

        Returns:
            Dictionary with offer details (BUNDLE, RTP extensions, codec params, etc.)
        """
        # Extract from JingleAdapter._extract_offer_details()
        pass
```

**Test**: Create `tests/test_jingle_sdp_converter.py` with basic SDP ↔ Jingle conversion

#### Step 1.2: Move Conversion Methods

**Tasks**:
1. Copy `_jingle_to_sdp()` → `JingleSDPConverter.jingle_to_sdp()`
2. Copy `_sdp_to_jingle()` → `JingleSDPConverter.sdp_to_jingle()`
3. Copy `_extract_offer_details()` → `JingleSDPConverter.extract_offer_context()`
4. Copy `_echo_offer_features()` → inline into `sdp_to_jingle()` for answers

**Test**: Existing calls still work, no behavior change

#### Step 1.3: Update JingleAdapter to Use Converter

**Changes**:
```python
class JingleAdapter:
    def __init__(self, xmpp_client, call_bridge, ...):
        # ... existing init ...
        self.converter = JingleSDPConverter(logger=self.logger)

    async def _handle_session_initiate(self, iq: Iq, jingle, sid: str):
        # ... existing code ...

        # OLD: sdp_offer = self._jingle_to_sdp(jingle, 'offer')
        # NEW:
        sdp_offer = self.converter.jingle_to_sdp(jingle, 'offer')

        # OLD: offer_details = self._extract_offer_details(jingle)
        # NEW:
        offer_context = self.converter.extract_offer_context(jingle)
        self.sessions[sid]['offer_context'] = offer_context

        # ... rest unchanged ...

    async def send_answer(self, session_id: str, sdp: str):
        # ... existing code ...

        # Get offer context for echoing features
        offer_context = self.sessions[session_id].get('offer_context')

        # OLD: self._sdp_to_jingle(sdp, jingle, session['media'], session_id=session_id, include_ssrc=False)
        # NEW:
        jingle = ET.SubElement(iq.xml, '{urn:xmpp:jingle:1}jingle')
        jingle.set('action', 'session-accept')
        jingle.set('sid', session_id)
        jingle.set('responder', str(self.xmpp.boundjid))

        contents = self.converter.sdp_to_jingle(sdp, 'answer', offer_context=offer_context)
        for content in contents:
            jingle.append(content)

        # ... rest unchanged ...
```

**Test**: All existing tests pass, behavior unchanged

### Phase 2: Clean Up rtcp-mux Handling

**Goal**: Eliminate voodoo, make rtcp-mux handling explicit and correct.

#### Step 2.1: Create RtcpMuxHandler

**File**: `drunk_call_hook/protocol/features/rtcp_mux.py`

```python
class RtcpMuxHandler:
    """
    Handles rtcp-mux negotiation between SDP and Jingle.

    Rules (from RFC 5761 + XEP-0167):
    1. Offer can propose rtcp-mux (optional in SDP/Jingle)
    2. Answer MUST echo rtcp-mux if it accepts it
    3. Both sides MUST support it or neither uses it
    4. If used, only component=1 candidates needed
    5. Legacy clients send both components for compatibility

    Conversations.im quirk:
    - Sends both component=1 and component=2 candidates even with rtcp-mux
    - For backward compatibility with clients that don't support it
    - We accept both but only use component=1 if rtcp-mux negotiated
    """

    @staticmethod
    def should_add_to_offer_sdp(peer_jid: str) -> bool:
        """
        Should we include rtcp-mux in SDP offer sent to call service?

        Answer: YES always. Let webrtcbin negotiate it.
        The call service will include it in the offer if it wants it.
        """
        return True  # Always let webrtcbin decide

    @staticmethod
    def should_add_to_offer_jingle(sdp_has_rtcp_mux: bool) -> bool:
        """
        Should we include <rtcp-mux/> in Jingle session-initiate?

        Answer: YES if SDP has it (echo what webrtcbin wants)
        """
        return sdp_has_rtcp_mux

    @staticmethod
    def should_add_to_answer_sdp(jingle_has_rtcp_mux: bool) -> bool:
        """
        Should we include rtcp-mux in SDP answer to call service?

        Answer: YES if Jingle offer had it (peer supports it)
        """
        return jingle_has_rtcp_mux

    @staticmethod
    def should_add_to_answer_jingle(sdp_has_rtcp_mux: bool, offer_had_rtcp_mux: bool) -> bool:
        """
        Should we include <rtcp-mux/> in Jingle session-accept?

        Answer: YES if BOTH offer had it AND SDP answer has it (both sides agree)
        """
        return sdp_has_rtcp_mux and offer_had_rtcp_mux

    @staticmethod
    def should_accept_component2_candidate(rtcp_mux_negotiated: bool) -> bool:
        """
        Should we accept component=2 candidates even if rtcp-mux is negotiated?

        Answer: YES for compatibility. Conversations.im sends them.
        We'll accept them but webrtcbin won't use them.
        """
        return True  # Always accept for compatibility
```

**Usage in converter**:
```python
# In sdp_to_jingle (for offers):
has_rtcp_mux = any(line.strip() == 'a=rtcp-mux' for line in media_lines)
if RtcpMuxHandler.should_add_to_offer_jingle(has_rtcp_mux):
    ET.SubElement(description, '{urn:xmpp:jingle:apps:rtp:1}rtcp-mux')

# In jingle_to_sdp (for offers):
has_rtcp_mux = description.find('{urn:xmpp:jingle:apps:rtp:1}rtcp-mux') is not None
if RtcpMuxHandler.should_add_to_answer_sdp(has_rtcp_mux):
    sdp_lines.append("a=rtcp-mux")
```

**Benefit**: All rtcp-mux logic in one place, documented, testable.

#### Step 2.2: Remove rtcp-mux Comment Voodoo

**Delete**:
```python
# CRITICAL: Do NOT add rtcp-mux to SDP even if Jingle has it  # ← DELETE THIS
# Conversations.im/Monocles expect BOTH component 1 and component 2 candidates  # ← DELETE THIS
# ...
```

**Replace with**: Clear method calls in RtcpMuxHandler with documented behavior.

**Test**: Calls to Conversations.im still work

### Phase 3: Clean Up Trickle ICE Handling

**Goal**: Remove asyncio task workarounds, use explicit state machine.

#### Step 3.1: Create TrickleICEHandler

**File**: `drunk_call_hook/protocol/features/trickle_ice.py`

```python
class TrickleICEState(Enum):
    """States for trickle ICE handling."""
    NORMAL = "normal"                    # Has candidates in offer
    WAITING_FOR_CANDIDATES = "waiting"   # 0 candidates, waiting for transport-info
    CANDIDATES_ARRIVED = "arrived"       # Candidates arrived via transport-info
    TIMEOUT = "timeout"                  # Timeout waiting for candidates

class TrickleICEHandler:
    """
    Handles trickle ICE timing issues.

    Problem: Conversations.im sends offers with 0 candidates in SDP,
    relying entirely on transport-info. If we call setRemoteDescription
    immediately, ICE starts with 0 candidates, then candidates arrive 400ms later.

    Solution: Detect trickle-only offers, defer answer creation until
    first transport-info arrives (or timeout).
    """

    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout = timeout_seconds
        self._pending_offers: Dict[str, dict] = {}  # {session_id: {sdp, state, timer_task}}

    def should_defer_answer(self, sdp: str) -> bool:
        """
        Should we defer answer creation for this offer?

        Returns True if SDP has 0 candidates (trickle-only).
        """
        candidate_count = sdp.count('a=candidate:')
        return candidate_count == 0

    def defer_answer(self, session_id: str, sdp: str, on_timeout: Callable):
        """
        Defer answer creation until candidates arrive.

        Args:
            session_id: Session ID
            sdp: SDP offer (stored for later)
            on_timeout: Callback if timeout expires before candidates arrive
        """
        # Store offer
        self._pending_offers[session_id] = {
            'sdp': sdp,
            'state': TrickleICEState.WAITING_FOR_CANDIDATES
        }

        # Schedule timeout
        async def timeout_handler():
            await asyncio.sleep(self.timeout)
            if session_id in self._pending_offers:
                if self._pending_offers[session_id]['state'] == TrickleICEState.WAITING_FOR_CANDIDATES:
                    self._pending_offers[session_id]['state'] = TrickleICEState.TIMEOUT
                    await on_timeout(session_id)

        task = asyncio.create_task(timeout_handler())
        self._pending_offers[session_id]['timer_task'] = task

    def candidates_arrived(self, session_id: str) -> bool:
        """
        Notify that candidates arrived via transport-info.

        Returns True if we were waiting for them (answer should be created now).
        """
        if session_id not in self._pending_offers:
            return False

        pending = self._pending_offers[session_id]
        if pending['state'] == TrickleICEState.WAITING_FOR_CANDIDATES:
            # Cancel timeout
            if 'timer_task' in pending:
                pending['timer_task'].cancel()

            pending['state'] = TrickleICEState.CANDIDATES_ARRIVED
            return True

        return False

    def get_deferred_offer(self, session_id: str) -> Optional[str]:
        """Get deferred SDP offer and clean up."""
        if session_id not in self._pending_offers:
            return None

        sdp = self._pending_offers[session_id]['sdp']
        del self._pending_offers[session_id]
        return sdp
```

**Usage in JingleAdapter**:
```python
class JingleAdapter:
    def __init__(self, ...):
        self.trickle_ice = TrickleICEHandler(timeout_seconds=5.0)

    async def _handle_session_initiate(self, iq: Iq, jingle, sid: str):
        sdp_offer = self.converter.jingle_to_sdp(jingle, 'offer')

        if self.trickle_ice.should_defer_answer(sdp_offer):
            self.logger.info(f"[TRICKLE-ICE] Deferring answer creation for {sid}")
            self.trickle_ice.defer_answer(sid, sdp_offer, self._on_trickle_timeout)
            # Don't call on_incoming_call yet - wait for candidates
        else:
            # Normal flow
            if self.on_incoming_call:
                await self.on_incoming_call(sid, peer_jid, sdp_offer, media_types)

    async def _handle_transport_info(self, iq: Iq, jingle, sid: str):
        # Parse candidates...

        if self.trickle_ice.candidates_arrived(sid):
            self.logger.info(f"[TRICKLE-ICE] Candidates arrived, creating answer for {sid}")
            sdp_offer = self.trickle_ice.get_deferred_offer(sid)
            # NOW call on_incoming_call to trigger answer creation
            if self.on_incoming_call:
                await self.on_incoming_call(sid, peer_jid, sdp_offer, media_types)

    async def _on_trickle_timeout(self, session_id: str):
        self.logger.warning(f"[TRICKLE-ICE] Timeout for {session_id}, proceeding anyway")
        sdp_offer = self.trickle_ice.get_deferred_offer(session_id)
        if sdp_offer and self.on_incoming_call:
            await self.on_incoming_call(session_id, peer_jid, sdp_offer, media_types)
```

**Benefit**: Clear state machine, no scattered state flags, testable.

#### Step 3.2: Remove Old Trickle ICE Workarounds

**Delete from _handle_session_initiate**:
```python
# Delete lines 255-280 (old workaround)
if candidate_count == 0:
    self.logger.info(f"[TRICKLE-ICE] Offer has 0 candidates...")
    self.sessions[sid]['waiting_for_candidates'] = True
    # ... async timeout task ...
```

**Delete from _handle_transport_info**:
```python
# Delete lines 425-444 (old check)
waiting_for_candidates = session.get('waiting_for_candidates', False)
if waiting_for_candidates and len(candidates) > 0:
    # ...
```

**Test**: Calls with trickle-only offers still work

### Phase 4: Simplify Candidate Queuing

**Goal**: Single queue location, clear rules.

#### Step 4.1: Centralize Candidate Queuing

**Rule**: Queue candidates until session-accept sent/received. After that, send immediately.

**Implementation** (in JingleAdapter):
```python
def _should_queue_candidate(self, session_id: str) -> bool:
    """
    Should we queue this ICE candidate instead of sending?

    Queue if session-initiate/session-accept not yet exchanged.
    """
    if session_id not in self.sessions:
        return True

    state = self.sessions[session_id].get('state', 'new')

    # Queue states: before session stanzas exchanged
    return state in ('proposing', 'proceeding', 'pending', 'incoming', 'accepted')

async def _on_bridge_ice_candidate(self, session_id: str, candidate: Dict[str, Any]):
    """Handle ICE candidate from CallBridge (Go service)."""
    if self._should_queue_candidate(session_id):
        if session_id not in self.pending_ice_candidates:
            self.pending_ice_candidates[session_id] = []
        self.pending_ice_candidates[session_id].append(candidate)
        self.logger.debug(f"Queued ICE candidate for {session_id}")
    else:
        # Active state - send immediately
        await self.send_ice_candidate(session_id, candidate)

def _flush_pending_candidates(self, session_id: str):
    """Flush queued candidates after session stanzas exchanged."""
    if session_id in self.pending_ice_candidates:
        pending = self.pending_ice_candidates[session_id]
        self.logger.info(f"Flushing {len(pending)} queued ICE candidates for {session_id}")
        for cand in pending:
            asyncio.create_task(self.send_ice_candidate(session_id, cand))
        del self.pending_ice_candidates[session_id]
```

**Call flush at the right times**:
```python
# After sending session-accept (incoming call):
async def send_answer(self, session_id: str, sdp: str):
    # ... send session-accept stanza ...
    self.sessions[session_id]['state'] = 'active'
    self._flush_pending_candidates(session_id)

# After receiving session-accept (outgoing call):
async def _handle_session_accept(self, iq: Iq, jingle, sid: str):
    # ... process session-accept ...
    self.sessions[sid]['state'] = 'active'
    self._flush_pending_candidates(sid)
```

**Delete**: All other candidate queuing logic (lines 765-773, etc.)

**Test**: ICE candidates arrive in correct order

### Phase 5: Clean Up SSRC Handling

**Goal**: Extract SSRC parsing/filtering to SSRCHandler.

#### Step 5.1: Create SSRCHandler

**File**: `drunk_call_hook/protocol/features/ssrc.py`

```python
class SSRCHandler:
    """
    Handles SSRC (XEP-0294) parameter filtering.

    Rule: Only echo SSRC parameters that were in the offer.
    Example: Conversations sends {cname, msid}, Pion generates {cname, msid, mslabel, label}.
    We filter to {cname, msid} to match offer.
    """

    @staticmethod
    def parse_ssrc_from_sdp(sdp_lines: List[str]) -> Dict[str, Dict[str, str]]:
        """
        Parse SSRC info from SDP.

        Returns: {ssrc_id: {param_name: param_value}}
        """
        ssrc_info = {}
        for line in sdp_lines:
            if line.startswith('a=ssrc:'):
                # Format: a=ssrc:2485877649 cname:pion-audio
                parts = line.split(':', 1)
                if len(parts) >= 2:
                    rest = parts[1].strip()
                    ssrc_parts = rest.split(' ', 1)
                    if len(ssrc_parts) >= 2:
                        ssrc = ssrc_parts[0]
                        if ':' in ssrc_parts[1]:
                            attr_name, attr_value = ssrc_parts[1].split(':', 1)
                            if ssrc not in ssrc_info:
                                ssrc_info[ssrc] = {}
                            ssrc_info[ssrc][attr_name] = attr_value
        return ssrc_info

    @staticmethod
    def filter_ssrc_params(ssrc_info: Dict[str, Dict[str, str]],
                          allowed_params: List[str]) -> Dict[str, Dict[str, str]]:
        """
        Filter SSRC params to only allowed ones.

        Args:
            ssrc_info: Full SSRC info from SDP
            allowed_params: Param names that were in offer (e.g., ['cname', 'msid'])

        Returns:
            Filtered SSRC info
        """
        if not allowed_params:
            return ssrc_info  # No filtering

        filtered = {}
        for ssrc, params in ssrc_info.items():
            filtered[ssrc] = {
                name: value
                for name, value in params.items()
                if name in allowed_params
            }
        return filtered

    @staticmethod
    def build_jingle_ssrc_elements(ssrc_info: Dict[str, Dict[str, str]]) -> List[ET.Element]:
        """Build Jingle <source> elements from SSRC info."""
        elements = []
        for ssrc, params in ssrc_info.items():
            source_el = ET.Element('{urn:xmpp:jingle:apps:rtp:ssma:0}source')
            source_el.set('ssrc', ssrc)
            for param_name, param_value in params.items():
                param_el = ET.SubElement(source_el, '{urn:xmpp:jingle:apps:rtp:ssma:0}parameter')
                param_el.set('name', param_name)
                param_el.set('value', param_value)
            elements.append(source_el)
        return elements
```

**Usage in converter**:
```python
# In sdp_to_jingle:
if should_add_ssrc:
    ssrc_info = SSRCHandler.parse_ssrc_from_sdp(media_lines)
    allowed_params = offer_context.get('ssrc_params', [])
    filtered_ssrc = SSRCHandler.filter_ssrc_params(ssrc_info, allowed_params)
    ssrc_elements = SSRCHandler.build_jingle_ssrc_elements(filtered_ssrc)
    for elem in ssrc_elements:
        description.append(elem)
```

**Delete**: Lines 1442-1495 (old manual parsing)

**Test**: SSRC params correctly filtered

---

## Testing Strategy

### Unit Tests (New)

**File**: `tests/test_jingle_sdp_converter.py`

```python
def test_sdp_to_jingle_basic():
    """Test basic SDP → Jingle conversion."""
    converter = JingleSDPConverter()
    sdp = """v=0
o=- 0 0 IN IP4 0.0.0.0
s=-
t=0 0
m=audio 9 UDP/TLS/RTP/SAVPF 111
c=IN IP4 0.0.0.0
a=rtpmap:111 opus/48000/2
a=mid:0
a=ice-ufrag:xyz
a=ice-pwd:abc
a=fingerprint:sha-256 AA:BB:CC
a=rtcp-mux
"""
    jingle = converter.sdp_to_jingle(sdp, 'offer')

    # Verify structure
    contents = jingle.findall('{urn:xmpp:jingle:1}content')
    assert len(contents) == 1

    description = contents[0].find('{urn:xmpp:jingle:apps:rtp:1}description')
    assert description is not None
    assert description.get('media') == 'audio'

    # Verify rtcp-mux
    rtcp_mux = description.find('{urn:xmpp:jingle:apps:rtp:1}rtcp-mux')
    assert rtcp_mux is not None

def test_jingle_to_sdp_round_trip():
    """Test Jingle → SDP → Jingle round-trip."""
    converter = JingleSDPConverter()

    # Create Jingle offer
    jingle_offer = create_test_jingle_offer()  # Helper function

    # Convert to SDP
    sdp_offer = converter.jingle_to_sdp(jingle_offer, 'offer')

    # Convert back to Jingle
    jingle_offer2 = converter.sdp_to_jingle(sdp_offer, 'offer')

    # Verify equivalence (ignoring minor formatting differences)
    assert_jingle_equivalent(jingle_offer, jingle_offer2)

def test_rtcp_mux_negotiation():
    """Test rtcp-mux negotiation through converter."""
    converter = JingleSDPConverter()

    # Offer with rtcp-mux
    sdp_offer_with_mux = create_sdp_with_rtcp_mux()
    jingle_offer = converter.sdp_to_jingle(sdp_offer_with_mux, 'offer')

    # Verify <rtcp-mux/> element
    description = jingle_offer.find('.//{urn:xmpp:jingle:apps:rtp:1}description')
    rtcp_mux = description.find('{urn:xmpp:jingle:apps:rtp:1}rtcp-mux')
    assert rtcp_mux is not None

    # Extract offer context
    offer_context = converter.extract_offer_context(jingle_offer)

    # Create answer
    sdp_answer_with_mux = create_sdp_answer_with_rtcp_mux()
    jingle_answer = converter.sdp_to_jingle(sdp_answer_with_mux, 'answer',
                                            offer_context=offer_context)

    # Verify answer also has <rtcp-mux/>
    description = jingle_answer.find('.//{urn:xmpp:jingle:apps:rtp:1}description')
    rtcp_mux = description.find('{urn:xmpp:jingle:apps:rtp:1}rtcp-mux')
    assert rtcp_mux is not None

def test_trickle_ice_detection():
    """Test trickle ICE handler detects 0-candidate offers."""
    handler = TrickleICEHandler()

    # Offer with 0 candidates
    sdp_no_cands = "v=0\nm=audio 9 UDP/TLS/RTP/SAVPF 111\n..."
    assert handler.should_defer_answer(sdp_no_cands) == True

    # Offer with candidates
    sdp_with_cands = sdp_no_cands + "a=candidate:1 1 UDP 123 192.168.1.1 54321 typ host\n"
    assert handler.should_defer_answer(sdp_with_cands) == False
```

### Integration Tests (Existing, Updated)

**File**: `tests/test-drunk-xmpp.py`

Update to use new converter:
```python
def test_jingle_offer_answer_flow():
    """Test full Jingle offer/answer flow with new converter."""
    # Create JingleAdapter with converter
    adapter = JingleAdapter(xmpp, bridge, logger=logger)

    # Send offer
    session_id = await adapter.send_offer(peer_jid, sdp_offer, ['audio'])

    # Receive session-accept
    # ... (existing test code) ...

    # Verify SDP conversion worked
    assert session created successfully
    assert audio bidirectional
```

### Regression Tests

Run existing call tests with Conversations.im and Dino to ensure no regressions.

---

## Migration Path

### Phase 1: Extract (Week 1)
- Create JingleSDPConverter class
- Move conversion methods
- Update JingleAdapter to use converter
- **No behavior change**
- All tests pass

### Phase 2: Clean rtcp-mux (Week 1)
- Create RtcpMuxHandler
- Update converter to use handler
- Remove comment voodoo
- Test with Conversations.im

### Phase 3: Clean Trickle ICE (Week 2)
- Create TrickleICEHandler
- Update adapter to use handler
- Remove asyncio task workarounds
- Test with trickle-only offers

### Phase 4: Simplify Queuing (Week 2)
- Centralize candidate queuing logic
- Remove duplicated queue code
- Test ICE candidate timing

### Phase 5: Clean SSRC (Week 2)
- Create SSRCHandler
- Update converter
- Remove manual parsing
- Test SSRC filtering

### Phase 6: Proto Updates (Week 3)
- Update call.proto (see PROTO-IMPROVEMENTS.md)
- Implement new C++ service
- Update Python to use new proto
- Full integration testing

---

## Success Criteria

- ✅ JingleSDPConverter has <200 lines per method (currently 257)
- ✅ All conversion logic in converter, not scattered
- ✅ RtcpMuxHandler eliminates comment voodoo
- ✅ TrickleICEHandler has clear state machine (no asyncio tasks in handlers)
- ✅ Candidate queuing in one place (not 4)
- ✅ SSRC handling extracted to SSRCHandler
- ✅ 100% test coverage for converter
- ✅ All integration tests pass (Conversations.im + Dino)
- ✅ No ADR violations (manual XML parsing abstracted)
- ✅ Code maintainable by someone who didn't write it

---

## Trickle-ICE SDP Storage Fix (2026-03-10)

### Problem

SP→SP calls failed with "No stored SDP offer" error when both sides used trickle-ICE (0 candidates in session-initiate).

**Root Cause**: When `should_defer_answer()` detected trickle-only offer, `on_incoming_call()` callback was skipped (jingle.py:280), preventing SDP from being stored in `pending_call_offers`. When user accepted via XEP-0353, `accept_call()` ran before SDP arrived. When SDP finally arrived (after candidates), the code thought user "already accepted" and didn't create the C++ session.

**Why it worked with Conversations.im**: Conversations.im sends candidates IN session-initiate (non-trickle), so `on_incoming_call()` was called immediately and SDP stored before user interaction.

### Solution

**File**: `drunk_call_hook/protocol/jingle.py:271-284`

**Change**: Always call `on_incoming_call()` to store SDP **before** setting up trickle-ICE deferral:

```python
# Always call on_incoming_call to store SDP (required for accept_call to work)
# This matches the working Conversations.im flow where SDP is stored immediately
if self.on_incoming_call:
    await self.on_incoming_call(sid, peer_jid, sdp_offer, media_types)

# Check if this is a trickle-only offer (0 candidates)
if self.trickle_ice.should_defer_answer(sdp_offer):
    # Defer answer creation until candidates arrive via transport-info
    async def on_timeout(session_id: str):
        if self.on_candidates_ready:
            await self.on_candidates_ready(session_id)

    self.trickle_ice.defer_answer(sid, sdp_offer, peer_jid, media_types, on_timeout)
```

**Result**:
- ✅ SP→SP calls now work (session de084ce6-7afa-4d8a-b372-5ecf06a1039c verified)
- ✅ No regression with Conversations.im/Dino
- ✅ SDP always available when user accepts call

**Minor harmless side effect**: Trickle-ICE timeout still fires 5s after successful calls, but safely returns without action.

---

**Next Steps**:
1. Review plan with user
2. Get approval to start Phase 1
3. Create feature branch: `jingle-refactor`
4. Implement + test incrementally

---

**Last Updated**: 2026-03-10
**Status**: Ready for review (Trickle-ICE fix applied)
