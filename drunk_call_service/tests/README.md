# Call Service Tests

**Testing Strategy**: Incremental validation at each layer

## Test Levels

### Level 1: GStreamer Standalone Tests (No gRPC) ✅ IMPLEMENTED

**Purpose**: Validate webrtcbin flow without gRPC complexity

**Location**: `tests/standalone/`

**Tests** (in order of implementation):
- `test_step0_gstreamer_basic.cpp` ✅ - GStreamer version, plugin availability, basic pipeline
- `test_step1_pipeline.cpp` ✅ - WebRTCSession class, pipeline creation, offer generation (Step 1)
- `test_step2_sdp_negotiation.cpp` ✅ - Full offer/answer negotiation, signaling states (Step 2)
- `test_audio_loopback.cpp` - Reference implementation from GStreamer examples

**Run**:
```bash
cd drunk_call_service/tests/standalone
make test              # Run all tests in sequence
./test_step1_pipeline  # Run specific test
```

**Benefits**:
- Fast iteration (no gRPC, Python)
- Easy debugging (single process, gdb)
- Validates GStreamer logic only

---

### Level 2: C++ Unit Tests (MediaSession Interface)

**Purpose**: Test MediaSession implementations in isolation

**Location**: `tests/unit/`

**Tests**:
- `test_webrtc_session.cpp` - WebRTCSession class methods
- `test_session_factory.cpp` - Factory logic, plugin detection
- `test_config.cpp` - Configuration parsing

**Framework**: Google Test (gtest)

**Run**:
```bash
cd drunk_call_service/build
./tests/unit_tests
```

---

### Level 3: gRPC Integration Tests (C++ Service)

**Purpose**: Test gRPC handlers with mock/real GStreamer

**Location**: `tests/integration/`

**Tests**:
- `test_grpc_service.cpp` - All RPC methods
- `test_concurrent_sessions.cpp` - Multiple sessions
- `test_threading.cpp` - Thread safety, deadlock detection

**Run**:
```bash
./drunk-call-service --test-mode &
./tests/integration/test_grpc_service
```

---

### Level 4: End-to-End Tests (Python Client)

**Purpose**: Full integration with Python/XMPP layer

**Location**: `../../tests/` (siproxylin project root)

**Tests**:
- `test_call_flow.py` - Full outgoing/incoming call
- `test_conversations_compat.py` - Interop with Conversations.im
- `test_dino_compat.py` - Interop with Dino

**Run**:
```bash
cd ../../tests
pytest test_call_flow.py -v
```

---

## Test Execution Order (Development)

**Phase 1** (Current): Standalone GStreamer tests
- Validate pipeline, SDP, ICE without gRPC
- Quick feedback loop

**Phase 2**: C++ unit tests
- Test MediaSession interface implementations
- Add as implementations mature

**Phase 3**: gRPC integration tests
- Test service layer, threading
- After gRPC handlers implemented

**Phase 4**: Python E2E tests
- Full stack validation
- After Python integration ready

---

## Test Data

**Location**: `tests/data/`

**Contents**:
- `sample_offer.sdp` - Valid SDP offer
- `sample_answer.sdp` - Valid SDP answer
- `ice_candidates.txt` - Sample ICE candidates
- `malformed_sdp.txt` - Invalid SDP for error testing

---

## Continuous Integration

**Goal**: Run all tests on commit

**CI Pipeline** (GitHub Actions):
```yaml
- Build service
- Run unit tests
- Run integration tests
- Run Python E2E tests (with test XMPP server)
```

---

## Manual Testing

**Interactive test client**: `tests/manual_test_client.py`

**Usage**:
```bash
python manual_test_client.py --session test-1 --create-offer
python manual_test_client.py --session test-1 --add-ice "candidate:..."
```

Useful for debugging specific scenarios.

---

**Next**: See `tests/standalone/test_audio_loopback.cpp` for first test to implement
