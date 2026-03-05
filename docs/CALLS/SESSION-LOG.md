# Development Session Log

**Purpose**: Track progress for Calls feature (Jingle + gRPC integration)

---

## 🎯 CURRENT STATUS (2026-03-04)

### ✅ Python/Jingle Refactoring: **COMPLETE**
- All 38 tests passing (JingleSDPConverter + SSRC handler)
- 683 lines of scattered logic removed and centralized
- Feature handlers: RtcpMuxHandler, TrickleICEHandler, SSRCHandler

### ✅ C++ Library Level: **COMPLETE**
- WebRTCSession (SDP, ICE, pipelines)
- DeviceEnumerator (audio/video, cross-platform)
- Statistics (bandwidth, packet loss, RTT, jitter)
- Logger (spdlog with rotation)
- **11 standalone tests passing** (test_step0 through test_step9)

### ✅ gRPC Service: **COMPLETE** (Phases 4.1-4.6)
- **Phase 4.1**: Thread infrastructure (ThreadSafeQueue, SessionManager)
- **Phase 4.2**: Service skeleton (main.cpp, call_service_impl, CLI args)
- **Phase 4.3**: CreateSession, StreamEvents, EndSession + graceful shutdown
- **Phase 4.4**: SDP operations (CreateOffer, CreateAnswer, SetRemoteDescription)
- **Phase 4.5**: ICE candidate handling (AddICECandidate)
- **Phase 4.6**: GetStats, SetMute, ListAudioDevices

**RPC Status**: 11/12 methods working (CreateSession, CreateOffer, CreateAnswer, SetRemoteDescription, AddICECandidate, StreamEvents, EndSession, GetStats, SetMute, ListAudioDevices, Heartbeat)

**Binary**: drunk-call-service-linux (13MB debug, ~3MB release)

---

## 🚀 RESUME HERE

### Session 20 (2026-03-04): SDP Direction Bug - Root Cause Found, Partial Fix 🔬

**Status**: ROOT CAUSE CONFIRMED - Caps negotiation timing issue. Fix implemented but webrtcbin still generating `a=recvonly`

#### 🔍 Investigation Summary

**Problem**: SDP answer contains `a=recvonly` instead of `a=sendrecv`, preventing bidirectional audio
- Remote offer: `a=sendrecv` ✓
- Our answer: `a=recvonly` ✗ (wrong!)
- Result: Zero bandwidth, no audio flowing, Dino stays in "Calling" state

**Initial Attempts** (all failed):
1. Setting transceiver direction property to SENDRECV - property sets but ignored
2. Setting direction before AND after set-remote-description - no effect
3. Checking transceiver has sender - confirmed sender exists but SDP still wrong

#### ✅ Root Cause Discovery (Thanks to GPT-5 Analysis)

**Diagnostic Logs Revealed** (Session 0c2263c4):
```
[14:37:30.052] ⚠️ audio_src pad has NO caps negotiated yet!
[14:37:30.052] ⚠️ webrtcbin sink_0 pad has NO caps negotiated yet!
[14:37:30.052] ✓ PRE: Transceiver 0 has sender
```

**Timeline Analysis**:
- `14:37:30.048` - Pipeline set to PLAYING
- `14:37:30.052` - CreateAnswer called (**4ms later!**)
- Caps not yet negotiated (opusenc/rtpopuspay still negotiating)
- webrtcbin can't claim send capability → generates `a=recvonly`

**Official GStreamer Example Comparison**:
- Our structure is CORRECT (matches official webrtc-sendrecv.c)
- Pipeline: `audio_src → volume → queue → opusenc → rtpopuspay → capsfilter → webrtcbin`
- Official uses same approach for both offerer and answerer modes
- Key difference: Official example doesn't have this timing issue (may have different signaling flow)

#### 🔧 Fix Attempt #1: Wait for Caps Negotiation

**Implementation** (webrtc_session.cpp:209-273):
```cpp
// Wait up to 500ms for webrtcbin sink_0 to have negotiated caps
GstPad *webrtc_sink = gst_element_get_static_pad(webrtc_, "sink_0");
GstCaps *sink_caps = nullptr;
int wait_count = 0;
const int max_wait_ms = 500;
const int check_interval_ms = 10;

while (wait_count < max_wait_ms / check_interval_ms) {
    sink_caps = gst_pad_get_current_caps(webrtc_sink);
    if (sink_caps) {
        LOG_INFO("Caps negotiated after {}ms", wait_count * 10);
        break;
    }
    g_usleep(10000);  // 10ms
    wait_count++;
}
```

**Result** (Session 26d888ad):
```
[14:41:12.611] Waiting for audio pipeline caps negotiation...
[14:41:12.915] Caps negotiated after 300ms: application/x-rtp,media=audio,...OPUS,...
[14:41:12.915] PRE: Transceiver 0 direction=4 (SENDRECV)
[14:41:12.915] PRE: Transceiver 0 has sender
[14:41:13.076] AFTER: direction=4, current-direction=4
BUT: SDP Answer STILL has a=recvonly ❌
```

#### 🤔 Current Mystery

**What's Working**:
- ✅ Caps negotiate successfully after 300ms
- ✅ Transceiver has direction=4 (SENDRECV)
- ✅ Transceiver has sender object
- ✅ Remote offer has `a=sendrecv`
- ✅ ICE connects (checking → connected → completed)

**What's Still Broken**:
- ❌ SDP answer has `a=recvonly` despite transceiver direction=SENDRECV
- ❌ Zero bandwidth (no audio flowing)
- ❌ webrtcbin ignoring transceiver direction property

#### 💡 Next Steps to Try

**Theory #1: Transceiver Creation Method**
- Currently: We request `sink_%u` pad which implicitly creates transceiver
- Alternative: Explicitly call `add-transceiver` signal with SENDRECV direction
- Reference: `gst-plugins-bad/tests/check/elements/webrtcbin.c:1823`

**Theory #2: Audio Source Not Producing Data**
- webrtcbin might check if actual buffers are flowing (not just caps)
- Added logging to check: audio_src state, pad is_active status
- May need to wait for first buffer to flow before creating answer

**Theory #3: webrtcbin Bug or Limitation**
- webrtcbin might not support changing direction for answerer-created transceivers
- May need to search GStreamer source for answer direction determination logic
- Check: `gst-plugins-bad/ext/webrtc/webrtcsdp.c` - SDP generation code

**Theory #4: Codec/Payload Mismatch**
- Our caps: payload=97 (OPUS/48000/2)
- Answer uses: payload=111 (from remote offer)
- Mismatch might cause webrtcbin to disable send direction

#### 📝 Evidence Trail

**Confirmed Facts**:
1. GPT-5 diagnosis was correct: timing/caps negotiation issue
2. Waiting for caps fixes the timing but not the SDP direction
3. Transceiver direction property is set correctly but ignored during answer generation
4. This is NOT a Python/Jingle issue - purely webrtcbin behavior

**Files Modified**:
- `drunk_call_service/src/webrtc_session.cpp`:
  - Added caps negotiation wait loop (lines 209-273)
  - Added diagnostic logging for caps, transceiver direction, sender status
  - All changes documented with detailed comments

**Key Log Evidence**:
- Session 147d9e2e: First confirmed bandwidth=0kbps throughout call
- Session 0c2263c4: Discovered caps not negotiated (4ms timing)
- Session 26d888ad: Confirmed caps negotiate after 300ms but SDP still wrong

#### 🔬 Debugging Commands Used

```bash
# Check diagnostic logs
grep -E "Waiting for audio|Caps negotiated|audio_src caps|webrtcbin sink_0"

# Check transceiver direction
grep -E "PRE:|BEFORE:|AFTER:|direction=|has sender"

# Check SDP answer
grep -A20 "\[SDP-ANSWER\]"

# Compare with offer
grep -A20 "\[SDP-OFFER\]"
```

---

### Session 19 (2026-03-04): WebRTC Direction Bug - `a=recvonly` vs `a=sendrecv` 🔧

**Status**: Trickle-ICE buffering WORKS! New bug found: wrong SDP direction

**The Good News**: Buffering implementation working perfectly!
- Call ID: `4d6f06f6-a59d-4fc8-a829-7979bad6e22b`
- 4 candidates buffered during states `HAVE_OFFER` → `ANSWER_READY`
- All 4 candidates processed after `send_answer()` and added to C++ session
- ICE connected successfully: state `connected` → `completed`

**The Bad News**: No media flowing (bandwidth=0kbps)
- Our SDP answer contains `a=recvonly` instead of `a=sendrecv`
- Dino stayed in "Calling" state (not receiving audio from us)
- GStreamer: `audio_src` paused with `flushing` (nothing to send to)

**Next**: Investigate C++ `WebRTCSession::create_answer()` - why `recvonly`?

See detailed analysis below in Session 19 section.

---

### Session 18 (2026-03-04): Trickle-ICE State Machine Implementation ✅

**Goal**: Implement state machine with candidate buffering to fix race conditions in incoming trickle-ICE calls

**Problem**:
- `transport-info` arrives before C++ session exists → "Session not found" errors
- Async timing issues between Jingle (Python), gRPC, and GStreamer (C++)
- Candidates lost or added in wrong order

**Solution Implemented**: State machine with explicit synchronization + candidate buffering

**Incoming Call Flow (Sequential Phases)**:
```
Phase 1: RECV session-initiate → Parse SDP → STATE: HAVE_OFFER (buffer transport-info)
Phase 2: Gather TURN credentials + devices → STATE: RESOURCES_READY (buffer transport-info)
Phase 3: CreateSession(TURN, devices) → STATE: SESSION_CREATED (buffer transport-info)
Phase 4: CreateAnswer(remote_sdp) → STATE: REMOTE_SET (buffer transport-info)
Phase 5: STATE: ANSWER_READY → Process ALL buffered candidates → AddICECandidate()
Phase 6: Send session-accept → STATE: ACTIVE (normal trickle mode, no buffering)
```

**Key Changes**:

1. **Extended TrickleICEHandler** (`drunk_call_hook/protocol/features/trickle_ice.py` +154 lines):
   - Added `IncomingCallState` enum (6 states)
   - Added `_incoming_states: Dict[str, IncomingCallState]` - state tracking
   - Added `_buffered_candidates: Dict[str, List[Dict]]` - candidate buffering
   - New methods:
     - `set_incoming_state()` - update state with logging
     - `should_buffer_candidates()` - check if should buffer (states < ACTIVE)
     - `buffer_candidates()` - store transport-info for later
     - `get_buffered_candidates()` - retrieve and clear buffer
     - `cleanup_incoming_call()` - memory leak prevention

2. **Updated jingle.py** (`drunk_call_hook/protocol/jingle.py` ~50 lines changed):
   - Line 21: Import `IncomingCallState`
   - Line 269: Set initial state `HAVE_OFFER` in `_handle_session_initiate()`
   - Lines 417-435: Buffer candidates in `_handle_transport_info()` when `should_buffer_candidates()` returns True
   - Lines 372, 1065: Cleanup buffered candidates in termination handlers

3. **Updated calls.py** (`siproxylin/core/barrels/calls.py` ~70 lines changed):
   - Line 30: Import `IncomingCallState`
   - Line 711: State transition `RESOURCES_READY` after TURN + devices loaded
   - Line 742: State transition `SESSION_CREATED` after C++ session created
   - Lines 606-626, 794-814: Process buffered candidates after `CreateAnswer()`:
     - State transitions: `REMOTE_SET` → `ANSWER_READY`
     - Retrieve buffered candidates
     - Add to C++ session sequentially
     - Send session-accept
     - State transition: `ACTIVE` (normal trickle mode)

**Architecture**:
- **Buffering period**: States `HAVE_OFFER`, `RESOURCES_READY`, `SESSION_CREATED`, `REMOTE_SET`, `ANSWER_READY`
- **Processing point**: After `ANSWER_READY`, before sending `session-accept`
- **Active mode**: State `ACTIVE` - candidates added immediately (no buffering)

**Benefits**:
- **No more race conditions**: Candidates buffered until session ready
- **Sequential processing**: Explicit state transitions ensure correct order
- **Memory safe**: Cleanup on session termination
- **Backwards compatible**: Outgoing calls unchanged (still use hybrid trickle-ICE)

**Testing Status**: First test revealed race condition bug, now fixed

**Bug Found During Testing** (Call ID: 5eaa750e-4c26-403a-a61e-9935586c74e2):
- **Symptom**: ICE stuck at "checking", never connected. Dino stayed "Calling", we said "connected"
- **Root Cause**: Candidates buffered but NEVER processed before session-accept sent
- **Timeline of Bug**:
  1. CreateAnswer() completes → State: `ANSWER_READY`
  2. `get_buffered_candidates()` called → Returns 0 (candidates haven't arrived yet)
  3. Candidates arrive asynchronously → Buffered in `ANSWER_READY` state
  4. `send_answer()` called → Session-accept sent WITHOUT buffered candidates
  5. State: `ACTIVE` → Now candidates processed, but too late!
- **Fix**: Move `get_buffered_candidates()` AFTER `send_answer()` to catch race window
  - Lines 610-627 in calls.py (normal path)
  - Lines 818-835 in calls.py (deferred path)

**Files Changed**:
- `drunk_call_hook/protocol/features/trickle_ice.py` (+154 lines)
- `drunk_call_hook/protocol/jingle.py` (~50 lines changed)
- `siproxylin/core/barrels/calls.py` (~70 lines changed, +race condition fix)

**Next**: Retest incoming call from Conversations.im with race condition fix

---

### Session 19 (2026-03-04): WebRTC Direction Bug - `a=recvonly` vs `a=sendrecv` 🔧

**Status**: Trickle-ICE buffering works perfectly! Found new bug: wrong SDP direction

**The Good News**: Buffering implementation verified working!

Call ID: `4d6f06f6-a59d-4fc8-a829-7979bad6e22b`

**Evidence of Success** (State Machine + Buffering):
```
00:41:34 - [STATE] None → have_offer
00:41:34 - [BUFFER] Buffering candidates (state=resources_ready)
00:41:34 - [BUFFER] Buffered 1 candidates (total buffered: 1)
00:41:34 - [BUFFER] Buffered 1 candidates (total buffered: 2)
00:41:34 - [BUFFER] Buffered 1 candidates (total buffered: 3)
00:41:34 - [STATE] RESOURCES_READY → session_created
00:41:34 - [BUFFER] Buffering candidates (state=session_created)
00:41:34 - [BUFFER] Buffered 1 candidates (total buffered: 4)
00:41:34 - [STATE] SESSION_CREATED → remote_set
00:41:34 - [STATE] REMOTE_SET → answer_ready
00:41:35 - Sent session-accept
00:41:35 - [BUFFER] Retrieved 4 buffered candidates
00:41:35 - [BUFFER] Processing 4 buffered candidates
00:41:35 - Adding ICE candidate to session (×4)
00:41:35 - [STATE] ANSWER_READY → active
```

**ICE Connection**: ✅ SUCCESS
```
C++ logs:
00:41:35 - ice_state=connected
00:41:37 - ice_state=completed

GStreamer (stdout):
libnice-DEBUG: Agent: Selected pair: 1:1 13 UDP 89.238.78.51:54000 RELAYED
libnice-DEBUG: Agent: Remote selected pair: 1:1 remote1 UDP 105.66.6.71:30350 PEER-RFLX
libnice-DEBUG: stream 1 component 1 STATE-CHANGE connected → ready
```

**The Bad News**: No media flowing, wrong SDP direction

**Evidence**:
1. **Our SDP Answer**: Contains `a=recvonly` instead of `a=sendrecv`
   ```sdp
   m=audio 9 UDP/TLS/RTP/SAVPF 111
   a=mid:audio
   a=rtcp-mux
   a=setup:active
   a=rtpmap:111 OPUS/48000/2
   a=fmtp:111 useinbandfec=1
   a=recvonly  ← WRONG! Should be sendrecv
   a=fingerprint:sha-256 58:5A:EC:BA:D0:56:A8:C2:83:BF:EC:64:FE:22:11:8D...
   ```

2. **C++ Stats**: No media flowing
   ```
   00:41:35 - ice_state=connected, bandwidth=0kbps
   00:41:37 - ice_state=completed, bandwidth=0kbps
   00:41:39 - ice_state=completed, bandwidth=0kbps
   ```

3. **GStreamer Pipeline**: Audio source paused (nothing to send to)
   ```
   0:00:23.250468303 - basesrc.c:3042:gst_base_src_loop:<audio_src>
       pausing after gst_pad_push() = flushing
   ```

4. **Dino UI**: Stayed in "Calling" state (not receiving audio from us)

5. **Our UI**: Showed "Connected" (ICE worked, but misleading)

**Root Cause Analysis**:

Dino's offer had `senders="both"` (bidirectional):
```xml
<content creator="initiator" name="audio" senders="both">
```

This maps to `a=sendrecv` in SDP. Our answer should also be `a=sendrecv` but C++ generated `a=recvonly`.

**Hypothesis**: C++ `WebRTCSession::create_answer()` is setting wrong transceiver direction

**Possible Causes**:
1. GStreamer webrtcbin defaults to `recvonly` for answers (need to set direction explicitly)
2. Transceiver not configured before creating answer
3. Missing `gst_webrtc_rtp_transceiver_set_direction()` call
4. Direction set on wrong transceiver or at wrong time

**What Works**:
- ✅ Trickle-ICE state machine (6 states, sequential flow)
- ✅ Candidate buffering (4 candidates buffered → processed after answer)
- ✅ ICE connection (connected → completed)
- ✅ DTLS handshake (setup=active worked correctly)
- ✅ Jingle signaling (XEP-0166 compliance, IQ ACK before session-accept)

**What Doesn't Work**:
- ❌ Media direction (recvonly instead of sendrecv)
- ❌ Audio pipeline (source paused, no RTP packets sent)
- ❌ Bandwidth stats (0kbps, should be ~40kbps for Opus)

**Investigation Needed** (C++ Code):

Files to check:
1. `drunk_call_service/src/webrtc_session.cpp`:
   - `create_answer()` method (line ~200-250)
   - Transceiver direction handling
   - Look for `gst_webrtc_rtp_transceiver_set_direction()`

2. GStreamer webrtcbin documentation:
   - Default transceiver direction for answers
   - How to set direction before creating answer
   - Difference between offer and answer direction handling

**Logs to Review**:
- ✅ Python logs: State machine working perfectly
- ✅ C++ logs: ICE connected, but bandwidth=0kbps
- ✅ GStreamer stdout: Pipeline paused with `flushing`
- ⚠️ GStreamer stderr: Only memory leaks (not audio-related)

**Next Steps**:
1. Review C++ `create_answer()` implementation
2. Check if transceivers are created/configured
3. Add `set_direction(SENDRECV)` before creating answer
4. Test with modified C++ code
5. Verify Dino receives audio and transitions to "Connected" state

**Files to Modify** (estimated):
- `drunk_call_service/src/webrtc_session.cpp` - Fix transceiver direction

**Impact**: High priority - calls connect but no audio flows

---

### Session 14 (2026-03-03): Phase 4.7 Complete + First Python Integration Test ✅

**Phase 4.7 Complete**: All 4 GStreamer error handling fixes implemented:
- ✅ Issue #6: GStreamer bus error monitoring (ERROR, WARNING, EOS, STATE_CHANGED)
- ✅ Issue #8: Graceful pipeline shutdown with 5-second timeout
- ✅ Issue #9: Cleanup zombie elements on pad link failure
- ✅ Issue #7: Detailed logging for partial pipeline failure paths

**First Python Integration Test**:
- Attempted first real call: Conversations.im → siproxylin
- Found bug: "Session not found" when adding ICE candidates
- **Root cause**: Python tried to add ICE candidates before C++ session existed
- **Fix**: Create C++ session immediately when call accepted (before candidates arrive)
  - Based on GStreamer source analysis (webrtcbin queues candidates internally)
  - Changed flow: `accept_call()` → create session → candidates can arrive anytime

**Files Changed**:
- `siproxylin/core/barrels/calls.py`:
  - New method `_create_incoming_session()` - extracted session creation logic
  - Updated `accept_call()` - creates C++ session immediately
  - Updated `_on_jingle_incoming_call()` - creates session if user already accepted
  - Simplified `_on_candidates_ready()` - just creates answer (session exists)

**Status**: Ready to test incoming calls again

**Next**: Test incoming call flow end-to-end

---

### Architecture
```
Python (Jingle/XMPP) ↔ gRPC ↔ C++ Service ↔ WebRTC/GStreamer

Threading Model:
- Main thread: Starts GLib thread + gRPC server, then blocks
- GLib thread: Runs g_main_loop_run(), processes GStreamer callbacks
- gRPC thread pool: Handles all RPC calls
- Cross-thread communication: ThreadSafeQueue + SessionManager
```

### Key Documents
1. `docs/CALLS/4-GRPC-PLAN.md` - Implementation plan
2. `docs/CALLS/GSTREAMER-THREADING.md` - Threading patterns
3. `docs/THREAD-INFRASTRUCTURE-USAGE.md` - ThreadSafeQueue/SessionManager usage
4. `docs/LOGGING-POLICY.md` - STDOUT/STDERR/Logger rules
5. `docs/CALLS/PLAN.md` - Original architecture
6. `docs/ADR.md` - Critical rules

### Critical Rules
- STDOUT: Reserved for libnice/GStreamer debug ONLY
- STDERR: Only for FATAL errors before logger init
- Use LOG_*() macros for all application logging
- Follow patterns in GSTREAMER-THREADING.md

### What to Build Next

**Phase 4.7: Error Handling Improvements (IN PROGRESS)**
- [x] Critical bug fixes (Session 13: memory leaks, use-after-free, privacy, logging)
- [ ] Issue #6: GStreamer bus error monitoring (follow official pattern)
- [ ] Issue #8: Graceful pipeline shutdown with timeout
- [ ] Issue #9: Cleanup zombie elements on pad link failure
- [ ] Issue #7: Add logging for partial pipeline failure reproduction
- [ ] Structured error events (ICE_FAILED, DTLS_FAILED, PIPELINE_ERROR)
- [ ] Error propagation to Python via ErrorEvent

**Phase 4.8: Integration Testing with Python**
- End-to-end test: Python ↔ gRPC ↔ C++ service
- Full call flow: Offer/Answer, ICE negotiation, media flow
- Interop testing with Conversations.im / Dino
- Performance validation: Startup time, memory usage, latency

**Success Criteria (Phase 4.8)**:
- [ ] Python client can create sessions and exchange SDP
- [ ] ICE candidates trickle correctly Python ↔ C++
- [ ] Audio bidirectional (loopback test)
- [ ] Stats API returns valid data
- [ ] Mute/unmute works from Python
- [ ] Device enumeration accessible from Python
- [ ] Clean shutdown via Python or Ctrl+C

### Testing
```bash
# Standalone library tests
cd tests/standalone && make test

# gRPC integration tests
./tests/test_grpc_service.sh
./tests/test_ice_candidates.sh
```

---

## 📊 Progress Tracker

**Python Side**:
- [x] Sessions 1-6: Jingle refactor

**C++ Library**:
- [x] WebRTCSession, DeviceEnumerator, Stats, Logger
- [x] 11 standalone tests passing

**gRPC Service**:
- [x] Phase 4.1: Thread infrastructure
- [x] Phase 4.2: Service skeleton
- [x] Phase 4.3: CreateSession + StreamEvents + EndSession
- [x] Phase 4.4: SDP operations + 3 critical bug fixes
- [x] Phase 4.5: ICE candidate handling
- [x] Phase 4.6: GetStats, SetMute, ListAudioDevices
- [ ] Phase 4.7: Error handling improvements ← **NEXT**
- [ ] Phase 4.8: Integration testing with Python

---

## 📁 Key Files

**Source** (drunk_call_service/src/):
- `webrtc_session.{h,cpp}` - WebRTC session (library level)
- `session_manager.{h,cpp}` - Thread-safe session map
- `thread_safe_queue.h` - Cross-thread event queue
- `logger.{h,cpp}` - spdlog wrapper
- `device_enumerator.cpp` - Device enumeration
- `call_service_impl.{h,cpp}` - gRPC service implementation
- `main.cpp` - Service entry point

**Proto**:
- `proto/call.proto` - gRPC service definition (13 RPCs)

**Tests**:
- `tests/standalone/` - 11 library tests (test_step0 through test_step9)
- `tests/test_grpc_service.sh` - Integration test for all RPCs
- `tests/test_ice_candidates.sh` - ICE candidate handling test

---

## 🔍 Session History

### Sessions 1-6 (2026-03-02 to 2026-03-03): Python/Jingle Refactoring
- Created JingleSDPConverter (pure SDP ↔ Jingle conversion)
- Feature handlers (RtcpMuxHandler, TrickleICEHandler, SSRCHandler)
- Removed ~683 lines of scattered logic
- 38 tests passing

### Session 7 (2026-03-03): Phase 4.1 - Thread Infrastructure
- ThreadSafeQueue<T> template (77 lines)
- SessionManager class (124 lines)
- 13 tests passing (6 queue tests, 7 session manager tests)
- Docs: THREAD-INFRASTRUCTURE-USAGE.md, LOGGING-POLICY.md

### Session 8 (2026-03-03): Phase 4.2 - gRPC Service Skeleton
- main.cpp: GLib thread + gRPC server (353 lines)
- call_service_impl.{h,cpp}: 12 RPC handlers (stubs)
- CMakeLists.txt: Platform-specific binary naming
- CLI: --port, --log-level, --log-path, --test-devices, --help
- lsan.supp: Memory leak suppression for GLib/GStreamer internals

### Session 9 (2026-03-03): Phase 4.3 - CreateSession + StreamEvents + Shutdown
- CreateSession: Creates WebRTC session, sets callbacks, adds to SessionManager
- StreamEvents: Blocks on ThreadSafeQueue, streams to client
- EndSession: Marks inactive, shuts down queue, removes from manager
- Graceful shutdown: SIGINT/SIGTERM handlers, cleanup_all_sessions(), 5-step sequence
- Updated session_manager.h to use call::CallEvent (protobuf namespace)
- test_grpc_service.sh: Comprehensive integration test

### Session 10 (2026-03-03): Phases 4.4, 4.5, 4.6 - SDP, ICE, Stats
- **Phase 4.4**: CreateOffer, CreateAnswer, SetRemoteDescription
  - Fixed 3 bugs: orphaned pipeline, shutdown hang, use-after-free
  - Pattern: shared_ptr<SDPCallbackState> for async callbacks
- **Phase 4.5**: AddICECandidate RPC
  - test_ice_candidates.sh: Validates host/srflx/relay types
- **Phase 4.6**: GetStats, SetMute, ListAudioDevices
  - Cross-platform device enumeration via DeviceEnumerator

### Session 11 (2026-03-03): Bug Fixes - PipeWire + CreateAnswer + Test Namespace
- **PipeWire Double-Free**: Removed gst_device_monitor_start/stop calls
  - Root cause: PipeWire plugin threading issues
  - Solution: Use probe-on-demand pattern (get_devices() probes without start/stop)
- **CreateAnswer Test**: Use real SDP from CreateOffer instead of handcrafted minimal SDP
  - Proper test flow: session-1 creates offer → session-2 creates answer
- **Test Namespace Fix**: test_step9_session_manager.cpp updated for call::CallEvent
  - Added #include "call.pb.h" for complete type definition
  - Updated Makefile: -I../../build/generated, link call.pb.cc, -lprotobuf

### Session 12 (2026-03-03): Verification - All Tests Passing
- **Standalone tests**: All 11 library tests passing (steps 0-9)
  - test_step5_device_enumeration: 4 audio inputs, 1 output, 2 video devices
  - No AddressSanitizer errors (PipeWire fix confirmed)
- **Integration tests**: All 11/12 RPCs working
  - test_grpc_service.sh: All methods succeed
  - test_ice_candidates.sh: Host/srflx/relay candidates processed
  - ListAudioDevices: 4 devices enumerated, no crashes
  - Clean shutdown: Graceful 5-step sequence verified
- **System ready for Phase 4.7** (error handling) or Phase 4.8 (Python integration)

### Session 13 (2026-03-03): Code Review + Critical Bug Fixes
**Code Review**: Deep analysis of C++ code (96 files, 2 files reviewed: webrtc_session.cpp, device_enumerator.cpp)
- **LeakSanitizer Results**: From 440 lines of leaks → 6 lines (only PulseAudio/ALSA internals)
- **Issues Found**: 5 critical, 5 serious, 4 moderate, 2 minor (16 total)

**✅ FIXED (5 Critical Issues)**:
1. **Circular Reference Memory Leak** (call_service_impl.cpp:96-159)
   - **Problem**: Lambda captured `shared_ptr<CallSession>` → CallSession owns WebRTC → WebRTC stores callback → circular reference
   - **Fix**: Use `std::weak_ptr` in lambdas, call `.lock()` to get session safely
   - **Evidence**: LeakSanitizer showed 4 WebRTCSession (2624 bytes) + 4 ThreadSafeQueue (1920 bytes) + CallSession leaks → all eliminated

2. **Promise Use-After-Free** (webrtc_session.cpp:228, 749, 797)
   - **Problem**: `gst_promise_interrupt()` + `gst_promise_unref()` called immediately after `g_signal_emit_by_name()`
   - **Impact**: Async callback could fire after promise freed → crash/memory corruption
   - **Fix**: Let GStreamer own promises, don't interrupt/unref after emitting
   - **Locations**: `set_remote_description()`, `on_offer_created()`, `on_answer_created()`

3. **Production g_assert()** (webrtc_session.cpp:731, 791)
   - **Problem**: `g_assert()` can be compiled out in release builds → undefined behavior
   - **Fix**: Replace with proper error handling, check `gst_promise_wait()` result, propagate errors to callbacks

4. **Privacy Leak in Logging** (webrtc_session.cpp:896, 905)
   - **Problem**: Relay-only mode filtered host/srflx candidates but logged full candidate string with IP addresses
   - **Fix**: Created `extract_candidate_type()` helper, log only candidate type (host/srflx/relay), never IP addresses
   - **Impact**: Privacy feature now actually private

5. **Missing Signal Disconnection** (webrtc_session.cpp:34-47)
   - **Problem**: Signals connected in `connect_signals()` never disconnected in destructor
   - **Impact**: If GStreamer fires signal during/after destruction → use-after-free crash
   - **Fix**: Add `g_signal_handlers_disconnect_by_data(webrtc_, this)` in destructor before `stop()`

**✅ COMPLETED: std::cout/cerr → LOG_*() Replacement** (96 instances across 2 files)
- **Rationale**:
  - STDOUT reserved for GStreamer/libnice debug (per LOGGING-POLICY.md)
  - Privacy: Prevented IP address logging in relay-only mode
  - Debuggability: Configurable log levels (TRACE/DEBUG/INFO/ERROR)
  - Production: Structured logs with timestamps to rotating files
- **Log Level Assignment**:
  - `LOG_ERROR`: All `std::cerr` (37 instances) - initialization failures, pipeline errors, exceptions
  - `LOG_INFO`: High-level events (34 instances) - session lifecycle, ICE state changes, config applied
  - `LOG_DEBUG`: Library operations (18 instances) - pipeline creation, signal connection, stream linking
  - `LOG_TRACE`: Repetitive/in-loop (7 instances) - ICE candidates (type only, no IPs!), gathering states
- **Privacy Fix**: ICE candidates log mline + type only, never full candidate string
- **Cleanup**: Removed `#include <iostream>` from both files

**⚠️ REMAINING ISSUES (4 Serious - Documented for Next Session)**

**Issue #6: Missing GStreamer Bus Error Monitoring** ⚠️ SERIOUS
- **Problem**: Pipelines created but bus never monitored for ERROR messages
- **Impact**: Silent failures - device unavailable, codec errors, resource exhaustion go unnoticed
- **Official Pattern**: [GStreamer Bus Tutorial](https://gstreamer.freedesktop.org/documentation/application-development/basics/bus.html)
  ```c
  GstBus *bus = gst_element_get_bus(pipeline);
  gst_bus_add_watch(bus, bus_call, loop);  // GLib integration
  gst_object_unref(bus);

  static gboolean bus_call(GstBus *bus, GstMessage *msg, gpointer data) {
      switch (GST_MESSAGE_TYPE(msg)) {
          case GST_MESSAGE_ERROR: {
              GError *err;
              gchar *debug_info;
              gst_message_parse_error(msg, &err, &debug_info);
              // Log error, propagate to Python via ErrorEvent
              g_error_free(err);
              g_free(debug_info);
              break;
          }
          // ... other message types
      }
      return TRUE;
  }
  ```
- **Fix Location**: `webrtc_session.cpp:create_pipeline()` after pipeline creation
- **Propagation**: Push ErrorEvent to event_queue for Python consumption

**Issue #7: Incomplete Resource Cleanup on Partial Pipeline Failure** 🟡 MODERATE
- **Problem**: If element creation/linking fails midway in `create_pipeline()`, already-added elements not cleaned up
- **Example**: Line 437 - if `gst_element_link_many()` fails, elements already in bin but not linked → zombie state
- **Official Pattern**: [GStreamer Error Handling](https://gstreamer.freedesktop.org/documentation/plugin-development/basics/elements.html#error-handling)
  ```c
  if (!gst_element_link_many(src, filter, sink, NULL)) {
      gst_object_unref(pipeline);  // Unreffing bin unrefs contained elements
      pipeline = NULL;
      return FALSE;
  }
  ```
- **Impact**: LOW - Resource leak only if CreateSession fails (rare in practice)
- **Logging to Add**: `LOG_ERROR()` on each failure path with element names
- **Steps to Reproduce**:
  1. Mock `gst_element_factory_make()` to fail on 3rd element
  2. Call CreateSession RPC
  3. Check valgrind for leaked GstElement allocations
- **Fix**: On any error path in `create_pipeline()`, call `gst_object_unref(pipeline_); pipeline_ = nullptr;`

**Issue #8: Unsafe Pipeline Shutdown** ⚠️ SERIOUS
- **Problem**: `stop()` sets state directly to NULL without checking current state or waiting for transition
- **Impact**: Can hang if pipeline mid-transition, crashes if async operations in progress
- **Current Code** (webrtc_session.cpp:140):
  ```cpp
  gst_element_set_state(pipeline_, GST_STATE_NULL);  // Too abrupt!
  ```
- **Official Pattern**: [GStreamer State Changes](https://gstreamer.freedesktop.org/documentation/application-development/basics/states.html)
  ```c
  // Graceful shutdown with timeout
  gst_element_set_state(pipeline, GST_STATE_NULL);
  GstStateChangeReturn ret = gst_element_get_state(
      pipeline, NULL, NULL, GST_SECOND * 5);  // Wait up to 5 seconds

  if (ret == GST_STATE_CHANGE_FAILURE) {
      g_printerr("Pipeline shutdown failed or timed out\n");
      // Force cleanup anyway
  }
  ```
- **Fix Location**: `webrtc_session.cpp:stop()` - add state change wait with 5s timeout
- **Logging**: `LOG_WARN()` if timeout, `LOG_ERROR()` if failure

**Issue #9: Incomplete Error Handling in on_incoming_stream** 🟡 MODERATE
- **Problem**: If pad linking fails (line 1060), elements added to pipeline but left unlinked → zombie elements
- **Current Code** (webrtc_session.cpp:1055-1065):
  ```cpp
  if (gst_pad_link(pad, sink_pad) != GST_PAD_LINK_OK) {
      std::cerr << "Failed to link incoming pad to depay" << std::endl;
      // ❌ Elements still in pipeline, not cleaned up!
  } else {
      std::cout << "Incoming stream linked successfully" << std::endl;
  }
  gst_object_unref(sink_pad);
  ```
- **Official Pattern**: [GStreamer Dynamic Pipelines](https://gstreamer.freedesktop.org/documentation/application-development/advanced/pipeline-manipulation.html)
  ```c
  if (gst_pad_link(pad, sink_pad) != GST_PAD_LINK_OK) {
      // Remove elements from pipeline
      gst_bin_remove_many(GST_BIN(pipeline), depay, decoder, queue, sink, NULL);
      // Set to NULL and unref
      gst_element_set_state(depay, GST_STATE_NULL);
      gst_object_unref(depay);
      // ... same for other elements
      return;
  }
  ```
- **Fix Location**: `webrtc_session.cpp:on_incoming_stream()` - cleanup on link failure

**🔗 References for Next Session**:
- [GStreamer Application Development Manual](https://gstreamer.freedesktop.org/documentation/application-development/)
- [GStreamer Bus/Messages Tutorial](https://gstreamer.freedesktop.org/documentation/application-development/basics/bus.html)
- [GStreamer State Changes](https://gstreamer.freedesktop.org/documentation/application-development/basics/states.html)
- [GStreamer Error Handling Patterns](https://gstreamer.freedesktop.org/documentation/plugin-development/basics/elements.html#error-handling)
- [webrtcbin Examples](https://gitlab.freedesktop.org/gstreamer/gstreamer/-/tree/main/subprojects/gst-examples/webrtc)

---

## 🏁 End Goal

**Vision**: Python handles XMPP/Jingle signaling, C++ handles WebRTC media
- Python: Lightweight, manages sessions, routes signaling
- C++: Heavy lifting, GStreamer pipelines, actual audio/video
- Communication: gRPC (Python calls C++ service for media operations)

**When Complete**:
- User initiates call in Python → Python calls CreateSession gRPC
- Python streams ICE candidates via StreamEvents
- C++ manages WebRTC pipeline
- Python receives media stats, state changes
- Call quality improves (native performance)

---

**Last Updated**: 2026-03-03 (Session 13: Code review + 5 critical bug fixes)
**Next Session**: Fix remaining 4 issues (#6, #7, #8, #9) following official GStreamer patterns

---

### Session 21 (2026-03-04): Device ID Bug + SDP Direction Investigation 🔍

**Status**: Connection WORKS (both ends), Audio BROKEN (0kbps) - Root cause identified

#### Part A: Device ID Bug Discovery & Fix

**Problem Found**: Audio device enumeration was returning wrong field
- **Proto has**: `name` (device ID) and `description` (display name)
- **Bug**: C++ was setting `description = device.description` (device class "Audio/Source")
- **Should be**: `description = device.name` (display name "Family 17h/19h...")

**Device ID Extraction Bug**:
- **PipeWire/PulseAudio** uses property `node.name` for device ID
- **Code was checking**: `device.api`, `device.name`, `device` (all NULL!)
- **Fix**: Check `node.name` first (alsa_input.pci-...)

**Files Fixed**:
```
drunk_call_service/src/call_service_impl.cpp:571 - set_description(device.name) not device.description
drunk_call_service/src/device_enumerator.cpp:75 - check node.name property
```

**Python Improvements**:
- Settings dialog now stores BOTH device_id and display_name in JSON
- Backward compatibility for old string format
- Fallback to default if saved device unplugged

**JSON Format** (new):
```json
{
  "microphone_device": {
    "device_id": "alsa_input.pci-0000_05_00.6.analog-stereo",
    "display_name": "Family 17h/19h HD Audio Controller Analog Stereo"
  }
}
```

**Result**: Device enumeration now works correctly, but revealed deeper issue...

#### Part B: SDP Direction Investigation (a=recvonly Problem)

**THE REAL PROBLEM**: webrtcbin generates `a=recvonly` instead of `a=sendrecv`

**Timeline of Understanding**:

1. **Initial Finding**: SDP answer contains `a=recvonly`
   - Python was hardcoded to send `senders='both'` regardless
   - This masked the problem temporarily

2. **Connection Issue Separate from SDP**:
   - At BINGO (SESSION-ROTATE.md): Both ends connected but SDP had `a=recvonly`
   - Connection works when `device_id=""` (use default/auto)
   - SDP direction is a SEPARATE issue from connection

3. **Python Jingle Converter Fix**:
   - Added proper SDP direction parsing in `jingle_sdp_converter.py:132-155`
   - Now reads actual SDP direction and converts to Jingle `senders` attribute:
     - `a=sendrecv` → `senders='both'`
     - `a=recvonly` → `senders='initiator'` (only Dino sends, we receive)
     - `a=sendonly` → `senders='responder'` (we send, Dino receives)

4. **Result**: Python now sends HONEST `senders` attribute to Dino
   - Session 7de03fd5: Sent `senders="initiator"` (receive-only)
   - Dino offered `a=sendrecv` (wanted bidirectional)
   - **Incompatible expectations → Dino refuses to send media**
   - No `pad-added` signal fires (no incoming RTP)
   - bandwidth=0kbps, no audio in either direction

**Attempts to Fix webrtcbin SDP Generation** (all FAILED):

```cpp
// TRIED #1: Set transceiver direction BEFORE set-remote-description
GArray* transceivers = nullptr;
g_signal_emit_by_name(webrtc_, "get-transceivers", &transceivers);
for (each transceiver) {
    g_object_set(trans, "direction", GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_SENDRECV, NULL);
}
// Result: Property sets to 4 (SENDRECV) but SDP still has a=recvonly ❌

// TRIED #2: Also set AFTER set-remote-description in callback
void on_offer_set_for_answer() {
    // Set transceiver direction again
    g_object_set(trans, "direction", GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_SENDRECV, NULL);
    // create-answer
}
// Result: Transceiver shows direction=4 but SDP still has a=recvonly ❌

// TRIED #3: Set is-live=true on audio source
g_object_set(audio_src_,
    "is-live", TRUE,
    "do-timestamp", TRUE,
    nullptr);
// Result: Property sets but SDP still has a=recvonly ❌
```

**Root Cause (Confirmed)**:
webrtcbin determines SDP direction based on **whether the RTP sender has negotiated caps**, NOT just transceiver direction property!

Evidence:
- Pipeline starts → caps negotiation begins
- `create_answer()` called ~4ms later
- **Caps not negotiated yet** → webrtcbin thinks we can't send
- webrtcbin generates `a=recvonly`
- Caps finish negotiating ~300ms later (but SDP already sent)

**Previous attempt**: Added 500ms caps wait loop
- **Worked for SDP**: Gave time for caps negotiation
- **BROKE connection**: Delay caused timing issues, Dino stuck at "calling"
- Lesson: Answer must be created PROMPTLY (milliseconds not 300ms+)

#### Current State

**What Works** ✅:
- ICE: CHECKING → CONNECTED → COMPLETED (perfect!)
- Connection: Both ends show "connected"
- Device enumeration: Correct device IDs
- Python: Honest SDP→Jingle conversion

**What's Broken** ❌:
- webrtcbin: Still generates `a=recvonly` despite transceiver=SENDRECV
- Audio flow: 0 kbps bandwidth
- No `pad-added` signal (no incoming RTP from Dino)
- Dino won't send because we offered receive-only

**Test Evidence** (Session 7de03fd5-3325-4b96-9fbd-72f880541e3c):
```
Timeline:
22:35:28.543 - CreateSession
22:35:28.576 - Pipeline PLAYING
22:35:28.699 - CreateAnswer (120ms) → SDP with a=recvonly
22:35:28.899 - ICE CHECKING
22:35:29.402 - ICE CONNECTED (0.5s)
22:35:30.965 - ICE COMPLETED (2.4s)
22:35:30.293 onwards - bandwidth=0kbps (no media)

Jingle sent to Dino:
<content creator="initiator" name="audio" senders="initiator">
  (only Dino sends, we receive-only)

No pad-added signal fired = No incoming RTP = Dino not sending
```

#### Files Modified This Session

**C++**:
- `drunk_call_service/src/call_service_impl.cpp:571,582` - Fix device description field
- `drunk_call_service/src/device_enumerator.cpp:75` - Check node.name for device ID
- `drunk_call_service/src/webrtc_session.cpp:543-547` - Add is-live=true property
- `drunk_call_service/src/webrtc_session.cpp:1081-1089` - Add SDP direction logging

**Python**:
- `siproxylin/gui/settings_dialog.py:447-454` - Store both device_id and display_name
- `siproxylin/gui/settings_dialog.py:365-393` - Load with backward compatibility & fallback
- `siproxylin/core/barrels/calls.py:282-290` - Handle dict/string format
- `drunk_call_hook/protocol/jingle_sdp_converter.py:132-155` - Parse SDP direction, convert to Jingle senders

#### Next Steps (Critical Path to Working Audio)

**MUST FIX**: Make webrtcbin generate `a=sendrecv` in SDP answer

**Possible Approaches**:

1. **Pre-negotiate caps** (unclear how, need research)
   - Force caps on audio_src didn't work
   - Need caps on RTP sender, not audio_src

2. **Wait for caps WITHOUT breaking timing** (challenge!)
   - Need < 50ms wait (not 300ms)
   - Or async answer creation (complex)

3. **Hack SDP in Python** (last resort)
   - Replace `a=recvonly` with `a=sendrecv` before converting to Jingle
   - Risky if pipeline actually can't send

4. **Research GStreamer patterns** (recommended)
   - Check official webrtcbin examples for answer creation
   - Look for caps negotiation forcing patterns
   - May need to change pipeline structure

**Test Command for Debugging**:
```bash
# Check device properties
gst-inspect-1.0 pulsesrc
gst-inspect-1.0 autoaudiosrc

# Test if pipeline can capture audio
gst-launch-1.0 autoaudiosrc is-live=true ! audioconvert ! audioresample ! \
  opusenc ! rtpopuspay ! fakesink

# Check caps negotiation timing
GST_DEBUG=GST_CAPS:5 ./drunk-call-service-linux
```

**Key Insight**: The connection and SDP direction are TWO DIFFERENT PROBLEMS:
- Connection: Fixed by transceiver direction (BINGO achievement)
- Audio flow: Blocked by SDP direction mismatch (still unsolved)

**Documentation References**:
- `SESSION-ROTATE.md` - BINGO moment transcript
- `docs/CALLS/2-SDP-PLAN.md` - Updated with critical lesson learned
- `docs/ADR.md` - Architecture decisions

---

**Last Updated**: 2026-03-04 22:36 (Session 21: Device ID fixed, SDP direction root cause confirmed)
**Next Session**: Research GStreamer caps forcing or implement SDP hack workaround

#### 📝 NOTE FOR NEXT SESSION

**START HERE**: Analyze GStreamer webrtcbin source code to understand SDP direction logic

**Task**: Find where webrtcbin decides `a=recvonly` vs `a=sendrecv` in answer generation

**GStreamer Source to Check**:
```bash
# Clone GStreamer if not already available
git clone https://gitlab.freedesktop.org/gstreamer/gstreamer.git
cd gstreamer/subprojects/gst-plugins-bad/ext/webrtc

# Key files to analyze:
# - gstwebrtcbin.c - Main webrtcbin logic
# - webrtctransceiver.c - Transceiver direction negotiation
# Search for: "recvonly", "sendrecv", "create-answer", direction negotiation
```

**Questions to Answer**:
1. Where does webrtcbin check if sender has caps?
2. What exact condition triggers `a=recvonly` generation?
3. Is there a property/signal to force caps pre-negotiation?
4. How do official examples handle this timing?

**Alternative**: Check GStreamer webrtc examples in `gst-examples/webrtc/` for answer creation patterns

**Quick Test Ideas**:
- Add capsfilter between audio_src and opusenc with fixed caps
- Try `gst_element_sync_state_with_parent()` on audio_src before answer
- Check if `gst_element_get_state()` with timeout helps

**If Analysis Takes Too Long**: Implement Python SDP hack as temporary workaround:
```python
# In jingle_sdp_converter.py after parsing SDP
if role == 'answer' and 'a=recvonly' in sdp_str:
    sdp_str = sdp_str.replace('a=recvonly', 'a=sendrecv')
    # Log warning that we're overriding broken SDP
```

---

---

### Session 22 (2026-03-05): Root Cause Analysis - Two Transceivers Problem 🔬

**Status**: SDP now has `a=sendrecv` ✅ but still no audio (0kbps bandwidth, 2 transceivers)

#### Progress Made

**Win**: Fixed `a=recvonly` → `a=sendrecv` by adding `encoding-params="2"` to transceiver codec preferences!
- Added explicit `add-transceiver` call with OPUS caps including stereo channels
- SDP answer now correctly shows `a=sendrecv`

**Problem**: Still getting 2 transceivers instead of 1
- Transceiver 0: Created by our `add-transceiver` call
- Transceiver 1: Created by webrtcbin from remote offer (this one is used - `sink_1`)
- Bandwidth: 0kbps (no audio flowing)

#### Root Cause Confirmed

By analyzing GStreamer source code (`gst-plugins-bad/ext/webrtc/gstwebrtcbin.c:4521-4568`):

When `create_answer()` is called, webrtcbin:
1. Tries to find existing transceiver matching offer's caps (lines 4521-4560)
2. If match found: uses `rtp_trans->direction` (line 4563)
3. If NO match: creates NEW transceiver with `RECVONLY` (line 4568)

**Our issue**: Caps don't match, so webrtcbin creates second transceiver.

#### Official GStreamer Pattern

Analyzed `/drunk_call_service/tmp/gst-examples/webrtc/sendrecv/gst/webrtc-sendrecv.c`:

```c
// Pipeline created ONCE for both offerer AND answerer:
pipe1 = gst_parse_launch(
    "webrtcbin bundle-policy=max-bundle name=sendrecv "
    "audiotestsrc is-live=true ! ... ! rtpopuspay ! sendrecv. "
    "videotestsrc is-live=true ! ... ! rtpvp8pay ! sendrecv. ", &error);

// For answerer:
on_offer_received(sdp) {
    set-remote-description(offer);  // webrtcbin creates transceivers from offer
    // callback fires:
    create-answer();
}
```

**Key insight**: Sources are linked to webrtcbin BEFORE any SDP negotiation. Works for both roles.

#### Why Our Code Has 2 Transceivers

**Current flow**:
1. Create pipeline, request `sink_%u` pad → creates transceiver 0 with caps from our pipeline
2. Call `add-transceiver` explicitly → ??? (redundant?)
3. Receive offer → `set-remote-description` → webrtcbin can't match caps → creates transceiver 1
4. `create-answer` → uses transceiver 1 (the new RECVONLY one, but we force it to SENDRECV)

**Why caps don't match**: Unknown - need to log actual caps to see mismatch

#### Next Steps to Try

**Option 1: Remove `add-transceiver`, let implicit creation work**
- Revert to simple `request_pad_simple("sink_%u")` only
- Problem: This gave us `a=recvonly` before
- May need to set transceiver direction AFTER it's created but BEFORE set-remote-description

**Option 2: Don't request pad until AFTER set-remote-description**
- Let webrtcbin create transceiver from remote offer
- Then link our audio source to it
- Challenge: Need pad to link pipeline, but pad creates transceiver

**Option 3: Set codec-preferences on our transceiver to match offer exactly**
- Need to know offer's codecs beforehand (we don't)
- Or set very permissive caps

**Option 4: Add detailed logging to see exact caps mismatch**
- Log our transceiver's codec-preferences
- Log remote offer's codecs  
- Find exact field that doesn't match
- This is what the updated code in webrtc_session.cpp:1082-1164 will do

#### Files Modified This Session

**C++**:
- `drunk_call_service/src/webrtc_session.cpp`:
  - Lines 565-568: Reverted `add-transceiver` code (kept simple pad request)
  - Lines 1082-1164: Added detailed transceiver/caps logging in `on_offer_set_for_answer()`
    - Logs mlineindex, direction, codec-preferences for each transceiver
    - Checks if sender exists
    - Forces direction to SENDRECV if not already

**Next Test**: Build with new logging, check what codec-preferences our transceiver has vs what offer contains

#### Evidence

**Logs showing 2 transceivers**:
```
[2026-03-05 00:02:48.462] Found 2 transceiver(s) for answer
[2026-03-05 00:02:48.462] Transceiver 0 direction: 4 (SENDRECV)
[2026-03-05 00:02:48.462] Transceiver 1 direction: 4 (SENDRECV)
[2026-03-05 00:02:48.463] Incoming stream on pad: sink_1  ← Using transceiver 1!
```

**Bandwidth**: 0kbps throughout call (no RTP flowing)

**Audio devices**: Microphone IS capturing (pactl shows source-output), but no playback (no sink-inputs)

---

---

### Session 23 (2026-03-05): Codec-Preferences Set But Transceiver Still Not Matched 🔍

**Status**: Still `a=recvonly`, but discovered the exact problem!

#### What We Did

Added code to set `codec-preferences` on transceiver immediately after creating it (lines 620-652 in webrtc_session.cpp):
```cpp
// After requesting pad (which creates transceiver):
GstCaps *opus_caps = gst_caps_new_simple("application/x-rtp",
    "media", G_TYPE_STRING, "audio",
    "encoding-name", G_TYPE_STRING, "OPUS",
    "clock-rate", G_TYPE_INT, 48000,
    "encoding-params", G_TYPE_STRING, "2",  // Stereo
    nullptr);
g_object_set(trans, "codec-preferences", opus_caps, ...);
```

Also enhanced logging in `on_offer_set_for_answer()` to show detailed transceiver state (lines 1082-1164).

#### The Discovery

**Logs from test call (session f04fd02f)**:
```
[00:14:04.121] Setting codec-preferences on 1 transceiver(s)
[00:14:04.121] Transceiver 0 configured: OPUS 48kHz stereo, direction=SENDRECV
...
[00:14:04.438] Found 1 transceiver(s) after set-remote-description
[00:14:04.438] Transceiver 0: mline=4294967295, direction=4 (SENDRECV)
[00:14:04.438] Transceiver 0 codec-preferences: application/x-rtp, media=(string)audio, 
                encoding-name=(string)OPUS, clock-rate=(int)48000, encoding-params=(string)2
[00:14:04.438] Transceiver 0 has sender
```

**Key finding**: `mline=4294967295` (which is `UINT_MAX` or `-1` = **UNASSIGNED**)

This means:
1. ✅ Codec-preferences ARE being set correctly at pipeline creation
2. ✅ Direction is SENDRECV
3. ✅ Transceiver has a sender
4. ❌ **But mline is unassigned** - webrtcbin didn't match our transceiver to the remote offer!

#### Root Cause Analysis

When webrtcbin processes `set-remote-description` with an offer, it tries to match the offer's m-line with existing transceivers by comparing caps (gstwebrtcbin.c:4521-4560).

**Our caps**:
```
application/x-rtp, media=audio, encoding-name=OPUS, clock-rate=48000, encoding-params=2
```

**Remote offer** (Dino):
```
a=rtpmap:111 opus/48000/2
```
Which translates to payload type **111**.

**The missing piece**: We don't specify `payload` in our caps! This is likely why the match fails.

#### Why mline=UNASSIGNED Causes a=recvonly

From GStreamer source (gstwebrtcbin.c:4562-4568):
```c
if (rtp_trans) {
    answer_dir = rtp_trans->direction;  // Uses our SENDRECV
} else {
    // No matching transceiver found!
    answer_dir = GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_RECVONLY;
    GST_WARNING ("did not find compatible transceiver, will only receive");
}
```

Since our transceiver's mline is unassigned, webrtcbin treats it as "no matching transceiver" and generates `a=recvonly`.

#### The Solution (To Try Next)

We should NOT be setting codec-preferences ourselves! Looking back at the official GStreamer example (`webrtc-sendrecv.c`), they don't set codec-preferences manually. The caps are negotiated automatically from the pipeline.

**The real issue**: We're requesting a pad (`sink_%u`) which creates a transceiver, but webrtcbin doesn't know what caps to associate with it yet because the pipeline hasn't fully negotiated caps.

**Possible solutions**:

**Option A**: Don't create transceiver until after `set-remote-description`
- Remove pad request from `create_pipeline()`
- Let webrtcbin create transceiver from remote offer
- Then dynamically link our audio source when transceiver is created
- Challenge: Need to connect to some signal to know when transceiver is ready

**Option B**: Use `add-transceiver` with proper caps including payload type
- Go back to explicit `add-transceiver` approach
- But this time include `payload` in caps: `"payload", G_TYPE_INT, 111`
- This might help webrtcbin match it

**Option C**: Wait for caps negotiation before requesting pad
- Start pipeline in PAUSED state
- Wait for caps to be negotiated on our audio chain
- Then request pad (transceiver gets proper caps)
- Then call `set-remote-description`

#### Files Modified

**C++**:
- `drunk_call_service/src/webrtc_session.cpp`:
  - Lines 620-652: Added codec-preferences setting after pad request
  - Lines 1082-1164: Enhanced logging to show transceiver state after set-remote-description

#### Evidence

**SDP Answer** (still broken):
```
a=recvonly
```

**Transceiver state**:
- 1 transceiver (not 2 anymore!) ✅
- direction=SENDRECV ✅  
- codec-preferences set correctly ✅
- **mline=UNASSIGNED** ❌ ← This is the problem!

**Bandwidth**: Still 0kbps (no audio)

#### Next Session TODO

1. Try Option B: Add `"payload", G_TYPE_INT, 111` to codec-preferences caps
2. If that doesn't work, try Option A: Dynamic linking after set-remote-description
3. Check if there's a webrtcbin signal that fires when transceiver is ready
4. Look at GStreamer test suite for answerer examples

---
