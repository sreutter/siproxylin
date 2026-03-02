# Call Service Tests

**Testing Strategy**: Incremental validation at each layer

## Test Levels

### Level 1: GStreamer Standalone Tests (No gRPC)

**Purpose**: Validate webrtcbin flow without gRPC complexity

**Location**: `tests/standalone/`

**Tests**:
- `test_pipeline.cpp` - Pipeline creation, element linking, PLAYING state
- `test_sdp_local.cpp` - Create offer/answer locally (two webrtcbins in one process)
- `test_ice_loopback.cpp` - ICE candidates, local connectivity
- `test_audio_loopback.cpp` - Full call loopback (mic → speaker)

**Run**:
```bash
cd drunk_call_service/tests/standalone
./test_pipeline
./test_audio_loopback
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
