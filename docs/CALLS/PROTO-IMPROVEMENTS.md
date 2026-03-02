# Protocol Buffers Improvements

**Status**: Planning
**Date**: 2026-03-02
**Urgency**: MEDIUM - Current proto works but missing features

**See Also**:
- drunk_call_service/proto/call.proto - Current definition
- docs/CALLS/4-GRPC-PLAN.md - gRPC integration requirements
- docs/CALLS/JINGLE-REFACTOR-PLAN.md - Jingle cleanup

---

## Current Proto Analysis

### What Works

```protobuf
service CallService {
  rpc CreateSession(CreateSessionRequest) returns (CreateSessionResponse);
  rpc CreateOffer(CreateOfferRequest) returns (SDPResponse);
  rpc CreateAnswer(CreateAnswerRequest) returns (SDPResponse);
  rpc SetRemoteDescription(SetRemoteDescriptionRequest) returns (Empty);
  rpc AddICECandidate(AddICECandidateRequest) returns (Empty);
  rpc EndSession(EndSessionRequest) returns (Empty);
  rpc StreamEvents(StreamEventsRequest) returns (stream CallEvent);
  rpc GetStats(GetStatsRequest) returns (GetStatsResponse);
  rpc ListAudioDevices(Empty) returns (ListAudioDevicesResponse);
  rpc SetMute(SetMuteRequest) returns (Empty);
  rpc Heartbeat(Empty) returns (Empty);
  rpc Shutdown(Empty) returns (Empty);
}
```

**Analysis**: Good coverage of call lifecycle, but events/stats need improvement.

### What's Missing

1. **Separate ICE connection state** from peer connection state
2. **Structured error types** (not just string messages)
3. **ICE gathering state** events
4. **Detailed stats** (packet loss, RTT, jitter)
5. **Video support** (future, but structure should allow it)

---

## Problem 1: Connection State Conflation

### Current Proto

```protobuf
message ConnectionStateEvent {
  enum State {
    NEW = 0;
    CHECKING = 1;
    CONNECTED = 2;
    COMPLETED = 3;
    FAILED = 4;
    DISCONNECTED = 5;
    CLOSED = 6;
  }
  State state = 1;
}
```

### Problem

This mixes **ICE connection state** and **peer connection state** into one field.

**WebRTC has three separate states**:
1. **Signaling State**: stable, have-local-offer, have-remote-offer, have-local-answer, have-remote-answer
2. **ICE Connection State**: new, checking, connected, completed, failed, disconnected, closed
3. **Peer Connection State**: new, connecting, connected, disconnected, failed, closed

**Python cares about ICE connection state** for GUI updates ("Connecting...", "Connected", "Failed").

**Current Go implementation**: Sends ICE connection state as `state`, ignoring peer connection state.

### Proposed Fix

```protobuf
message ConnectionStateEvent {
  // ICE connection state (most important for GUI)
  enum ICEConnectionState {
    ICE_NEW = 0;
    ICE_CHECKING = 1;
    ICE_CONNECTED = 2;
    ICE_COMPLETED = 3;
    ICE_FAILED = 4;
    ICE_DISCONNECTED = 5;
    ICE_CLOSED = 6;
  }
  ICEConnectionState ice_connection_state = 1;

  // Peer connection state (overall connection)
  enum PeerConnectionState {
    PEER_NEW = 0;
    PEER_CONNECTING = 1;
    PEER_CONNECTED = 2;
    PEER_DISCONNECTED = 3;
    PEER_FAILED = 4;
    PEER_CLOSED = 5;
  }
  PeerConnectionState peer_connection_state = 2;

  // ICE gathering state (useful for debugging)
  enum ICEGatheringState {
    GATHERING_NEW = 0;
    GATHERING_GATHERING = 1;
    GATHERING_COMPLETE = 2;
  }
  ICEGatheringState ice_gathering_state = 3 [optional];
}
```

**Benefit**:
- Python can differentiate ICE issues from general connection issues
- Better debugging (know exactly which layer failed)
- Forward compatible with future states

**Migration**: Existing Python code uses `state` field → change to `ice_connection_state`.

---

## Problem 2: Unstructured Errors

### Current Proto

```protobuf
message ErrorEvent {
  string message = 1;
}
```

### Problem

Python receives generic error strings like "Pipeline error: ..." and has to:
1. Parse the string to determine error type
2. Show generic error message to user
3. Can't take appropriate action (e.g., retry for transient errors)

**Examples of errors**:
- ICE failed (show "Connection failed", suggest checking network)
- DTLS failed (show "Encryption failed", security issue)
- Proxy unreachable (show "Proxy error", check proxy settings)
- Device busy (show "Microphone in use", close other apps)
- Codec error (show "Audio format error", usually a bug)

### Proposed Fix

```protobuf
message ErrorEvent {
  // Error category
  enum ErrorType {
    UNKNOWN = 0;
    ICE_FAILED = 1;           // ICE connection failed (network issue)
    DTLS_FAILED = 2;          // DTLS handshake failed (encryption)
    PIPELINE_ERROR = 3;       // GStreamer pipeline error
    CODEC_ERROR = 4;          // Codec negotiation/encoding error
    DEVICE_ERROR = 5;         // Audio device error (busy, missing, etc.)
    PROXY_ERROR = 6;          // Proxy unreachable or auth failed
    TURN_ERROR = 7;           // TURN server unreachable or auth failed
    TIMEOUT = 8;              // Operation timed out
  }
  ErrorType type = 1;

  // Human-readable error message (for logs/debugging)
  string message = 2;

  // Additional context (GStreamer error details, etc.)
  string debug_info = 3;

  // Error code (if applicable, e.g., HTTP status, TURN error code)
  int32 code = 4 [optional];

  // Is this a retryable error?
  bool retryable = 5 [optional];
}
```

**Benefit**:
- Python can show appropriate error messages to user
- GUI can suggest fixes (e.g., "Check proxy settings" for PROXY_ERROR)
- Telemetry can categorize errors (ICE failures vs device issues)
- Can implement retry logic for transient errors

**C++ Implementation**:
```cpp
// In WebRTCSession::on_ice_connection_state
if (ice_state == ICEConnectionState::FAILED) {
    CallEvent event;
    event.set_session_id(session->session_id);
    auto* error_event = event.mutable_error();
    error_event->set_type(ErrorEvent::ICE_FAILED);
    error_event->set_message("ICE connection failed");
    error_event->set_debug_info("All candidate pairs failed, check network/firewall");
    error_event->set_retryable(true);
    session->event_queue->push(event);
}
```

---

## Problem 3: Incomplete Stats

### Current Proto

```protobuf
message GetStatsResponse {
  string connection_state = 1;
  string ice_connection_state = 2;
  string ice_gathering_state = 3;
  int64 bytes_sent = 4;
  int64 bytes_received = 5;
  int64 bandwidth_kbps = 6;
  repeated string local_candidates = 7;
  repeated string remote_candidates = 8;
  string connection_type = 9;  // "P2P (direct)", "TURN relay", etc.
}
```

### Problems

1. **No quality metrics**: packet loss, RTT, jitter (important for debugging call quality issues)
2. **Strings for states**: Should be enums for type safety
3. **No codec info**: What codec is actually being used? (useful for debugging)
4. **No SSRC info**: Can't correlate with SDP/Jingle

### Proposed Fix

```protobuf
message GetStatsResponse {
  // Connection states (enums, not strings)
  ConnectionStateEvent.PeerConnectionState peer_connection_state = 1;
  ConnectionStateEvent.ICEConnectionState ice_connection_state = 2;
  ConnectionStateEvent.ICEGatheringState ice_gathering_state = 3;

  // Traffic stats
  int64 bytes_sent = 4;
  int64 bytes_received = 5;
  int64 packets_sent = 6;
  int64 packets_received = 7;
  int64 bandwidth_kbps = 8;  // Current bandwidth (smoothed)

  // Quality metrics
  double packet_loss_percent = 9;   // Packet loss rate (0.0 - 100.0)
  int32 rtt_ms = 10;                 // Round-trip time in milliseconds
  int32 jitter_ms = 11;              // Jitter in milliseconds

  // ICE candidates
  repeated ICECandidateInfo local_candidates = 12;
  repeated ICECandidateInfo remote_candidates = 13;
  ICECandidatePairInfo active_candidate_pair = 14;  // Currently used pair

  // Codec info
  AudioCodecInfo audio_codec = 15;

  // Connection type (for quick display)
  string connection_type = 16;  // "P2P (direct)", "P2P (srflx)", "TURN relay"

  // Timestamps
  int64 timestamp_us = 17;  // When stats were collected (microseconds since epoch)
  int64 duration_ms = 18;   // Call duration in milliseconds
}

message ICECandidateInfo {
  string candidate_id = 1;
  string ip = 2;
  int32 port = 3;
  string protocol = 4;  // "UDP", "TCP"
  string type = 5;      // "host", "srflx", "relay"
  int32 priority = 6;
}

message ICECandidatePairInfo {
  ICECandidateInfo local_candidate = 1;
  ICECandidateInfo remote_candidate = 2;
  bool nominated = 3;
  int64 bytes_sent = 4;
  int64 bytes_received = 5;
  int32 rtt_ms = 6;
}

message AudioCodecInfo {
  string name = 1;          // "opus", "PCMU", etc.
  int32 payload_type = 2;   // RTP payload type
  int32 clockrate = 3;      // 48000, 8000, etc.
  int32 channels = 4;       // 1 (mono), 2 (stereo)
  map<string, string> parameters = 5;  // fmtp parameters
}
```

**Benefit**:
- Python can show detailed call quality metrics in GUI
- Can diagnose issues (high packet loss → network issue, high jitter → WiFi issue)
- Telemetry can track codec usage, connection types
- Better debugging tools

**C++ Implementation** (in WebRTCSession::get_stats()):
```cpp
Stats WebRTCSession::get_stats() const {
    Stats stats;

    // ... existing code ...

    // Get webrtcbin stats via get-stats action
    GstPromise *promise = gst_promise_new();
    g_signal_emit_by_name(webrtc_, "get-stats", NULL, promise);
    gst_promise_wait(promise);

    const GstStructure *stats_struct = gst_promise_get_reply(promise);
    // Parse GstStructure for RTP stats (packet loss, jitter, etc.)
    // See: gstreamer.freedesktop.org/documentation/webrtc/webrtcbin.html#webrtcbin:get-stats

    stats.packet_loss_percent = /* parse from stats_struct */;
    stats.rtt_ms = /* parse from stats_struct */;
    stats.jitter_ms = /* parse from stats_struct */;

    gst_promise_unref(promise);

    return stats;
}
```

---

## Problem 4: No Video Support (Future-Proofing)

### Current State

Everything is hardcoded for audio: `CreateSessionRequest` has `microphone_device`, `speakers_device`, but no camera.

### Proposed Fix

Add video support to proto **now** (even if not implemented yet):

```protobuf
message CreateSessionRequest {
  string session_id = 1;
  string peer_jid = 2;

  // Audio devices
  string microphone_device = 3;
  string speakers_device = 4;

  // Video device (NEW, optional for now)
  string camera_device = 19;

  // ... existing proxy/TURN/audio processing fields ...

  // Video settings (NEW, optional)
  VideoSettings video_settings = 20 [optional];
}

message VideoSettings {
  bool enabled = 1;             // Enable video in call
  int32 width = 2;              // Requested width (e.g., 640, 1280)
  int32 height = 3;             // Requested height (e.g., 480, 720)
  int32 framerate = 4;          // Requested FPS (e.g., 15, 30)
  int32 max_bitrate_kbps = 5;   // Max video bitrate
}

message AudioDevice {
  string name = 1;
  string description = 2;
  string device_class = 3;  // "Audio/Source", "Audio/Sink", "Video/Source" (NEW)
}

// Rename to DeviceInfo (supports audio + video)
message ListAudioDevicesResponse {
  repeated AudioDevice devices = 1;  // Now includes video devices with class="Video/Source"
}
```

**Benefit**: When we add video, we don't need to change proto (just implement in C++).

---

## Problem 5: Missing Heartbeat Context

### Current Proto

```protobuf
rpc Heartbeat(Empty) returns (Empty);
```

### Problem

Heartbeat is blind - service doesn't know which Python process sent it.

**Scenario**: Multiple Python processes (e.g., user runs two instances) connect to same service. Service can't differentiate.

### Proposed Fix (Optional)

```protobuf
message HeartbeatRequest {
  string client_id = 1;  // UUID identifying Python process
}

rpc Heartbeat(HeartbeatRequest) returns (Empty);
```

**Benefit**: Service can track active clients, log client reconnects.

**Downside**: Requires Python changes.

**Decision**: Keep as `Empty` for now (single-user app, not critical).

---

## Complete Proposed Proto Changes

### call.proto (Updated)

```protobuf
syntax = "proto3";

package call;

option go_package = "github.com/yourusername/drunk-call-service/proto";

service CallService {
  // (RPCs unchanged)
  rpc CreateSession(CreateSessionRequest) returns (CreateSessionResponse);
  rpc CreateOffer(CreateOfferRequest) returns (SDPResponse);
  rpc CreateAnswer(CreateAnswerRequest) returns (SDPResponse);
  rpc SetRemoteDescription(SetRemoteDescriptionRequest) returns (Empty);
  rpc AddICECandidate(AddICECandidateRequest) returns (Empty);
  rpc EndSession(EndSessionRequest) returns (Empty);
  rpc StreamEvents(StreamEventsRequest) returns (stream CallEvent);
  rpc Heartbeat(Empty) returns (Empty);
  rpc Shutdown(Empty) returns (Empty);
  rpc GetStats(GetStatsRequest) returns (GetStatsResponse);
  rpc ListAudioDevices(Empty) returns (ListAudioDevicesResponse);
  rpc SetMute(SetMuteRequest) returns (Empty);
}

// Request/Response messages (mostly unchanged)

message CreateSessionRequest {
  string session_id = 1;
  string peer_jid = 2;
  string microphone_device = 3;
  string speakers_device = 4;

  // Proxy configuration
  string proxy_host = 5;
  int32 proxy_port = 6;
  string proxy_username = 7;
  string proxy_password = 8;
  string proxy_type = 9;

  // TURN server configuration
  string turn_server = 10;
  string turn_username = 11;
  string turn_password = 12;

  // ICE transport policy
  bool relay_only = 13;

  // Audio processing (WebRTC DSP)
  bool echo_cancel = 14;
  int32 echo_suppression_level = 15;
  bool noise_suppression = 16;
  int32 noise_suppression_level = 17;
  bool gain_control = 18;

  // Video (NEW, optional for future)
  string camera_device = 19;
  VideoSettings video_settings = 20;
}

message VideoSettings {
  bool enabled = 1;
  int32 width = 2;
  int32 height = 3;
  int32 framerate = 4;
  int32 max_bitrate_kbps = 5;
}

message CreateSessionResponse {
  bool success = 1;
  string error = 2;
}

message CreateOfferRequest {
  string session_id = 1;
}

message CreateAnswerRequest {
  string session_id = 1;
  string remote_sdp = 2;
}

message SDPResponse {
  string sdp = 1;
  string error = 2;
}

message SetRemoteDescriptionRequest {
  string session_id = 1;
  string remote_sdp = 2;
  string sdp_type = 3;
}

message AddICECandidateRequest {
  string session_id = 1;
  string candidate = 2;
  string sdp_mid = 3;
  int32 sdp_mline_index = 4;
}

message EndSessionRequest {
  string session_id = 1;
}

message StreamEventsRequest {
  string session_id = 1;
}

message Empty {}

// Event messages (UPDATED)

message CallEvent {
  string session_id = 1;
  oneof event {
    ICECandidateEvent ice_candidate = 2;
    ConnectionStateEvent connection_state = 3;
    ErrorEvent error = 4;
  }
}

message ICECandidateEvent {
  string candidate = 1;
  string sdp_mid = 2;
  int32 sdp_mline_index = 3;
}

message ConnectionStateEvent {
  // ICE connection state (UPDATED: now separate from peer connection state)
  enum ICEConnectionState {
    ICE_NEW = 0;
    ICE_CHECKING = 1;
    ICE_CONNECTED = 2;
    ICE_COMPLETED = 3;
    ICE_FAILED = 4;
    ICE_DISCONNECTED = 5;
    ICE_CLOSED = 6;
  }
  ICEConnectionState ice_connection_state = 1;

  // Peer connection state (NEW)
  enum PeerConnectionState {
    PEER_NEW = 0;
    PEER_CONNECTING = 1;
    PEER_CONNECTED = 2;
    PEER_DISCONNECTED = 3;
    PEER_FAILED = 4;
    PEER_CLOSED = 5;
  }
  PeerConnectionState peer_connection_state = 2;

  // ICE gathering state (NEW)
  enum ICEGatheringState {
    GATHERING_NEW = 0;
    GATHERING_GATHERING = 1;
    GATHERING_COMPLETE = 2;
  }
  ICEGatheringState ice_gathering_state = 3;
}

message ErrorEvent {
  // Error type (NEW: structured error types)
  enum ErrorType {
    UNKNOWN = 0;
    ICE_FAILED = 1;
    DTLS_FAILED = 2;
    PIPELINE_ERROR = 3;
    CODEC_ERROR = 4;
    DEVICE_ERROR = 5;
    PROXY_ERROR = 6;
    TURN_ERROR = 7;
    TIMEOUT = 8;
  }
  ErrorType type = 1;

  // Human-readable error message
  string message = 2;

  // Debug info (NEW)
  string debug_info = 3;

  // Error code (NEW, optional)
  int32 code = 4;

  // Retryable? (NEW, optional)
  bool retryable = 5;
}

// GetStats messages (UPDATED)

message GetStatsRequest {
  string session_id = 1;
}

message GetStatsResponse {
  // Connection states (UPDATED: now enums)
  ConnectionStateEvent.PeerConnectionState peer_connection_state = 1;
  ConnectionStateEvent.ICEConnectionState ice_connection_state = 2;
  ConnectionStateEvent.ICEGatheringState ice_gathering_state = 3;

  // Traffic stats (UPDATED: added packets)
  int64 bytes_sent = 4;
  int64 bytes_received = 5;
  int64 packets_sent = 6;
  int64 packets_received = 7;
  int64 bandwidth_kbps = 8;

  // Quality metrics (NEW)
  double packet_loss_percent = 9;
  int32 rtt_ms = 10;
  int32 jitter_ms = 11;

  // ICE candidates (UPDATED: structured)
  repeated ICECandidateInfo local_candidates = 12;
  repeated ICECandidateInfo remote_candidates = 13;
  ICECandidatePairInfo active_candidate_pair = 14;

  // Codec info (NEW)
  AudioCodecInfo audio_codec = 15;

  // Connection type (unchanged)
  string connection_type = 16;

  // Timestamps (NEW)
  int64 timestamp_us = 17;
  int64 duration_ms = 18;
}

message ICECandidateInfo {
  string candidate_id = 1;
  string ip = 2;
  int32 port = 3;
  string protocol = 4;
  string type = 5;
  int32 priority = 6;
}

message ICECandidatePairInfo {
  ICECandidateInfo local_candidate = 1;
  ICECandidateInfo remote_candidate = 2;
  bool nominated = 3;
  int64 bytes_sent = 4;
  int64 bytes_received = 5;
  int32 rtt_ms = 6;
}

message AudioCodecInfo {
  string name = 1;
  int32 payload_type = 2;
  int32 clockrate = 3;
  int32 channels = 4;
  map<string, string> parameters = 5;
}

// Audio device enumeration messages (unchanged)

message AudioDevice {
  string name = 1;
  string description = 2;
  string device_class = 3;  // "Audio/Source", "Audio/Sink", or "Video/Source"
}

message ListAudioDevicesResponse {
  repeated AudioDevice devices = 1;
}

message SetMuteRequest {
  string session_id = 1;
  bool muted = 2;
}
```

---

## Migration Strategy

### Phase 1: Backward-Compatible Changes

**Add new fields without breaking existing**:
1. Add `peer_connection_state`, `ice_gathering_state` to `ConnectionStateEvent`
2. Add `type`, `debug_info`, `code`, `retryable` to `ErrorEvent`
3. Add quality metrics to `GetStatsResponse`

**Python migration**:
```python
# OLD:
state = event.connection_state.state

# NEW (backward compatible):
ice_state = event.connection_state.ice_connection_state or event.connection_state.state
```

### Phase 2: Deprecate Old Fields

Mark old fields as deprecated:
```protobuf
message ConnectionStateEvent {
  State state = 1 [deprecated = true];  // Use ice_connection_state instead
  ICEConnectionState ice_connection_state = 2;
  // ...
}
```

### Phase 3: Remove Deprecated Fields

After all clients updated, remove deprecated fields (next major version).

---

## Testing Strategy

### Proto Validation

```bash
# Validate proto syntax
protoc --cpp_out=/tmp drunk_call_service/proto/call.proto

# Generate Python bindings
python -m grpc_tools.protoc -I drunk_call_service/proto \
    --python_out=drunk_call_hook/proto \
    --grpc_python_out=drunk_call_hook/proto \
    drunk_call_service/proto/call.proto
```

### Integration Tests

1. **Test backward compatibility**: Old Python code with new proto
2. **Test new fields**: Verify new error types, stats
3. **Test round-trip**: C++ → Python → C++ for all messages

---

## Summary of Changes

| Message | Changes | Breaking? |
|---------|---------|-----------|
| `ConnectionStateEvent` | Add `peer_connection_state`, `ice_gathering_state`; rename `state` → `ice_connection_state` | **YES** (field rename) |
| `ErrorEvent` | Add `type`, `debug_info`, `code`, `retryable` | NO (additive) |
| `GetStatsResponse` | Add quality metrics, structured candidates, codec info, enums for states | NO (additive) |
| `CreateSessionRequest` | Add `camera_device`, `video_settings` | NO (optional fields) |
| `AudioDevice` | Extend `device_class` to include "Video/Source" | NO (value extension) |

**Breaking changes**: 1 (ConnectionStateEvent field rename)

**Migration effort**: LOW (Python needs to use new field name)

---

**Next Steps**:
1. Review with user
2. Update call.proto
3. Regenerate Python bindings
4. Update Python code to use new fields
5. Implement new fields in C++ service
6. Test with Conversations.im + Dino

---

**Last Updated**: 2026-03-02
**Status**: Ready for review
