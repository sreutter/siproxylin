# GStreamer WebRTC Call Service - Architecture Plan

**Status**: Draft
**Date**: 2026-03-02
**Approach**: webrtcbin-first design, then map to gRPC interface

---

## Philosophy

**This is NOT protobuf-driven design**. We define the CORRECT webrtcbin flow first, based on GStreamer best practices and examples, then figure out what gRPC changes are needed to support it.

**Why**: Previous attempts to patch both ends simultaneously led to async timing issues and broken flows. The call service MUST follow webrtcbin's natural flow.

---

## Reference Materials

**GStreamer Examples**:
- `drunk_call_service/tmp/gst-examples/webrtc/sendrecv/gst/webrtc-sendrecv.c` - Full WebRTC flow with signaling
- `drunk_call_service/tmp/gst-plugins-bad1.0-1.22.0/tests/examples/webrtc/webrtc.c` - Bidirectional local test

**Code Reference**: `docs/CALLS/webrtcbin-reference.cpp` - All code examples with comments

**Official Docs**: https://gstreamer.freedesktop.org/documentation/webrtc/

**Inspect Live**: `gst-inspect-1.0 webrtcbin` - Current system capabilities

---

## Core WebRTC Flow (from GStreamer examples)

### Outgoing Call Flow (Offer)

1. Create pipeline with webrtcbin element
2. Set webrtcbin properties: `bundle-policy=max-bundle`, `ice-transport-policy`, STUN/TURN
3. Connect audio source → opus encoder → rtpopuspay → webrtcbin
4. Connect signals: `on-negotiation-needed`, `on-ice-candidate`, `pad-added`, state notifications
5. Set pipeline to `GST_STATE_PLAYING`
6. **Signal `on-negotiation-needed`** fires → emit `create-offer` action
7. **Promise callback**: offer ready → emit `set-local-description` → send SDP to peer via gRPC
8. **Signal `on-ice-candidate`** fires (multiple) → stream to peer via gRPC
9. Receive remote SDP answer → emit `set-remote-description`
10. **Signal `pad-added`** fires (incoming media) → link to audio sink
11. **Property `ice-connection-state`** transitions: new → checking → connected
12. **Property `connection-state`** transitions: connecting → connected

### Incoming Call Flow (Answer)

1. Create pipeline with webrtcbin element
2. Set properties (bundle-policy, ice-transport-policy, STUN/TURN)
3. Connect audio source chain
4. Set pipeline to `GST_STATE_READY` (not playing yet)
5. Receive remote SDP offer → emit `set-remote-description` with promise callback
6. **Promise callback**: offer set → emit `create-answer`
7. **Promise callback**: answer ready → emit `set-local-description` → send SDP to peer
8. Set pipeline to `GST_STATE_PLAYING`
9. **Signal `on-ice-candidate`** fires → stream to peer
10. **Signal `pad-added`** → link to audio sink
11. State transitions same as outgoing

**See**: `docs/CALLS/webrtcbin-reference.cpp` for full implementation

---

## GStreamer Webrtcbin API

### Signals (Callbacks)

| Signal | Parameters | Purpose | Reference |
|--------|-----------|---------|-----------|
| `on-negotiation-needed` | none | Trigger SDP negotiation | webrtcbin-reference.cpp:184 |
| `on-ice-candidate` | `guint mlineindex, gchar* candidate` | Local ICE candidate | webrtcbin-reference.cpp:276 |
| `pad-added` | `GstPad* pad` | Remote media stream | webrtcbin-reference.cpp:307 |
| `notify::ice-connection-state` | none | ICE state changed | webrtcbin-reference.cpp:342 |
| `notify::connection-state` | none | Connection state changed | webrtcbin-reference.cpp:359 |
| `notify::ice-gathering-state` | none | Gathering state changed | gst-inspect-1.0 webrtcbin |

### Actions (Signal Emissions)

| Action | Parameters | Return | Reference |
|--------|-----------|--------|-----------|
| `create-offer` | `GstStructure* options, GstPromise* promise` | async | webrtcbin-reference.cpp:142 |
| `create-answer` | `GstStructure* options, GstPromise* promise` | async | webrtcbin-reference.cpp:201 |
| `set-local-description` | `GstWebRTCSessionDescription*, GstPromise*` | async | webrtcbin-reference.cpp:159 |
| `set-remote-description` | `GstWebRTCSessionDescription*, GstPromise*` | async | webrtcbin-reference.cpp:240 |
| `add-ice-candidate` | `guint mlineindex, gchar* candidate` | void | webrtcbin-reference.cpp:295 |
| `get-stats` | `GstPad* pad, GstPromise* promise` | async | webrtcbin-reference.cpp:372 |
| `add-turn-server` | `gchar* uri` | boolean | webrtcbin-reference.cpp:107 |

### Properties

| Property | Type | Default | Purpose |
|----------|------|---------|---------|
| `bundle-policy` | enum | none | Bundle behavior (use `max-bundle`) |
| `ice-transport-policy` | enum | all | ICE candidates (all/relay) |
| `stun-server` | string | null | STUN server URI |
| `turn-server` | string | null | TURN server (convenience, use add-turn-server for multiple) |
| `ice-connection-state` | enum (readonly) | new | ICE connection state |
| `connection-state` | enum (readonly) | new | Peer connection state |
| `signaling-state` | enum (readonly) | stable | Signaling state |

**Full list**: `gst-inspect-1.0 webrtcbin` or webrtcbin.h

---

## State Machines

### ICE Connection State

```
NEW → CHECKING → CONNECTED → COMPLETED
  ↓       ↓           ↓
FAILED  DISCONNECTED  CLOSED
```

- **NEW**: Initial
- **CHECKING**: ICE checks in progress
- **CONNECTED**: Working candidate pair found (media flows)
- **COMPLETED**: All checks done
- **FAILED**: All checks failed
- **DISCONNECTED**: Lost connection
- **CLOSED**: Shut down

**Map to proto**: NEW/CHECKING → CHECKING, CONNECTED/COMPLETED → CONNECTED

### Peer Connection State

```
NEW → CONNECTING → CONNECTED
  ↓       ↓            ↓
CLOSED  FAILED    DISCONNECTED
```

### Signaling State

```
STABLE ⇄ HAVE_LOCAL_OFFER ⇄ HAVE_REMOTE_ANSWER → STABLE
  ↓
HAVE_REMOTE_OFFER ⇄ HAVE_LOCAL_ANSWER → STABLE
```

---

## Pipeline Architecture

### Audio-Only Pipeline

```
Outgoing:
  [pulsesrc] → [queue] → [opusenc] → [rtpopuspay] → [webrtcbin:sink_%u] → network

Incoming (dynamic, via pad-added signal):
  network → [webrtcbin:src_%u] → [rtpopusdepay] → [opusdec] → [queue] → [pulsesink]
```

**Key Points**:
- Outgoing: connected at pipeline creation
- Incoming: connected dynamically when `pad-added` fires
- Codec: Opus (payload 97, dynamic)
- Bundle: single ICE connection (`bundle-policy=max-bundle`)
- RTCP-MUX: automatic (`a=rtcp-mux`)

**Implementation**: See `docs/CALLS/webrtcbin-reference.cpp` create_audio_pipeline()

---

## Session Management

### Session Structure

See: `docs/CALLS/webrtcbin-reference.cpp` CallSession struct (line 18)

**Key Fields**:
- `pipeline`, `webrtc`: GStreamer elements
- `is_outgoing`: offer vs answer
- `relay_only`: ICE transport policy
- Device names, audio processing flags
- gRPC event stream writer (thread-safe)

### Session Lifecycle

1. **CreateSession** (gRPC) → allocate CallSession, create pipeline
2. **CreateOffer** or **CreateAnswer** → trigger webrtcbin SDP generation
3. **SetRemoteDescription** → apply peer's SDP
4. **AddICECandidate** (multiple) → add remote candidates
5. **Automatic**: ICE/DTLS handshake, media flow
6. **EndSession** → cleanup pipeline

---

## Threading Model

### GLib Main Loop (Required)

GStreamer signals fire in main loop thread. We run a service-wide main loop.

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 416-431

**Critical**: All GStreamer callbacks execute in main loop thread. Use thread-safe queues/mutexes for gRPC communication.

### Thread Safety

1. **GStreamer callbacks** (main loop) → push events to thread-safe queue
2. **gRPC handlers** (gRPC pool) → lock session, call GStreamer (thread-safe with locks)
3. **Event streaming** (per-session thread) → poll queue, stream to Python

---

## SDP Handling

### Creating Offers/Answers

See: `docs/CALLS/webrtcbin-reference.cpp`
- Offer creation: lines 142-171
- Answer creation: lines 177-225
- Set remote description: lines 231-252

**Flow**:
1. Emit action (`create-offer`/`create-answer`) with promise
2. Promise callback fires with SDP in GstStructure reply
3. Extract SDP: `gst_structure_get(reply, "offer", GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &sdp, NULL)`
4. Set local description: emit `set-local-description`
5. Convert to string: `gst_sdp_message_as_text(sdp->sdp)`
6. Return via gRPC

---

## ICE Candidate Handling

### Local Candidates (C++ → Python)

**Signal**: `on-ice-candidate` (webrtcbin-reference.cpp:276)
- Stream to Python via gRPC `StreamEvents`
- Thread-safe write with mutex

### Remote Candidates (Python → C++)

**Action**: `add-ice-candidate` (webrtcbin-reference.cpp:295)
- Emit signal directly
- Webrtcbin queues candidates if received before set-remote-description

---

## TURN/STUN Configuration

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 98-116

### STUN

Set property: `g_object_set(webrtc, "stun-server", "stun://host:port", NULL)`

### TURN

Emit action: `g_signal_emit_by_name(webrtc, "add-turn-server", "turn://user:pass@host:port", &success)`

**Multiple servers**: call `add-turn-server` multiple times

### Relay-Only Mode

Set property: `g_object_set(webrtc, "ice-transport-policy", GST_WEBRTC_ICE_TRANSPORT_POLICY_RELAY, NULL)`

**Privacy**: Forces TURN relay (no P2P), prevents IP leaks

---

## Audio Device Selection

### PulseAudio Devices

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 390-394

**Microphone**: `g_object_set(pulsesrc, "device", "alsa_input.pci-...", NULL)`
**Speakers**: `g_object_set(pulsesink, "device", "alsa_output.pci-...", NULL)`

### Device Enumeration

Use PulseAudio API or parse `pactl list sources/sinks`

**Proto**: `ListAudioDevices` returns device name + description

---

## Audio Processing (WebRTC DSP)

**Element**: `webrtcdsp` (gst-plugins-bad)

**Properties**:
- `echo-cancel`: boolean
- `echo-suppression-level`: 0-2
- `noise-suppression`: boolean
- `gain-control`: boolean

**Pipeline**: Insert between source and encoder: `pulsesrc → webrtcdsp → opusenc`

**Note**: Verify availability with `gst-inspect-1.0 webrtcdsp`

---

## Incoming Media (pad-added signal)

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 307-339

**Flow**:
1. Signal fires with `GstPad *pad` when remote media arrives
2. Check direction: `GST_PAD_DIRECTION(pad) == GST_PAD_SRC` (incoming only)
3. Create sink chain: depay → decoder → queue → audiosink
4. Add to pipeline, sync state: `gst_element_sync_state_with_parent()`
5. Link: `gst_element_link_many()` then `gst_pad_link(pad, sink_pad)`

---

## State Monitoring

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 342-368

### ICE Connection State

Connect: `g_signal_connect(webrtc, "notify::ice-connection-state", callback, session)`

Read: `g_object_get(webrtc, "ice-connection-state", &state, NULL)`

Stream to Python via gRPC event

### Connection State

Same pattern, property: `connection-state`

**Purpose**: Python needs real-time state for GUI updates

---

## Statistics

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 372-384

**Action**: `get-stats` with promise
**Reply**: `GstStructure` with WebRTC stats (bytes, bitrate, candidates, connection type)

**Parse**: Use `gst_structure_foreach()` to iterate stats

**Proto**: `GetStats` returns structured stats to Python

---

## Missing Protobuf Features

Based on webrtcbin flow analysis:

### 1. Bundle Support (Required)

**Status**: ✓ Transparent (webrtcbin handles with `bundle-policy=max-bundle`)
**Proto change**: None needed

### 2. RTCP-MUX (Required)

**Status**: ✓ Transparent (webrtcbin adds `a=rtcp-mux` automatically)
**Proto change**: None needed

### 3. Trickle ICE (Required)

**Status**: ✓ Already supported
**Current**: `AddICECandidate` + `StreamEvents` with `ICECandidateEvent`

### 4. Connection State Streaming (NEEDED)

**Current**: `ConnectionStateEvent` has basic enum
**Needed**: Add separate ICE state field

**Proposed proto change**:
```protobuf
message ConnectionStateEvent {
  State peer_connection_state = 1;  // Rename existing
  State ice_connection_state = 2;   // NEW: separate ICE state
}
```

**Rationale**: Python needs to distinguish ICE failures from general connection issues

### 5. Error Event Details (NEEDED)

**Current**: `ErrorEvent.message` (string only)
**Needed**: Structured error types

**Proposed proto change**:
```protobuf
message ErrorEvent {
  enum ErrorType {
    ICE_FAILED = 0;
    DTLS_FAILED = 1;
    PIPELINE_ERROR = 2;
    CODEC_ERROR = 3;
    DEVICE_ERROR = 4;
  }
  ErrorType type = 1;
  string message = 2;
  string details = 3;  // GStreamer error details
}
```

**Rationale**: GUI needs to show user-friendly error messages

### 6. Audio DSP Configuration (Optional)

**Current**: `CreateSessionRequest` has echo_cancel, noise_suppression, gain_control
**Status**: ✓ Adequate for now

**Future**: May need more granular control (suppression levels, etc.)

---

## Success Criteria (Testing)

### Outgoing Call

1. CreateSession → success
2. CreateOffer → valid SDP with opus, bundle, rtcp-mux, ice-options
3. ICE candidates stream via StreamEvents
4. SetRemoteDescription (answer) → success
5. ice-connection-state → CHECKING → CONNECTED
6. Audio bidirectional (verify with GetStats)
7. Mute/unmute works
8. EndSession → clean shutdown

### Incoming Call

1. CreateSession → success
2. CreateAnswer (with offer) → valid SDP
3. ICE candidates stream
4. ice-connection-state → CONNECTED
5. Audio bidirectional
6. GetStats works

### Interoperability

- **Conversations.im** (Android): Trickle ICE, bundle, TURN relay
- **Dino** (Linux): Standard WebRTC
- **Both**: OMEMO fingerprint verification (Python/Jingle layer)

**Test method**: Look at logs for:
- ICE state transitions
- SDP bundle/rtcp-mux attributes
- Candidate gathering completion
- Media flow (RTP packets)

---

## Build Configuration

### Dependencies

- GStreamer >= 1.22 (`gstreamer-1.0`, `gstreamer-webrtc-1.0`, `gstreamer-sdp-1.0`)
- gRPC C++ (`grpc++`, `protobuf`)
- CMake >= 3.20
- C++17

### Compilation

```bash
pkg-config --cflags --libs gstreamer-webrtc-1.0 gstreamer-sdp-1.0
# Output: -I/usr/include/gstreamer-1.0 ... -lgstwebrtc-1.0 -lgstsdp-1.0 ...
```

### CMakeLists.txt

**Location**: `drunk_call_service/CMakeLists.txt` (to be created)

**Key points**:
- Use `pkg_check_modules` for GStreamer
- Link: gstreamer-1.0, gstreamer-webrtc-1.0, gstreamer-sdp-1.0, grpc++, protobuf
- Install target: `drunk_call_service/bin/drunk-call-service-{linux,windows,macos}`

---

## Implementation Steps (Next)

1. **Create detailed step plans** (separate files):
   - `1-PIPELINE-PLAN.md`: Pipeline creation, audio routing
   - `2-SDP-PLAN.md`: Offer/answer handling, promises
   - `3-ICE-PLAN.md`: Candidate management, trickle ICE
   - `4-GRPC-PLAN.md`: Service integration, threading
   - `5-STATS-PLAN.md`: Statistics, device enumeration

2. **Each plan includes**:
   - Testable milestones
   - Expected log output
   - Failure modes
   - Rollback strategy

3. **Implementation approach**:
   - One step at a time
   - Test at each milestone (check logs)
   - Document progress in `{STEP}-STATUS.md`

---

**Last Updated**: 2026-03-02
**Status**: Ready for review and detailed planning
