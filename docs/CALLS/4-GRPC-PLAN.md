# Step 4: gRPC Service Integration & Threading

**Status**: Planning
**Depends on**: 1-PIPELINE-PLAN.md, 2-SDP-PLAN.md, 3-ICE-PLAN.md
**Leads to**: 5-STATS-PLAN.md (final step)

---

## Goal

Integrate GStreamer WebRTC implementation with gRPC service, handle threading correctly, manage session lifecycle, implement service startup/shutdown.

**Success**: Python can create/manage multiple concurrent sessions, gRPC calls don't block, events stream correctly, no deadlocks or race conditions.

---

## Threading Architecture

### Thread Model

**Three thread domains**:

1. **GLib Main Loop Thread** (single, long-lived)
   - Runs `g_main_loop_run()`
   - All GStreamer signals fire here
   - Handles GstPromise callbacks
   - Must NOT block

2. **gRPC Thread Pool** (multiple threads, managed by gRPC)
   - Handles incoming gRPC requests (CreateSession, CreateOffer, etc.)
   - Can block waiting for results
   - Must be thread-safe when accessing sessions

3. **Event Streaming Threads** (one per session)
   - Dedicated thread for `StreamEvents` per session
   - Polls event queue
   - Writes to gRPC stream

**Critical rule**: GStreamer objects (GstElement, etc.) can ONLY be accessed from main loop thread or with proper locking.

**Reference**: `docs/CALLS/PLAN.md` (Threading Model section)

---

## Task 4.1: Service Initialization

**What**: Start gRPC server, initialize GStreamer, create main loop

**Implementation** (`src/main.cpp`):
```c++
int main(int argc, char **argv) {
    // Initialize GStreamer
    gst_init(&argc, &argv);

    // Check required plugins (from 1-PIPELINE-PLAN.md task 1.2)
    if (!check_required_plugins()) {
        return EXIT_FAILURE;
    }

    // Create and start GLib main loop thread
    GMainLoop *main_loop = g_main_loop_new(NULL, FALSE);
    std::thread main_loop_thread([main_loop]() {
        g_main_loop_run(main_loop);
    });

    // Create gRPC service
    CallServiceImpl service;
    grpc::ServerBuilder builder;
    builder.AddListeningPort("127.0.0.1:50051",
        grpc::InsecureServerCredentials());
    builder.RegisterService(&service);
    std::unique_ptr<grpc::Server> server(builder.BuildAndStart());

    std::cout << "Call service listening on 127.0.0.1:50051" << std::endl;

    // Wait for shutdown signal
    server->Wait();

    // Cleanup
    g_main_loop_quit(main_loop);
    main_loop_thread.join();
    g_main_loop_unref(main_loop);
    gst_deinit();

    return EXIT_SUCCESS;
}
```

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 416-431

**Test**:
```bash
./drunk-call-service
# Expected output:
# "GStreamer 1.22.x initialized"
# "Call service listening on 127.0.0.1:50051"
# (no errors, process stays running)

# In another terminal:
grpcurl -plaintext localhost:50051 list
# Should show: call.CallService
```

---

## Task 4.2: Session Management

**What**: Store and manage multiple concurrent sessions

**Data structure**:
```c++
class CallServiceImpl : public CallService::Service {
private:
    std::map<std::string, std::unique_ptr<CallSession>> sessions_;
    std::mutex sessions_mutex_;

public:
    CallSession* find_session(const std::string &session_id) {
        std::lock_guard<std::mutex> lock(sessions_mutex_);
        auto it = sessions_.find(session_id);
        if (it == sessions_.end()) {
            return nullptr;
        }
        return it->second.get();
    }

    void add_session(const std::string &session_id,
                    std::unique_ptr<CallSession> session) {
        std::lock_guard<std::mutex> lock(sessions_mutex_);
        sessions_[session_id] = std::move(session);
    }

    void remove_session(const std::string &session_id) {
        std::lock_guard<std::mutex> lock(sessions_mutex_);
        sessions_.erase(session_id);
    }
};
```

**Thread safety**: Always hold `sessions_mutex_` when accessing map

**Test**:
```bash
# Create 3 sessions concurrently (Python):
import concurrent.futures
def create_session(n):
    stub.CreateSession(CreateSessionRequest(session_id=f"session-{n}"))

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    executor.map(create_session, [1, 2, 3])

# Verify: 3 sessions created, no crashes
```

---

## Task 4.3: Implement CreateSession RPC

**What**: Create new call session, build pipeline, configure properties

**Implementation**:
```c++
Status CreateSession(ServerContext* context,
                    const CreateSessionRequest* request,
                    CreateSessionResponse* response) {
    try {
        // Create session object
        auto session = std::make_unique<CallSession>();
        session->session_id = request->session_id();
        session->peer_jid = request->peer_jid();
        session->relay_only = request->relay_only();
        session->stun_server = request->turn_server().empty() ?
            "stun://stun.l.google.com:19302" : "";
        session->turn_server = request->turn_server();
        session->microphone_device = request->microphone_device();
        session->speakers_device = request->speakers_device();

        // Create pipeline (from 1-PIPELINE-PLAN.md)
        create_audio_pipeline(session.get());

        // Configure TURN/STUN (from 1-PIPELINE-PLAN.md task 1.6)
        configure_turn_stun(session.get());

        // Set pipeline to PLAYING
        GstStateChangeReturn ret =
            gst_element_set_state(session->pipeline, GST_STATE_PLAYING);
        if (ret == GST_STATE_CHANGE_FAILURE) {
            response->set_success(false);
            response->set_error("Failed to start pipeline");
            return Status::OK;
        }

        // Store session
        add_session(request->session_id(), std::move(session));

        response->set_success(true);
        return Status::OK;

    } catch (const std::exception &e) {
        response->set_success(false);
        response->set_error(e.what());
        return Status::OK;
    }
}
```

**Error handling**: Catch all exceptions, return structured error

**Test**:
```bash
# Python:
response = stub.CreateSession(CreateSessionRequest(
    session_id="test-1",
    peer_jid="peer@example.com",
    relay_only=True,
    turn_server="turn://user:pass@turn.example.com:3478"
))
assert response.success == True

# Service logs:
# - "Created session: test-1"
# - "Pipeline PLAYING"
```

---

## Task 4.4: Implement CreateOffer RPC

**What**: Generate SDP offer, block until ready

**Implementation**:
```c++
Status CreateOffer(ServerContext* context,
                  const CreateOfferRequest* request,
                  SDPResponse* response) {
    CallSession *session = find_session(request->session_id());
    if (!session) {
        response->set_error("Session not found");
        return Status::OK;
    }

    session->is_outgoing = true;

    // on-negotiation-needed signal should fire automatically
    // Wait for offer to be created (signaled by promise callback)
    std::unique_lock<std::mutex> lock(session->sdp_mutex);
    bool timeout = !session->offer_ready.wait_for(lock,
        std::chrono::seconds(10));

    if (timeout) {
        response->set_error("Timeout waiting for offer");
        return Status::OK;
    }

    response->set_sdp(session->local_sdp);
    return Status::OK;
}
```

**Reference**: See 2-SDP-PLAN.md task 2.3

**Thread coordination**:
- gRPC thread: blocks on condition variable
- Main loop thread (promise callback): signals condition variable

**Test**:
```bash
# Python:
sdp_response = stub.CreateOffer(CreateOfferRequest(session_id="test-1"))
assert len(sdp_response.sdp) > 100  # Valid SDP
assert "m=audio" in sdp_response.sdp
assert "a=fingerprint" in sdp_response.sdp
```

**Timeout**: 10 seconds (should normally complete in <1 second)

---

## Task 4.5: Implement CreateAnswer RPC

**What**: Set remote offer, generate answer

**Implementation**:
```c++
Status CreateAnswer(ServerContext* context,
                   const CreateAnswerRequest* request,
                   SDPResponse* response) {
    CallSession *session = find_session(request->session_id());
    if (!session) {
        response->set_error("Session not found");
        return Status::OK;
    }

    session->is_outgoing = false;

    // Parse and set remote SDP (from 2-SDP-PLAN.md task 2.4)
    GstSDPMessage *sdp_msg;
    gst_sdp_message_new(&sdp_msg);
    GstSDPResult result = gst_sdp_message_parse_buffer(
        (guint8*)request->remote_sdp().c_str(),
        request->remote_sdp().size(),
        sdp_msg);

    if (result != GST_SDP_OK) {
        response->set_error("Invalid SDP");
        gst_sdp_message_free(sdp_msg);
        return Status::OK;
    }

    GstWebRTCSessionDescription *offer =
        gst_webrtc_session_description_new(GST_WEBRTC_SDP_TYPE_OFFER, sdp_msg);

    // Set remote description (triggers promise chain)
    GstPromise *promise = gst_promise_new_with_change_func(
        on_offer_set_for_answer, session, nullptr);
    g_signal_emit_by_name(session->webrtc, "set-remote-description",
        offer, promise);

    gst_webrtc_session_description_free(offer);

    // Wait for answer
    std::unique_lock<std::mutex> lock(session->sdp_mutex);
    bool timeout = !session->answer_ready.wait_for(lock,
        std::chrono::seconds(10));

    if (timeout) {
        response->set_error("Timeout creating answer");
        return Status::OK;
    }

    response->set_sdp(session->local_sdp);
    return Status::OK;
}
```

**Reference**: 2-SDP-PLAN.md tasks 2.4, 2.5

**Test**: Same as CreateOffer, but provide remote offer SDP

---

## Task 4.6: Implement SetRemoteDescription RPC

**What**: Apply remote answer (for outgoing calls)

**Implementation**:
```c++
Status SetRemoteDescription(ServerContext* context,
                           const SetRemoteDescriptionRequest* request,
                           Empty* response) {
    CallSession *session = find_session(request->session_id());
    if (!session) {
        return Status(StatusCode::NOT_FOUND, "Session not found");
    }

    // Parse SDP
    GstSDPMessage *sdp_msg;
    gst_sdp_message_new(&sdp_msg);
    gst_sdp_message_parse_buffer(
        (guint8*)request->remote_sdp().c_str(),
        request->remote_sdp().size(),
        sdp_msg);

    // Determine type
    GstWebRTCSDPType type = (request->sdp_type() == "offer") ?
        GST_WEBRTC_SDP_TYPE_OFFER : GST_WEBRTC_SDP_TYPE_ANSWER;

    GstWebRTCSessionDescription *remote_desc =
        gst_webrtc_session_description_new(type, sdp_msg);

    // Set remote description
    GstPromise *promise = gst_promise_new();
    g_signal_emit_by_name(session->webrtc, "set-remote-description",
        remote_desc, promise);
    gst_promise_interrupt(promise);
    gst_promise_unref(promise);

    gst_webrtc_session_description_free(remote_desc);

    return Status::OK;
}
```

**Reference**: 2-SDP-PLAN.md task 2.6

---

## Task 4.7: Implement AddICECandidate RPC

**What**: Apply remote ICE candidates

**Implementation**:
```c++
Status AddICECandidate(ServerContext* context,
                      const AddICECandidateRequest* request,
                      Empty* response) {
    CallSession *session = find_session(request->session_id());
    if (!session) {
        return Status(StatusCode::NOT_FOUND, "Session not found");
    }

    // Add candidate to webrtcbin
    g_signal_emit_by_name(session->webrtc, "add-ice-candidate",
        request->sdp_mline_index(), request->candidate().c_str());

    return Status::OK;
}
```

**Reference**: 3-ICE-PLAN.md task 3.4

**Thread safety**: `g_signal_emit_by_name` is thread-safe

---

## Task 4.8: Implement StreamEvents RPC

**What**: Stream ICE candidates and state changes to Python

**Challenge**: Long-lived streaming RPC, must handle backpressure

**Implementation**:
```c++
Status StreamEvents(ServerContext* context,
                   const StreamEventsRequest* request,
                   ServerWriter<CallEvent>* writer) {
    CallSession *session = find_session(request->session_id());
    if (!session) {
        return Status(StatusCode::NOT_FOUND, "Session not found");
    }

    // Store writer in session for signal handlers to use
    {
        std::lock_guard<std::mutex> lock(session->event_mutex);
        session->event_writer = writer;
    }

    // Keep connection open until session ends
    while (!context->IsCancelled() && session->pipeline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    // Clear writer
    {
        std::lock_guard<std::mutex> lock(session->event_mutex);
        session->event_writer = nullptr;
    }

    return Status::OK;
}
```

**Signal handlers use writer**:
```c++
void on_ice_candidate(...) {
    CallSession *session = (CallSession*)user_data;

    CallEvent event;
    event.set_session_id(session->session_id);
    auto *ice_event = event.mutable_ice_candidate();
    ice_event->set_candidate(candidate);
    ice_event->set_sdp_mline_index(mlineindex);

    std::lock_guard<std::mutex> lock(session->event_mutex);
    if (session->event_writer) {
        session->event_writer->Write(event);
    }
}
```

**Reference**: 3-ICE-PLAN.md task 3.1, `docs/CALLS/webrtcbin-reference.cpp` lines 276-292

**Test**:
```bash
# Python (async):
for event in stub.StreamEvents(StreamEventsRequest(session_id="test-1")):
    if event.HasField("ice_candidate"):
        print(f"ICE candidate: {event.ice_candidate.candidate}")
    elif event.HasField("connection_state"):
        print(f"State: {event.connection_state.state}")
```

---

## Task 4.9: Implement EndSession RPC

**What**: Stop pipeline, cleanup resources, remove session

**Implementation**:
```c++
Status EndSession(ServerContext* context,
                 const EndSessionRequest* request,
                 Empty* response) {
    CallSession *session = find_session(request->session_id());
    if (!session) {
        return Status(StatusCode::NOT_FOUND, "Session not found");
    }

    // Stop pipeline
    if (session->pipeline) {
        gst_element_set_state(session->pipeline, GST_STATE_NULL);
        gst_object_unref(session->pipeline);
        session->pipeline = nullptr;
    }

    // Remove from map (destructor cleans up)
    remove_session(request->session_id());

    return Status::OK;
}
```

**Reference**: `docs/CALLS/webrtcbin-reference.cpp` lines 436-445

**Test**:
```bash
# After EndSession:
# - StreamEvents stream should close
# - Pipeline stopped (check logs)
# - No memory leaks (run with valgrind)
```

---

## Task 4.10: Implement Heartbeat RPC

**What**: Keep service alive, check health

**Implementation**:
```c++
Status Heartbeat(ServerContext* context,
                const Empty* request,
                Empty* response) {
    // Just return OK (service is alive)
    return Status::OK;
}
```

**Purpose**: Python calls every 5 seconds to ensure service is responsive

**Test**:
```bash
# Python:
stub.Heartbeat(Empty())
# Should return immediately, no error
```

---

## Task 4.11: Implement Shutdown RPC

**What**: Graceful service shutdown

**Implementation**:
```c++
Status Shutdown(ServerContext* context,
               const Empty* request,
               Empty* response) {
    // End all sessions
    {
        std::lock_guard<std::mutex> lock(sessions_mutex_);
        for (auto &pair : sessions_) {
            if (pair.second->pipeline) {
                gst_element_set_state(pair.second->pipeline, GST_STATE_NULL);
            }
        }
        sessions_.clear();
    }

    // Trigger server shutdown
    // (Implementation depends on how server reference is stored)
    // server_->Shutdown();

    return Status::OK;
}
```

**Test**:
```bash
# Python:
stub.Shutdown(Empty())
# Service should exit cleanly
```

---

## Session Lifecycle Summary

**Full flow**:
```
Python                          C++ Service                     GStreamer
------                          -----------                     ---------
CreateSession      →            create pipeline                 → PLAYING
                                start main loop thread

CreateOffer/       →            wait on condition var
CreateAnswer
                                                                → negotiation-needed signal
                                ← promise callback fires        ← offer/answer created
                                notify condition var
                   ← return SDP

StreamEvents       →            store writer pointer
                                loop until cancelled
                                                                → on-ice-candidate signal
                                ← write to stream               ← candidates generated
                   ← ICE events

AddICECandidate    →            add to webrtcbin                → ICE checks
                                                                → ICE connected

SetRemoteDescription →          set remote SDP                  → DTLS handshake
                                                                → media flows

EndSession         →            stop pipeline                   → NULL state
                                destroy session
```

---

## Error Handling Strategy

### Task 4.12: Structured Error Returns

**What**: Always return gRPC Status::OK, use response fields for errors

**Pattern**:
```c++
// For RPCs with response message:
Status CreateSession(..., CreateSessionResponse* response) {
    try {
        // ... operation ...
        response->set_success(true);
        return Status::OK;
    } catch (const std::exception &e) {
        response->set_success(false);
        response->set_error(e.what());
        return Status::OK;  // gRPC transport succeeded
    }
}

// For RPCs with Empty response:
Status AddICECandidate(..., Empty* response) {
    try {
        // ... operation ...
        return Status::OK;
    } catch (const std::exception &e) {
        return Status(StatusCode::INTERNAL, e.what());
    }
}
```

**Rationale**: Python can check `response.success` instead of catching gRPC exceptions

---

## Resource Limits

### Task 4.13: Prevent Resource Exhaustion

**What**: Limit concurrent sessions, reject if over limit

**Implementation**:
```c++
const size_t MAX_SESSIONS = 10;

Status CreateSession(...) {
    {
        std::lock_guard<std::mutex> lock(sessions_mutex_);
        if (sessions_.size() >= MAX_SESSIONS) {
            response->set_success(false);
            response->set_error("Maximum concurrent sessions reached");
            return Status::OK;
        }
    }
    // ... proceed with creation ...
}
```

**Rationale**: Prevent DoS by creating unlimited sessions

**Test**:
```bash
# Try creating 11 sessions:
for i in range(15):
    response = stub.CreateSession(CreateSessionRequest(session_id=f"s-{i}"))
    if i < 10:
        assert response.success
    else:
        assert not response.success
        assert "Maximum concurrent" in response.error
```

---

## Logging Strategy

### Task 4.14: Structured Logging

**What**: Log all gRPC calls and GStreamer events

**Implementation**:
```c++
#include <spdlog/spdlog.h>

// In each RPC handler:
Status CreateSession(...) {
    spdlog::info("CreateSession: session_id={}, peer_jid={}",
        request->session_id(), request->peer_jid());

    // ... operation ...

    if (response->success()) {
        spdlog::info("CreateSession: success, session_id={}",
            request->session_id());
    } else {
        spdlog::error("CreateSession: failed, session_id={}, error={}",
            request->session_id(), response->error());
    }

    return Status::OK;
}
```

**Log file**: `~/.siproxylin/logs/drunk-call-service.log`

**Rotation**: 10MB per file, keep 5 files

---

## Milestone: gRPC Service Complete

**Definition of done**:
- [x] Service starts, listens on port 50051
- [x] All RPC methods implemented
- [x] Thread-safe session management
- [x] Event streaming works
- [x] Graceful shutdown
- [x] Error handling comprehensive
- [x] Resource limits enforced
- [x] Logging in place

**Integration test**:
```bash
# Run service:
./drunk-call-service

# Python full call flow:
# 1. CreateSession → success
# 2. StreamEvents → async listening
# 3. CreateOffer → valid SDP
# 4. Receive ICE candidates via StreamEvents
# 5. SetRemoteDescription (answer) → success
# 6. AddICECandidate (multiple) → success
# 7. Wait for CONNECTED state in StreamEvents
# 8. EndSession → success
#
# Service logs:
# - All operations logged
# - No errors
# - Clean shutdown
```

---

## Performance Considerations

### Task 4.15: Async Operations

**What**: Ensure gRPC handlers don't block excessively

**Pattern**: Use condition variables with timeouts

**Timeout values**:
- CreateOffer: 10 seconds
- CreateAnswer: 10 seconds
- ICE gathering: 30 seconds (implicit, GStreamer handles)

**Monitor**: If timeouts occur frequently, investigate GStreamer state

---

### Task 4.16: Memory Management

**What**: Prevent memory leaks

**Tools**:
```bash
# Run with AddressSanitizer:
ASAN_OPTIONS=detect_leaks=1 ./drunk-call-service

# Or valgrind:
valgrind --leak-check=full --show-leak-kinds=all ./drunk-call-service
```

**Common leaks**:
- GStreamer objects not unref'd
- GstPromise not unref'd after use
- SDP messages not freed

---

## Next Step

Once gRPC service is integrated, proceed to **5-STATS-PLAN.md** for statistics and monitoring.

---

**Status Document**: Create `4-GRPC-STATUS.md` when implementing to track:
- RPC call latencies (typical and worst-case)
- Concurrent session testing results
- Thread safety testing (run with ThreadSanitizer)
- Memory leak testing results

---

## STATUS

**Current**: Not started (depends on 1-3 completion)

**Done**: []

**Next**: Task 4.1 - Service initialization

**Blockers**: None

**Last updated**: 2026-03-02

---

**Last Updated**: 2026-03-02
