# Implementation Roadmap - Getting Started

**Date**: 2026-03-02
**Status**: Ready to implement

---

## Answers to Key Questions

### Q1: Abstract Scaffolding for Dual Paths (webrtcbin/rtpbin)

**Answer**: Yes, abstract interface layer created.

**Files**:
- `drunk_call_service/src/media_session.h` - Abstract base class
- `drunk_call_service/src/webrtc_session.h` - webrtcbin implementation
- `drunk_call_service/src/rtp_session.h` - rtpbin stub (implement later)
- `drunk_call_service/src/session_factory.cpp` - Factory with plugin detection

**Pattern**: Polymorphic inheritance with factory

**Usage**:
```cpp
SessionConfig config;
config.preferred_type = MediaSession::Type::WEBRTC;

auto session = SessionFactory::create(config);
if (!session) {
    // No implementation available
}

session->initialize(config);
session->create_offer([](bool success, const SDPMessage &sdp, const std::string &error) {
    // Handle SDP
});
```

**Benefits**:
- ✓ Clean separation: GStreamer logic vs gRPC layer
- ✓ Easy to swap implementations (webrtcbin ↔ rtpbin)
- ✓ Testable: mock MediaSession for gRPC tests
- ✓ Future-proof: add video, screen sharing without breaking interface

---

### Q2: Test Strategy - Standalone or Integration?

**Answer**: Hybrid approach - standalone first, integration later.

**Test Levels** (see `drunk_call_service/tests/README.md`):

**Level 1: Standalone GStreamer Tests** (Start here!)
- Location: `tests/standalone/`
- No gRPC, no Python
- Fast iteration, easy debugging
- Tests:
  - `test_pipeline.cpp` - GStreamer basics
  - `test_audio_loopback.cpp` - Full WebRTC loopback

**Build & Run**:
```bash
cd drunk_call_service/tests/standalone
make
./test_pipeline           # Quick smoke test
./test_audio_loopback     # Interactive audio test
```

**Level 2-4**: Unit tests → gRPC integration → Python E2E (later)

**Recommendation**: Implement standalone tests FIRST to validate GStreamer flow, then add gRPC layer.

---

### Q3: Use GStreamer Test Samples?

**Answer**: Yes! Standalone tests based on official examples.

**Sources used**:
- `drunk_call_service/tmp/gst-examples/webrtc/sendrecv/gst/webrtc-sendrecv.c`
- `drunk_call_service/tmp/gst-plugins-bad1.0-1.22.0/tests/examples/webrtc/webrtc.c`

**Our test adaptations**:
- `test_audio_loopback.cpp` - Based on webrtc.c (two webrtcbins, local loopback)
- Uses same signal flow: on-negotiation-needed → create-offer → ...
- Prints SDP, ICE candidates for verification
- Audio-only (simpler than video examples)

**Reusable patterns**:
- Promise callbacks for async SDP ops
- Signal handlers for ICE candidates
- pad-added for incoming media
- All patterns map directly to `WebRTCSession` class

---

## Implementation Order (Recommended)

### Phase 1: Standalone Validation (Week 1)

**Goal**: Prove GStreamer webrtcbin works

**Steps**:
1. Compile standalone tests:
   ```bash
   cd drunk_call_service/tests/standalone
   make test_pipeline
   ./test_pipeline
   ```
   Expected: ✓ All plugins found, pipeline works

2. Run audio loopback test:
   ```bash
   make test_audio_loopback
   GST_DEBUG=webrtcbin:5 ./test_audio_loopback 2>&1 | tee loopback.log
   ```
   Expected: SDP printed, ICE candidates exchanged, "Audio should be playing now"

3. Verify logs match expectations from `docs/CALLS/1-PIPELINE-PLAN.md`

4. Create `tests/standalone/1-STANDALONE-STATUS.md` documenting:
   - Test results (pass/fail)
   - SDP samples that worked
   - Timing measurements (offer creation, ICE gathering)
   - Issues encountered

**Deliverable**: Proof that webrtcbin works on your system

---

### Phase 2: Implement WebRTCSession Class (Week 2)

**Goal**: Wrap GStreamer in MediaSession interface

**Steps**:
1. Implement `WebRTCSession::initialize()` - pipeline creation
2. Implement `WebRTCSession::create_offer()` - async with callback
3. Implement `WebRTCSession::create_answer()` - promise chain
4. Implement ICE candidate handling
5. Test with standalone harness (no gRPC yet)

**Reference**: Copy patterns from `test_audio_loopback.cpp` into class methods

**Test**:
```cpp
WebRTCSession session;
SessionConfig config;
config.session_id = "test-1";
session.initialize(config);

session.create_offer([](bool success, const SDPMessage &sdp, const std::string &error) {
    std::cout << "Offer: " << sdp.sdp_text << std::endl;
});

// Run main loop...
```

**Deliverable**: `WebRTCSession` class working, testable without gRPC

---

### Phase 3: Add gRPC Layer (Week 3)

**Goal**: Integrate with proto/call.proto

**Steps**:
1. Implement gRPC service class using `MediaSession` interface
2. Thread-safe session management (map with mutex)
3. Event streaming (StreamEvents RPC)
4. All RPCs from `4-GRPC-PLAN.md`

**Test**: Python client can create session, exchange SDP

---

### Phase 4: Python Integration (Week 4)

**Goal**: Full stack working with XMPP/Jingle

**Steps**:
1. Update Python bridge to use new service
2. Test with Conversations.im
3. Test with Dino
4. Performance tuning, debugging

---

## Quick Start Guide

**Right now, you can**:

1. **Compile standalone test**:
   ```bash
   cd /home/m/claude/siproxylin/drunk_call_service/tests/standalone
   g++ test_pipeline.cpp -o test_pipeline \
       $(pkg-config --cflags --libs gstreamer-1.0)
   ./test_pipeline
   ```

2. **Run audio loopback**:
   ```bash
   g++ test_audio_loopback.cpp -o test_audio_loopback \
       $(pkg-config --cflags --libs gstreamer-webrtc-1.0 gstreamer-sdp-1.0)
   ./test_audio_loopback
   ```

3. **Verify GStreamer examples work**:
   ```bash
   cd /home/m/claude/siproxylin/drunk_call_service/tmp/gst-examples/webrtc/sendrecv/gst
   make
   # Requires websocket server, see README
   ```

**Expected outcome**: Understand webrtcbin signal flow before implementing class

---

## Documentation Map

**Architecture**:
- `docs/CALLS/PLAN.md` - Master plan (read first)
- `docs/CALLS/webrtcbin-reference.cpp` - Code examples

**Step-by-step plans**:
- `docs/CALLS/1-PIPELINE-PLAN.md` - Pipeline setup
- `docs/CALLS/2-SDP-PLAN.md` - Offer/answer
- `docs/CALLS/3-ICE-PLAN.md` - Candidates
- `docs/CALLS/4-GRPC-PLAN.md` - Service integration
- `docs/CALLS/5-STATS-PLAN.md` - Statistics

**Implementation**:
- `drunk_call_service/src/media_session.h` - Abstract interface
- `drunk_call_service/src/webrtc_session.h` - webrtcbin wrapper (implement this)
- `drunk_call_service/tests/standalone/` - Standalone tests (start here)

**Status tracking**:
- Create `X-PIPELINE-STATUS.md` as you implement each step
- Document what worked, what didn't, timing measurements

---

## Success Criteria (Phase 1)

Before moving to Phase 2, verify:

- [x] `test_pipeline` passes (all plugins available)
- [x] `test_audio_loopback` runs (SDP negotiated, ICE connected)
- [x] Logs show correct state transitions (see 2-SDP-PLAN.md, 3-ICE-PLAN.md)
- [x] Can hear audio (mic → speaker with delay)
- [x] No GStreamer errors or warnings
- [x] Understand signal flow (on-negotiation-needed → create-offer → ...)

**Time estimate**: 2-3 days to validate GStreamer setup and understand flow

---

## Troubleshooting Early Issues

### Issue: Plugins not found

**Fix**:
```bash
export GST_PLUGIN_PATH=/usr/lib/x86_64-linux-gnu/gstreamer-1.0
gst-inspect-1.0 webrtcbin
```

### Issue: Audio loopback no sound

**Possible causes**:
- Mic/speaker not configured (check `pactl list sources/sinks`)
- Wrong audio backend (try `audiotestsrc` instead of real mic)
- Volume muted

### Issue: ICE candidates not generated

**Possible causes**:
- No STUN server (add to webrtcbin: `stun-server=stun://stun.l.google.com:19302`)
- Firewall blocking UDP

**Debug**:
```bash
GST_DEBUG=nice:5,webrtcbin:5 ./test_audio_loopback
```

---

**Next Steps**: Start with Phase 1 - compile and run standalone tests!

---

**Last Updated**: 2026-03-02
