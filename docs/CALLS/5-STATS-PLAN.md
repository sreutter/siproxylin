# Step 5: Statistics, Monitoring & Device Management

**Status**: Planning
**Depends on**: 1-4 (all previous steps)
**Leads to**: Production deployment

---

## Goal

Implement call statistics (GetStats RPC), audio device enumeration (ListAudioDevices), mute control (SetMute), connection monitoring, and quality metrics.

**Success**: Python can query call quality metrics, enumerate/select audio devices, mute microphone, monitor bandwidth and connection type.

---

## WebRTC Statistics

### Overview

Webrtcbin provides comprehensive stats via `get-stats` action, following W3C WebRTC Stats API.

**Stats categories**:
- Codec: audio codec in use, bitrate, packet loss
- Transport: ICE candidate pairs, connection type (P2P/relay), local/remote IPs
- Media: bytes sent/received, packets lost, jitter
- Connection: RTT (round-trip time), bandwidth estimate

**Reference**: https://www.w3.org/TR/webrtc-stats/

---

## Task 5.1: Implement GetStats RPC

**What**: Query webrtcbin for statistics

**Implementation**:
```c++
Status GetStats(ServerContext* context,
               const GetStatsRequest* request,
               GetStatsResponse* response) {
    CallSession *session = find_session(request->session_id());
    if (!session) {
        return Status(StatusCode::NOT_FOUND, "Session not found");
    }

    // Create promise for async stats retrieval
    std::mutex stats_mutex;
    std::condition_variable stats_ready;
    bool done = false;
    GstStructure *stats_result = nullptr;

    auto stats_callback = [](GstPromise *promise, gpointer user_data) {
        auto *data = (StatsCallbackData*)user_data;

        const GstStructure *stats = gst_promise_get_reply(promise);
        data->stats = gst_structure_copy(stats);

        std::lock_guard<std::mutex> lock(data->mutex);
        data->done = true;
        data->cv.notify_one();

        gst_promise_unref(promise);
    };

    StatsCallbackData cb_data{stats_mutex, stats_ready, done, stats_result};

    GstPromise *promise = gst_promise_new_with_change_func(
        stats_callback, &cb_data, nullptr);
    g_signal_emit_by_name(session->webrtc, "get-stats", nullptr, promise);

    // Wait for stats
    std::unique_lock<std::mutex> lock(stats_mutex);
    stats_ready.wait_for(lock, std::chrono::seconds(5),
        [&done]() { return done; });

    if (!stats_result) {
        return Status(StatusCode::INTERNAL, "Stats retrieval failed");
    }

    // Parse stats structure
    parse_webrtc_stats(stats_result, response);

    gst_structure_free(stats_result);

    return Status::OK;
}
```

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 372-384

---

### Task 5.2: Parse WebRTC Stats Structure

**What**: Extract relevant stats from GstStructure

**Implementation**:
```c++
void parse_webrtc_stats(GstStructure *stats, GetStatsResponse *response) {
    // Iterate all stats entries
    gst_structure_foreach(stats, parse_stat_entry, response);
}

gboolean parse_stat_entry(GQuark field_id, const GValue *value,
                         gpointer user_data) {
    GetStatsResponse *response = (GetStatsResponse*)user_data;

    if (!GST_VALUE_HOLDS_STRUCTURE(value)) {
        return TRUE;  // Continue iteration
    }

    const GstStructure *stat = gst_value_get_structure(value);
    const gchar *type = gst_structure_get_string(stat, "type");

    if (g_strcmp0(type, "transport") == 0) {
        parse_transport_stats(stat, response);
    } else if (g_strcmp0(type, "candidate-pair") == 0) {
        parse_candidate_pair_stats(stat, response);
    } else if (g_strcmp0(type, "inbound-rtp") == 0) {
        parse_inbound_rtp_stats(stat, response);
    } else if (g_strcmp0(type, "outbound-rtp") == 0) {
        parse_outbound_rtp_stats(stat, response);
    }

    return TRUE;  // Continue
}
```

**Reference**: WebRTC Stats spec for structure format

---

### Task 5.3: Extract Transport Stats

**What**: ICE connection info, candidate pairs, connection type

**Implementation**:
```c++
void parse_transport_stats(const GstStructure *stat,
                          GetStatsResponse *response) {
    // ICE state
    const gchar *ice_state = gst_structure_get_string(stat, "ice-connection-state");
    response->set_ice_connection_state(ice_state);

    // DTLS state
    const gchar *dtls_state = gst_structure_get_string(stat, "dtls-state");

    // Selected candidate pair ID
    const gchar *selected_pair = gst_structure_get_string(stat,
        "selected-candidate-pair-id");
    // Use this to find the actual candidate pair stats
}

void parse_candidate_pair_stats(const GstStructure *stat,
                               GetStatsResponse *response) {
    // Check if this is the selected pair
    gboolean selected = FALSE;
    gst_structure_get_boolean(stat, "selected", &selected);

    if (!selected) {
        return;  // Only care about active pair
    }

    // Local candidate ID
    const gchar *local_id = gst_structure_get_string(stat, "local-candidate-id");
    // Remote candidate ID
    const gchar *remote_id = gst_structure_get_string(stat, "remote-candidate-id");

    // Bytes sent/received
    guint64 bytes_sent = 0, bytes_received = 0;
    gst_structure_get_uint64(stat, "bytes-sent", &bytes_sent);
    gst_structure_get_uint64(stat, "bytes-received", &bytes_received);

    response->set_bytes_sent(bytes_sent);
    response->set_bytes_received(bytes_received);

    // RTT (round-trip time) in milliseconds
    gdouble rtt = 0.0;
    gst_structure_get_double(stat, "round-trip-time", &rtt);
    // rtt is in seconds, convert to ms
    response->set_rtt_ms((int)(rtt * 1000));
}
```

**Test**:
```bash
# During active call:
response = stub.GetStats(GetStatsRequest(session_id="test-1"))
print(f"Bytes sent: {response.bytes_sent}")
print(f"Bytes received: {response.bytes_received}")
print(f"RTT: {response.rtt_ms}ms")
print(f"Connection type: {response.connection_type}")
```

**Expected values**:
- bytes_sent/received: increasing (proportional to call duration)
- RTT: 10-100ms for P2P, 50-200ms for relay
- connection_type: "host" (P2P), "relay" (TURN)

---

### Task 5.4: Extract RTP Media Stats

**What**: Packet loss, jitter, codec info

**Implementation**:
```c++
void parse_inbound_rtp_stats(const GstStructure *stat,
                            GetStatsResponse *response) {
    // Packets received
    guint64 packets_received = 0;
    gst_structure_get_uint64(stat, "packets-received", &packets_received);

    // Packets lost
    guint64 packets_lost = 0;
    gst_structure_get_uint64(stat, "packets-lost", &packets_lost);

    // Calculate packet loss percentage
    if (packets_received > 0) {
        double loss_pct = (double)packets_lost /
            (packets_received + packets_lost) * 100.0;
        response->set_packet_loss_pct(loss_pct);
    }

    // Jitter (in seconds)
    gdouble jitter = 0.0;
    gst_structure_get_double(stat, "jitter", &jitter);
    response->set_jitter_ms((int)(jitter * 1000));

    // Codec
    const gchar *codec = gst_structure_get_string(stat, "codec-id");
    // Look up codec details from another stat entry
}

void parse_outbound_rtp_stats(const GstStructure *stat,
                             GetStatsResponse *response) {
    // Packets sent
    guint64 packets_sent = 0;
    gst_structure_get_uint64(stat, "packets-sent", &packets_sent);

    // Bytes sent (for bitrate calculation)
    guint64 bytes_sent = 0;
    gst_structure_get_uint64(stat, "bytes-sent", &bytes_sent);
}
```

**Quality metrics**:
- **Packet loss < 1%**: Excellent
- **Packet loss 1-5%**: Good (Opus has FEC)
- **Packet loss > 5%**: Poor (noticeable quality degradation)
- **Jitter < 30ms**: Good
- **Jitter > 50ms**: May cause audio glitches

**Test**:
```bash
response = stub.GetStats(GetStatsRequest(session_id="test-1"))
print(f"Packet loss: {response.packet_loss_pct:.2f}%")
print(f"Jitter: {response.jitter_ms}ms")

# Quality assessment:
if response.packet_loss_pct < 1.0 and response.jitter_ms < 30:
    print("Call quality: EXCELLENT")
elif response.packet_loss_pct < 5.0 and response.jitter_ms < 50:
    print("Call quality: GOOD")
else:
    print("Call quality: POOR")
```

---

### Task 5.5: Calculate Bandwidth

**What**: Estimate current bandwidth usage

**Implementation**:
```c++
void update_bandwidth_estimate(CallSession *session, GetStatsResponse *response) {
    // Sample bytes_sent at 2-second intervals
    static std::map<std::string, BandwidthTracker> trackers;

    auto &tracker = trackers[session->session_id];

    auto now = std::chrono::steady_clock::now();
    auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
        now - tracker.last_sample_time).count();

    if (elapsed >= 2) {
        uint64_t bytes_diff = response->bytes_sent() - tracker.last_bytes_sent;
        double kbps = (bytes_diff * 8.0) / (elapsed * 1000.0);

        response->set_bandwidth_kbps((int64_t)kbps);

        tracker.last_bytes_sent = response->bytes_sent();
        tracker.last_sample_time = now;
    } else {
        response->set_bandwidth_kbps(tracker.last_bandwidth_kbps);
    }
}
```

**Expected bandwidth** (Opus audio):
- **Low quality**: 16-24 kbps
- **Standard**: 24-32 kbps
- **High quality**: 32-48 kbps
- **Plus overhead**: +10-20% for RTP/UDP/IP headers

**Test**:
```bash
# Poll stats every 2 seconds:
for i in range(10):
    response = stub.GetStats(GetStatsRequest(session_id="test-1"))
    print(f"Bandwidth: {response.bandwidth_kbps} kbps")
    time.sleep(2)

# Should stabilize around 30-40 kbps
```

---

### Task 5.6: Determine Connection Type

**What**: Classify connection as P2P (direct/reflexive) or TURN relay

**Implementation**:
```c++
void determine_connection_type(const GstStructure *local_candidate,
                              const GstStructure *remote_candidate,
                              GetStatsResponse *response) {
    const gchar *local_type = gst_structure_get_string(local_candidate, "candidate-type");
    const gchar *remote_type = gst_structure_get_string(remote_candidate, "candidate-type");

    std::string conn_type;

    if (g_strcmp0(local_type, "host") == 0 && g_strcmp0(remote_type, "host") == 0) {
        conn_type = "P2P (direct)";
    } else if (g_strcmp0(local_type, "srflx") == 0 || g_strcmp0(remote_type, "srflx") == 0) {
        conn_type = "P2P (reflexive)";
    } else if (g_strcmp0(local_type, "relay") == 0 || g_strcmp0(remote_type, "relay") == 0) {
        conn_type = "TURN relay";
    } else {
        conn_type = "Unknown";
    }

    response->set_connection_type(conn_type);

    // Extract IP addresses (for local/remote candidates lists)
    const gchar *local_ip = gst_structure_get_string(local_candidate, "address");
    const gchar *remote_ip = gst_structure_get_string(remote_candidate, "address");

    response->add_local_candidates(local_ip ? local_ip : "unknown");
    response->add_remote_candidates(remote_ip ? remote_ip : "unknown");
}
```

**Test**:
```bash
response = stub.GetStats(GetStatsRequest(session_id="test-1"))
print(f"Connection type: {response.connection_type}")
print(f"Local IP: {response.local_candidates[0]}")
print(f"Remote IP: {response.remote_candidates[0]}")

# Verify privacy:
# - relay_only=true → should be "TURN relay"
# - relay_only=false → may be "P2P (direct)" or "P2P (reflexive)"
```

---

## Audio Device Management

### Task 5.7: Implement ListAudioDevices RPC

**What**: Enumerate available microphones and speakers

**PulseAudio approach** (Linux):
```c++
Status ListAudioDevices(ServerContext* context,
                       const Empty* request,
                       ListAudioDevicesResponse* response) {
    // Use pactl to list devices
    FILE *fp = popen("pactl list sources short", "r");
    if (!fp) {
        return Status(StatusCode::INTERNAL, "Failed to enumerate sources");
    }

    char line[1024];
    while (fgets(line, sizeof(line), fp)) {
        // Parse line: "1    alsa_input.pci-...    module-alsa-card.c    ..."
        char *name = strtok(line, "\t");
        char *device = strtok(NULL, "\t");

        if (device) {
            auto *dev = response->add_devices();
            dev->set_name(device);
            dev->set_device_class("Audio/Source");

            // Get description from pactl list sources (long form)
            // Or use placeholder
            dev->set_description(device);
        }
    }
    pclose(fp);

    // Repeat for sinks (speakers)
    fp = popen("pactl list sinks short", "r");
    // ... similar parsing ...
    pclose(fp);

    return Status::OK;
}
```

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 390-394

**Better approach**: Use PulseAudio C API (libpulse)
```c++
#include <pulse/pulseaudio.h>

// Requires async API or threaded mainloop
// See: https://freedesktop.org/software/pulseaudio/doxygen/
```

**Test**:
```bash
# Python:
response = stub.ListAudioDevices(Empty())
for device in response.devices:
    print(f"{device.device_class}: {device.name}")
    print(f"  Description: {device.description}")

# Expected output:
# Audio/Source: alsa_input.pci-0000_05_00.6.analog-stereo
#   Description: Family 17h HD Audio Controller Analog Stereo
# Audio/Sink: alsa_output.pci-0000_05_00.6.analog-stereo
#   Description: Family 17h HD Audio Controller Analog Stereo
```

**Failure modes**:
- PulseAudio not running → empty list or error
- Permission denied → check user in audio group

---

### Task 5.8: Implement SetMute RPC

**What**: Mute/unmute microphone

**Implementation**:
```c++
Status SetMute(ServerContext* context,
              const SetMuteRequest* request,
              Empty* response) {
    CallSession *session = find_session(request->session_id());
    if (!session) {
        return Status(StatusCode::NOT_FOUND, "Session not found");
    }

    // Set mute on audio source
    if (session->audio_src) {
        g_object_set(session->audio_src, "mute", request->muted(), NULL);
    }

    session->is_muted = request->muted();

    return Status::OK;
}
```

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 398-401

**Test**:
```bash
# Start call, verify audio
stub.SetMute(SetMuteRequest(session_id="test-1", muted=True))
# Peer should hear silence

stub.SetMute(SetMuteRequest(session_id="test-1", muted=False))
# Peer should hear audio again
```

**UI feedback**: Python should show mute icon when muted

---

## Connection Quality Monitoring

### Task 5.9: Periodic Stats Polling

**What**: Python polls GetStats regularly to monitor quality

**Python implementation**:
```python
import threading
import time

def monitor_call_quality(session_id):
    while call_active:
        response = stub.GetStats(GetStatsRequest(session_id=session_id))

        # Check quality
        if response.packet_loss_pct > 5.0:
            show_warning("Poor call quality: high packet loss")
        elif response.rtt_ms > 300:
            show_warning("Poor call quality: high latency")

        # Update UI with stats
        update_stats_ui(response)

        time.sleep(5)  # Poll every 5 seconds

# Start monitoring in background
threading.Thread(target=monitor_call_quality, args=("session-1",), daemon=True).start()
```

**UI display**:
- Connection type icon (P2P, relay)
- Signal strength bars (based on packet loss)
- Bandwidth graph
- Latency indicator

---

### Task 5.10: Event-Based Quality Alerts

**What**: Stream quality degradation events

**Enhancement to proto** (optional):
```protobuf
message QualityEvent {
  enum Level {
    EXCELLENT = 0;
    GOOD = 1;
    FAIR = 2;
    POOR = 3;
  }
  Level quality = 1;
  float packet_loss_pct = 2;
  int32 rtt_ms = 3;
}

// Add to CallEvent oneof:
message CallEvent {
  oneof event {
    ICECandidateEvent ice_candidate = 2;
    ConnectionStateEvent connection_state = 3;
    ErrorEvent error = 4;
    QualityEvent quality = 5;  // NEW
  }
}
```

**Implementation**: Periodically check stats in main loop, stream quality changes

---

## Diagnostic Logging

### Task 5.11: Enable GStreamer Debug Logging

**What**: Allow dynamic log level control

**Environment variables**:
```bash
# Global debug level:
export GST_DEBUG=3  # 0=none, 1=error, 2=warning, 3=info, 4=debug, 5=trace

# Per-category debug:
export GST_DEBUG=webrtcbin:5,nice:5,dtls:4,rtp:3

# Log to file:
export GST_DEBUG_FILE=/tmp/gstreamer.log

# Disable ANSI colors:
export GST_DEBUG_NO_COLOR=1
```

**Service wrapper**: Python can set environment before launching service

**Test**:
```bash
GST_DEBUG=webrtcbin:5,nice:5 ./drunk-call-service 2>&1 | tee /tmp/debug.log
# Generates detailed logs for troubleshooting
```

---

### Task 5.12: Pipeline Visualization

**What**: Generate pipeline graphs for debugging

**Implementation**:
```c++
// In create_audio_pipeline(), after elements linked:
GST_DEBUG_BIN_TO_DOT_FILE(GST_BIN(session->pipeline),
    GST_DEBUG_GRAPH_SHOW_ALL, "pipeline-created");

// After ICE connected:
GST_DEBUG_BIN_TO_DOT_FILE(GST_BIN(session->pipeline),
    GST_DEBUG_GRAPH_SHOW_ALL, "pipeline-connected");
```

**Usage**:
```bash
export GST_DEBUG_DUMP_DOT_DIR=/tmp
./drunk-call-service

# After call established:
ls /tmp/*.dot
# pipeline-created.dot, pipeline-connected.dot

# Convert to image:
dot -Tpng /tmp/pipeline-connected.dot -o /tmp/pipeline.png
```

**Visualization shows**:
- All elements and pads
- Caps negotiation
- Element states
- Buffer flow

---

## Performance Metrics

### Task 5.13: Service-Level Metrics

**What**: Track service health metrics

**Metrics to track**:
- Active sessions count
- Total sessions created (lifetime)
- Average session duration
- Failed sessions (and failure reasons)
- gRPC call latencies
- Memory usage

**Implementation**:
```c++
struct ServiceMetrics {
    std::atomic<size_t> active_sessions{0};
    std::atomic<size_t> total_sessions{0};
    std::atomic<size_t> failed_sessions{0};

    std::mutex durations_mutex;
    std::vector<std::chrono::seconds> session_durations;

    void record_session_start() {
        active_sessions++;
        total_sessions++;
    }

    void record_session_end(std::chrono::seconds duration) {
        active_sessions--;
        std::lock_guard<std::mutex> lock(durations_mutex);
        session_durations.push_back(duration);
    }
};
```

**Expose via RPC** (optional):
```protobuf
rpc GetServiceStats(Empty) returns (ServiceStatsResponse);

message ServiceStatsResponse {
  int32 active_sessions = 1;
  int64 total_sessions = 2;
  int64 failed_sessions = 3;
  double avg_session_duration_sec = 4;
}
```

---

## Milestone: Stats & Monitoring Complete

**Definition of done**:
- [x] GetStats returns comprehensive call quality metrics
- [x] ListAudioDevices enumerates available devices
- [x] SetMute controls microphone
- [x] Connection type correctly identified
- [x] Bandwidth calculated accurately
- [x] Python can monitor call quality in real-time
- [x] Debug logging and visualization available

**Integration test**:
```bash
# Full call with monitoring:
# 1. ListAudioDevices → select devices
# 2. CreateSession with selected devices
# 3. Establish call (steps 2-3 from previous plans)
# 4. Poll GetStats every 5 seconds:
#    - Verify bytes_sent/received increasing
#    - Verify packet_loss < 5%
#    - Verify RTT < 200ms
#    - Verify connection_type correct
# 5. SetMute(true) → verify peer hears silence
# 6. SetMute(false) → verify audio resumes
# 7. EndSession
```

---

## Production Readiness

### Task 5.14: Error Recovery

**What**: Handle transient failures gracefully

**Scenarios**:
- STUN timeout → retry with backup STUN server
- TURN auth failure → log error, fall back to P2P if allowed
- Audio device unplugged → detect and notify user
- Network change → ICE handles automatically (see 3-ICE-PLAN.md task 3.11)

**Implementation**: Add retry logic, health checks

---

### Task 5.15: Resource Cleanup on Crash

**What**: Ensure resources freed even if service crashes

**Signal handlers**:
```c++
#include <csignal>

void signal_handler(int signum) {
    spdlog::warn("Received signal {}, shutting down gracefully", signum);

    // Stop all sessions
    // ... call service->Shutdown()

    exit(signum);
}

int main() {
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    // ... start service ...
}
```

**Test**:
```bash
# Start service, create session
# Send SIGTERM:
kill -TERM <pid>

# Logs should show:
# "Received signal 15, shutting down gracefully"
# "Pipeline stopped"
# Clean exit
```

---

## Next Steps (Beyond This Plan)

1. **Windows/macOS ports**: Adapt audio device enumeration for other platforms
2. **Video support**: Extend to video calls (add VP8/VP9 codecs, video sources)
3. **Screen sharing**: Add application/screen capture sources
4. **RTCP feedback**: Fine-tune codec parameters based on network conditions
5. **SFU/MCU**: Multi-party calls (requires different architecture)

---

**Status Document**: Create `5-STATS-STATUS.md` when implementing to track:
- Stats accuracy testing (compare with browser WebRTC stats)
- Device enumeration results on different systems
- Quality metric thresholds tuned for Opus audio
- Performance benchmarks (stats query latency, memory usage)

---

## STATUS

**Current**: Not started (depends on 1-4 completion)

**Done**: []

**Next**: Task 5.1 - Implement GetStats RPC

**Blockers**: None

**Last updated**: 2026-03-02

---

**Last Updated**: 2026-03-02
