# Step 4: gRPC Integration Plan

**Status**: Planning
**Date**: 2026-03-02
**Prerequisites**: Steps 1-3 completed (WebRTCSession, devices, stats working at library level)

**See Also**:
- docs/CALLS/PLAN.md - Overall architecture
- docs/CALLS/START.md - Requirements and context
- drunk_call_service/proto/call.proto - gRPC interface contract

---

## Current State

### What Works (Library Level)
- ✅ WebRTCSession: SDP negotiation, ICE, stats, mute
- ✅ Device enumeration (audio + video, cross-platform)
- ✅ Proxy support (HTTP + SOCKS5 via libnice properties)
- ✅ Logger (spdlog with rotation)
- ✅ Tests: test_device_enumeration, test_stats, test_logger passing

### What's Missing (gRPC Service Level)
- ⏳ gRPC service implementation (main.cpp with RPC handlers)
- ⏳ Threading model (GLib main loop + gRPC thread pool)
- ⏳ Event streaming (C++ → Python bidirectional)
- ⏳ Session lifecycle management (create/destroy, cleanup)
- ⏳ Error propagation (C++ exceptions → Python via ErrorEvent)

---

## Philosophy: Don't Fight the Frameworks

**CRITICAL RULE**: Let each framework do what it does best.

### GStreamer/webrtcbin Requirements
- **GLib main loop MUST run** in a dedicated thread (blocks forever with g_main_loop_run)
- **All GStreamer callbacks** fire in main loop thread
- **Thread-safe access** to GStreamer elements requires locks or main loop context invocation

### gRPC Requirements
- **gRPC handlers** run in gRPC thread pool (configurable size)
- **Bidirectional streaming** (StreamEvents) needs dedicated thread per stream
- **Synchronous calls** (CreateOffer, CreateAnswer) block caller thread until complete

### The Integration Challenge
```
Python (asyncio)
    ↓ gRPC async client
gRPC C++ Server (thread pool)
    ↓ needs to call
GStreamer (GLib main loop thread)
    ↓ callbacks fire
gRPC Event Stream (back to Python)
```

**Anti-pattern we're AVOIDING**: Trying to patch both ends simultaneously led to async timing races in Go implementation.

---

## Threading Model

### Thread Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Main Thread (short-lived)                │
│  - Parse CLI args                                           │
│  - Initialize GStreamer (gst_init)                          │
│  - Initialize spdlog logger                                 │
│  - Start GLib thread                                        │
│  - Start gRPC server                                        │
│  - Wait for SIGINT/SIGTERM → cleanup → exit                 │
└─────────────────────────────────────────────────────────────┘
                         │
         ┌───────────────┴────────────────┐
         ↓                                ↓
┌────────────────────────┐    ┌──────────────────────────────┐
│  GLib Main Loop Thread │    │  gRPC Server Thread Pool     │
│  (1 thread, dedicated) │    │  (N threads, configurable)   │
├────────────────────────┤    ├──────────────────────────────┤
│ - g_main_loop_run()    │    │ RPC Handlers:                │
│   (blocks forever)     │    │  - CreateSession             │
│                        │    │  - CreateOffer               │
│ GStreamer callbacks:   │    │  - CreateAnswer              │
│  - on_ice_candidate    │    │  - SetRemoteDescription      │
│  - on_negotiation_...  │    │  - AddICECandidate           │
│  - on_ice_conn_state   │    │  - GetStats                  │
│  - pad-added           │    │  - SetMute                   │
│                        │    │  - EndSession                │
│ Pushes events to →     │    │  - StreamEvents (streaming)  │
│ thread-safe queue      │    │  - Heartbeat                 │
└────────────────────────┘    │  - Shutdown                  │
                              └──────────────────────────────┘
                                      ↓
                          ┌──────────────────────────────────┐
                          │ Per-Session Event Stream Threads │
                          │ (1 thread per active StreamEvents│
                          │  RPC call, managed by gRPC)      │
                          ├──────────────────────────────────┤
                          │ - Polls thread-safe event queue  │
                          │ - Sends CallEvent to Python      │
                          │ - Blocks on queue.pop() until    │
                          │   event available or cancelled   │
                          └──────────────────────────────────┘
```

### Thread Responsibilities

| Thread | Runs | Responsibilities | Blocking? |
|--------|------|------------------|-----------|
| **Main** | main() | Startup, signal handling, shutdown coordination | Yes (waits for signals) |
| **GLib loop** | g_main_loop_run() | GStreamer callbacks, webrtcbin signals | Yes (event loop) |
| **gRPC pool** | grpc::Server | RPC handlers, session management | No (thread pool) |
| **StreamEvents** | grpc streaming | Event queue polling, Python streaming | Yes (blocking read from queue) |

---

## Session Management

### Session Structure

```cpp
struct CallSession {
    std::string session_id;           // Jingle session ID (from Python)
    std::string peer_jid;             // Remote peer JID

    // WebRTC session (library layer)
    std::unique_ptr<WebRTCSession> webrtc;

    // Event streaming
    std::shared_ptr<ThreadSafeQueue<CallEvent>> event_queue;
    grpc::ServerWriter<CallEvent>* event_writer;  // Set when StreamEvents RPC active
    std::mutex event_writer_lock;                 // Protect event_writer access

    // State
    std::atomic<bool> active;         // Session is active (not ended)
    std::chrono::steady_clock::time_point created_at;
};
```

### Session Lifecycle

```
Python                          gRPC Handler (C++)                GLib Thread
  |                                    |                                 |
  |--CreateSession(session_id)------→ |                                 |
  |                                    | Create CallSession              |
  |                                    | Create WebRTCSession            |
  |                                    | webrtc->initialize(config)      |
  |                                    | Store in sessions map           |
  |←--------success/error------------- |                                 |
  |                                    |                                 |
  |--StreamEvents(session_id)-------→ |                                 |
  |                                    | Set event_writer in session     |
  |                                    | [BLOCKS streaming events]       |
  |                                    |                                 |
  |--CreateOffer(session_id)--------→ |                                 |
  |                                    | webrtc->create_offer(callback)  |
  |                                    | [WAIT on promise/callback]      |
  |                                    |                          webrtc fires
  |                                    |                          on_offer_created
  |                                    |                          → cv.notify()
  |                                    | [RESUME with SDP]               |
  |←--------SDP offer----------------- |                                 |
  |                                    |                                 |
  |                                    |                          on_ice_candidate
  |←--------ICECandidateEvent--------- |← queue.push(event) ------------ |
  |                                    |                                 |
  |                                    |                          on_ice_connection_state
  |←--------ConnectionStateEvent------ |← queue.push(event) ------------ |
  |                                    |                                 |
  |--EndSession(session_id)----------→|                                 |
  |                                    | webrtc->stop()                  |
  |                                    | event_writer->WritesDone()      |
  |                                    | Delete from sessions map        |
  |←--------ok------------------------ |                                 |
```

### Thread-Safe Session Access

**Problem**: gRPC handlers (thread pool) need to access sessions that GStreamer callbacks (GLib thread) also access.

**Solution**: Mutex-protected session map + reference counting.

```cpp
class CallServiceImpl {
private:
    std::mutex sessions_lock_;
    std::map<std::string, std::shared_ptr<CallSession>> sessions_;

public:
    std::shared_ptr<CallSession> get_session(const std::string& session_id) {
        std::lock_guard<std::mutex> lock(sessions_lock_);
        auto it = sessions_.find(session_id);
        if (it == sessions_.end()) return nullptr;
        return it->second;  // shared_ptr keeps session alive during use
    }

    void add_session(const std::string& session_id, std::shared_ptr<CallSession> session) {
        std::lock_guard<std::mutex> lock(sessions_lock_);
        sessions_[session_id] = session;
    }

    void remove_session(const std::string& session_id) {
        std::lock_guard<std::mutex> lock(sessions_lock_);
        sessions_.erase(session_id);
    }
};
```

**Usage**:
```cpp
// In RPC handler (gRPC thread)
auto session = service->get_session(request->session_id());
if (!session) {
    return grpc::Status(grpc::StatusCode::NOT_FOUND, "Session not found");
}
// session is now ref-counted - won't be deleted until shared_ptr goes out of scope
session->webrtc->set_mute(request->muted());
```

---

## Event Streaming (C++ → Python)

### The Challenge

GStreamer callbacks fire in GLib thread:
```cpp
// This runs in GLib thread!
void on_ice_candidate(GstElement* webrtc, guint mlineindex, gchar* candidate, gpointer user_data) {
    // How do we get this to Python?
}
```

Python expects events via `StreamEvents` RPC:
```python
async for event in stub.StreamEvents(request):
    # Handle event
```

### The Solution: Thread-Safe Event Queue

```cpp
template<typename T>
class ThreadSafeQueue {
private:
    std::queue<T> queue_;
    std::mutex mutex_;
    std::condition_variable cv_;
    bool shutdown_ = false;

public:
    void push(const T& item) {
        std::lock_guard<std::mutex> lock(mutex_);
        queue_.push(item);
        cv_.notify_one();  // Wake up StreamEvents thread
    }

    bool pop(T& item, std::chrono::milliseconds timeout = std::chrono::milliseconds(1000)) {
        std::unique_lock<std::mutex> lock(mutex_);

        // Wait for item or shutdown
        if (!cv_.wait_for(lock, timeout, [this] {
            return !queue_.empty() || shutdown_;
        })) {
            return false;  // Timeout
        }

        if (shutdown_ && queue_.empty()) {
            return false;  // Shutting down
        }

        item = std::move(queue_.front());
        queue_.pop();
        return true;
    }

    void shutdown() {
        std::lock_guard<std::mutex> lock(mutex_);
        shutdown_ = true;
        cv_.notify_all();  // Wake all waiting threads
    }
};
```

### Event Flow

```
GLib Thread                        Event Queue              StreamEvents Thread (gRPC)
     |                                   |                              |
on_ice_candidate()                       |                              |
     | CallEvent event;                  |                              |
     | event.set_session_id(sid);        |                              |
     | event.mutable_ice_candidate()->   |                              |
     |   set_candidate(cand);            |                              |
     |                                   |                              |
     | queue->push(event); -----------→ | store event                  |
     |                                   | cv.notify_one() -----------→ | wake up!
     |                                   |                              |
     |                                   |                  T item;     |
     |                                   | ←--------------- | queue.pop(item)
     |                                   | return item --→  |           |
     |                                   |                  | writer->Write(item)
     |                                   |                              | → Python
```

### StreamEvents RPC Implementation

```cpp
grpc::Status CallServiceImpl::StreamEvents(
    grpc::ServerContext* context,
    const StreamEventsRequest* request,
    grpc::ServerWriter<CallEvent>* writer) {

    std::string session_id = request->session_id();
    LOG_INFO("StreamEvents started for session: {}", session_id);

    // Get session
    auto session = get_session(session_id);
    if (!session) {
        return grpc::Status(grpc::StatusCode::NOT_FOUND, "Session not found");
    }

    // Set event writer (protected by lock)
    {
        std::lock_guard<std::mutex> lock(session->event_writer_lock);
        if (session->event_writer) {
            // Already streaming - only one StreamEvents per session allowed
            return grpc::Status(grpc::StatusCode::ALREADY_EXISTS,
                               "Event stream already active for this session");
        }
        session->event_writer = writer;
    }

    // Stream events from queue until session ends or client cancels
    while (session->active && !context->IsCancelled()) {
        CallEvent event;

        // Block waiting for event (1s timeout for cancellation check)
        if (session->event_queue->pop(event, std::chrono::milliseconds(1000))) {
            // Send event to Python
            if (!writer->Write(event)) {
                // Client disconnected
                LOG_WARNING("Failed to write event for {}, client disconnected", session_id);
                break;
            }
        }
        // Timeout - check session->active and context->IsCancelled() again
    }

    // Cleanup
    {
        std::lock_guard<std::mutex> lock(session->event_writer_lock);
        session->event_writer = nullptr;
    }

    LOG_INFO("StreamEvents ended for session: {}", session_id);
    return grpc::Status::OK;
}
```

### Callback Wrappers (GLib → Queue)

```cpp
// Static callback (called by GStreamer in GLib thread)
void WebRTCSession::on_ice_candidate_static(GstElement* webrtc, guint mlineindex,
                                           gchar* candidate, gpointer user_data) {
    auto* session = static_cast<WebRTCSession*>(user_data);
    session->on_ice_candidate(mlineindex, candidate);
}

// Instance method (has access to callbacks)
void WebRTCSession::on_ice_candidate(guint mlineindex, const char* candidate) {
    LOG_DEBUG("ICE candidate: mline={} candidate={}", mlineindex, candidate);

    if (ice_callback_) {
        ICECandidate ice_cand;
        ice_cand.candidate = candidate;
        ice_cand.sdp_mid = std::to_string(mlineindex);  // Or actual mid from SDP
        ice_cand.sdp_mline_index = mlineindex;

        ice_callback_(ice_cand);  // Call callback (pushes to queue)
    }
}

// In main.cpp (gRPC service creates WebRTCSession):
webrtc->set_ice_candidate_callback([session](const ICECandidate& cand) {
    // This runs in GLib thread!
    CallEvent event;
    event.set_session_id(session->session_id);
    auto* ice_event = event.mutable_ice_candidate();
    ice_event->set_candidate(cand.candidate);
    ice_event->set_sdp_mid(cand.sdp_mid);
    ice_event->set_sdp_mline_index(cand.sdp_mline_index);

    session->event_queue->push(event);  // Thread-safe push
});
```

---

## RPC Handler Implementations

### CreateSession

```cpp
grpc::Status CallServiceImpl::CreateSession(
    grpc::ServerContext* context,
    const CreateSessionRequest* request,
    CreateSessionResponse* response) {

    try {
        std::string session_id = request->session_id();
        LOG_INFO("CreateSession: {}", session_id);

        // Create session
        auto session = std::make_shared<CallSession>();
        session->session_id = session_id;
        session->peer_jid = request->peer_jid();
        session->event_queue = std::make_shared<ThreadSafeQueue<CallEvent>>();
        session->active = true;
        session->created_at = std::chrono::steady_clock::now();

        // Create WebRTC session
        session->webrtc = std::make_unique<WebRTCSession>();

        // Configure session
        SessionConfig config;
        config.session_id = session_id;
        config.microphone_device = request->microphone_device();
        config.speakers_device = request->speakers_device();
        config.relay_only = request->relay_only();

        // Proxy config
        if (!request->proxy_host().empty()) {
            config.proxy_host = request->proxy_host();
            config.proxy_port = request->proxy_port();
            config.proxy_username = request->proxy_username();
            config.proxy_password = request->proxy_password();
            config.proxy_type = request->proxy_type();  // "SOCKS5" or "HTTP"
        }

        // TURN config
        if (!request->turn_server().empty()) {
            config.turn_server = request->turn_server();
            config.turn_username = request->turn_username();
            config.turn_password = request->turn_password();
        }

        // Audio processing
        config.echo_cancel = request->echo_cancel();
        config.noise_suppression = request->noise_suppression();
        config.gain_control = request->gain_control();

        // Set callbacks (BEFORE initialize to avoid race)
        session->webrtc->set_ice_candidate_callback([session](const ICECandidate& cand) {
            CallEvent event;
            event.set_session_id(session->session_id);
            auto* ice_event = event.mutable_ice_candidate();
            ice_event->set_candidate(cand.candidate);
            ice_event->set_sdp_mid(cand.sdp_mid);
            ice_event->set_sdp_mline_index(cand.sdp_mline_index);
            session->event_queue->push(event);
        });

        session->webrtc->set_state_callback([session](ConnectionState state,
                                                       ICEConnectionState ice_state,
                                                       ICEGatheringState gathering_state) {
            // Map to proto enum
            CallEvent event;
            event.set_session_id(session->session_id);
            auto* state_event = event.mutable_connection_state();

            // Map ICE connection state (this is what Python cares about)
            switch (ice_state) {
                case ICEConnectionState::NEW:
                    state_event->set_state(ConnectionStateEvent::NEW);
                    break;
                case ICEConnectionState::CHECKING:
                    state_event->set_state(ConnectionStateEvent::CHECKING);
                    break;
                case ICEConnectionState::CONNECTED:
                case ICEConnectionState::COMPLETED:
                    state_event->set_state(ConnectionStateEvent::CONNECTED);
                    break;
                case ICEConnectionState::FAILED:
                    state_event->set_state(ConnectionStateEvent::FAILED);
                    break;
                case ICEConnectionState::DISCONNECTED:
                    state_event->set_state(ConnectionStateEvent::DISCONNECTED);
                    break;
                case ICEConnectionState::CLOSED:
                    state_event->set_state(ConnectionStateEvent::CLOSED);
                    break;
            }

            session->event_queue->push(event);
        });

        // Initialize WebRTC session
        if (!session->webrtc->initialize(config)) {
            response->set_success(false);
            response->set_error("Failed to initialize WebRTC session");
            return grpc::Status::OK;
        }

        // Start pipeline
        if (!session->webrtc->start()) {
            response->set_success(false);
            response->set_error("Failed to start WebRTC pipeline");
            return grpc::Status::OK;
        }

        // Store session
        add_session(session_id, session);

        response->set_success(true);
        LOG_INFO("Session created: {}", session_id);
        return grpc::Status::OK;

    } catch (const std::exception& e) {
        LOG_ERROR("CreateSession exception: {}", e.what());
        response->set_success(false);
        response->set_error(e.what());
        return grpc::Status::OK;
    }
}
```

### CreateOffer

**Challenge**: Asynchronous operation (webrtcbin uses GstPromise callbacks).

**Solution**: Condition variable + timeout.

```cpp
grpc::Status CallServiceImpl::CreateOffer(
    grpc::ServerContext* context,
    const CreateOfferRequest* request,
    SDPResponse* response) {

    try {
        std::string session_id = request->session_id();
        LOG_INFO("CreateOffer: {}", session_id);

        auto session = get_session(session_id);
        if (!session) {
            response->set_error("Session not found");
            return grpc::Status::OK;
        }

        // Synchronization for async SDP creation
        std::mutex sdp_mutex;
        std::condition_variable sdp_cv;
        std::string sdp_result;
        std::string error_result;
        bool sdp_done = false;

        // Call create_offer with callback
        session->webrtc->create_offer([&](const SDPMessage& sdp, const std::string& error) {
            std::lock_guard<std::mutex> lock(sdp_mutex);
            if (!error.empty()) {
                error_result = error;
            } else {
                sdp_result = sdp.sdp;
            }
            sdp_done = true;
            sdp_cv.notify_one();
        });

        // Wait for callback (with timeout)
        std::unique_lock<std::mutex> lock(sdp_mutex);
        if (!sdp_cv.wait_for(lock, std::chrono::seconds(10), [&] { return sdp_done; })) {
            response->set_error("Timeout waiting for offer");
            LOG_ERROR("CreateOffer timeout for {}", session_id);
            return grpc::Status::OK;
        }

        if (!error_result.empty()) {
            response->set_error(error_result);
            return grpc::Status::OK;
        }

        response->set_sdp(sdp_result);
        LOG_INFO("Offer created for {}", session_id);
        return grpc::Status::OK;

    } catch (const std::exception& e) {
        LOG_ERROR("CreateOffer exception: {}", e.what());
        response->set_error(e.what());
        return grpc::Status::OK;
    }
}
```

**Note**: CreateAnswer follows same pattern.

### SetRemoteDescription

```cpp
grpc::Status CallServiceImpl::SetRemoteDescription(
    grpc::ServerContext* context,
    const SetRemoteDescriptionRequest* request,
    Empty* response) {

    try {
        std::string session_id = request->session_id();
        LOG_INFO("SetRemoteDescription: {} (type={})", session_id, request->sdp_type());

        auto session = get_session(session_id);
        if (!session) {
            return grpc::Status(grpc::StatusCode::NOT_FOUND, "Session not found");
        }

        SDPMessage remote_sdp;
        remote_sdp.sdp = request->remote_sdp();
        remote_sdp.type = request->sdp_type();  // "offer" or "answer"

        if (!session->webrtc->set_remote_description(remote_sdp)) {
            return grpc::Status(grpc::StatusCode::INTERNAL,
                               "Failed to set remote description");
        }

        LOG_INFO("Remote description set for {}", session_id);
        return grpc::Status::OK;

    } catch (const std::exception& e) {
        LOG_ERROR("SetRemoteDescription exception: {}", e.what());
        return grpc::Status(grpc::StatusCode::INTERNAL, e.what());
    }
}
```

### AddICECandidate

```cpp
grpc::Status CallServiceImpl::AddICECandidate(
    grpc::ServerContext* context,
    const AddICECandidateRequest* request,
    Empty* response) {

    try {
        std::string session_id = request->session_id();

        auto session = get_session(session_id);
        if (!session) {
            return grpc::Status(grpc::StatusCode::NOT_FOUND, "Session not found");
        }

        ICECandidate candidate;
        candidate.candidate = request->candidate();
        candidate.sdp_mid = request->sdp_mid();
        candidate.sdp_mline_index = request->sdp_mline_index();

        if (!session->webrtc->add_remote_ice_candidate(candidate)) {
            LOG_WARNING("Failed to add ICE candidate for {}", session_id);
            // Don't fail - ICE candidates can arrive late or be duplicates
        }

        return grpc::Status::OK;

    } catch (const std::exception& e) {
        LOG_ERROR("AddICECandidate exception: {}", e.what());
        return grpc::Status(grpc::StatusCode::INTERNAL, e.what());
    }
}
```

### EndSession

```cpp
grpc::Status CallServiceImpl::EndSession(
    grpc::ServerContext* context,
    const EndSessionRequest* request,
    Empty* response) {

    try {
        std::string session_id = request->session_id();
        LOG_INFO("EndSession: {}", session_id);

        auto session = get_session(session_id);
        if (!session) {
            // Session already ended - not an error
            LOG_WARNING("EndSession called for non-existent session: {}", session_id);
            return grpc::Status::OK;
        }

        // Mark inactive (stops StreamEvents loop)
        session->active = false;

        // Stop WebRTC session (GStreamer pipeline)
        if (session->webrtc) {
            session->webrtc->stop();
        }

        // Shutdown event queue (wakes StreamEvents thread)
        if (session->event_queue) {
            session->event_queue->shutdown();
        }

        // Remove from sessions map
        remove_session(session_id);

        LOG_INFO("Session ended: {}", session_id);
        return grpc::Status::OK;

    } catch (const std::exception& e) {
        LOG_ERROR("EndSession exception: {}", e.what());
        return grpc::Status(grpc::StatusCode::INTERNAL, e.what());
    }
}
```

---

## Error Handling

### Principles

1. **C++ exceptions → gRPC Status codes** for RPC errors
2. **GStreamer errors → ErrorEvent** streamed to Python
3. **PROPAGATE errors to Python** - GUI must show user feedback

### Error Event Flow

```cpp
// In WebRTCSession::on_pipeline_error (called from GLib thread)
void WebRTCSession::on_pipeline_error(const std::string& message, const std::string& debug) {
    LOG_ERROR("Pipeline error: {} (debug: {})", message, debug);

    if (error_callback_) {
        error_callback_(message, debug);  // Callback pushes to queue
    }
}

// In main.cpp CreateSession:
session->webrtc->set_error_callback([session](const std::string& message,
                                               const std::string& debug) {
    CallEvent event;
    event.set_session_id(session->session_id);
    auto* error_event = event.mutable_error();
    error_event->set_message(message);
    // Future: Add error_type enum (ICE_FAILED, DTLS_FAILED, etc.)

    session->event_queue->push(event);
});
```

### Common Error Scenarios

| Error | Where Detected | How Reported | Python Action |
|-------|---------------|--------------|---------------|
| Session not found | RPC handler | grpc::Status NOT_FOUND | Log warning |
| Pipeline creation failed | WebRTCSession::initialize() | CreateSessionResponse.error | Show error dialog |
| ICE failed | on_ice_connection_state (FAILED) | ConnectionStateEvent | Show "Connection failed" |
| DTLS handshake failed | on_pipeline_error | ErrorEvent | Show "Encryption failed" |
| Proxy unreachable | libnice (via bus message) | ErrorEvent | Show "Proxy error" |
| Offer creation timeout | CreateOffer handler | SDPResponse.error | Retry or abort call |

---

## File Structure

```
drunk_call_service/
├── src/
│   ├── main.cpp                    # gRPC service entry point, main() function
│   ├── call_service_impl.{h,cpp}  # CallServiceImpl class (RPC handlers)
│   ├── thread_safe_queue.h        # ThreadSafeQueue template
│   ├── session_manager.{h,cpp}    # Session map, thread-safe access
│   ├── webrtc_session.{h,cpp}     # (existing) WebRTCSession implementation
│   ├── media_session.h            # (existing) Interface
│   ├── device_enumerator.cpp      # (existing) Device enumeration
│   └── logger.{h,cpp}             # (existing) spdlog wrapper
│
├── proto/
│   └── call.proto                 # gRPC interface definition
│
├── tests/standalone/
│   ├── test_grpc_service.cpp      # NEW: Full end-to-end gRPC test
│   ├── test_event_streaming.cpp   # NEW: Event queue test
│   └── (existing tests)
│
└── CMakeLists.txt                 # Build configuration
```

---

## Implementation Steps

### Step 4.1: Thread Infrastructure

**Files**: `src/thread_safe_queue.h`, `src/session_manager.{h,cpp}`

**Tasks**:
1. Implement ThreadSafeQueue template
2. Create SessionManager class (mutex-protected session map)
3. Write unit tests for queue (blocking pop, timeout, shutdown)

**Test**: Compile, run test_thread_safe_queue

### Step 4.2: gRPC Service Skeleton

**Files**: `src/main.cpp`, `src/call_service_impl.{h,cpp}`

**Tasks**:
1. Implement main() with GLib thread startup
2. Create CallServiceImpl class stub (all RPCs return UNIMPLEMENTED)
3. Start gRPC server, join GLib thread

**Test**: Start service, call Heartbeat RPC from Python

### Step 4.3: CreateSession + Event Streaming

**Files**: `src/call_service_impl.cpp`

**Tasks**:
1. Implement CreateSession RPC (create WebRTCSession, set callbacks)
2. Implement StreamEvents RPC (poll event queue, stream to Python)
3. Wire ICE candidate callback to event queue

**Test**: Create session from Python, verify StreamEvents receives ICE candidates

### Step 4.4: SDP Operations (Offer/Answer)

**Files**: `src/call_service_impl.cpp`

**Tasks**:
1. Implement CreateOffer RPC (async with cv.wait_for)
2. Implement CreateAnswer RPC (same pattern)
3. Implement SetRemoteDescription RPC

**Test**: Full offer/answer exchange from Python, verify SDP negotiation

### Step 4.5: ICE + State Callbacks

**Files**: `src/call_service_impl.cpp`

**Tasks**:
1. Implement AddICECandidate RPC
2. Wire connection state callback to event queue
3. Map ICE states to proto enums

**Test**: Verify ICE state transitions stream to Python (NEW → CHECKING → CONNECTED)

### Step 4.6: GetStats, SetMute, EndSession

**Files**: `src/call_service_impl.cpp`

**Tasks**:
1. Implement GetStats RPC (read from WebRTCSession::get_stats())
2. Implement SetMute RPC
3. Implement EndSession RPC (cleanup, queue shutdown)
4. Implement Shutdown RPC (graceful service exit)

**Test**: Call operations from Python, verify behavior

### Step 4.7: Error Handling

**Files**: `src/call_service_impl.cpp`, `src/webrtc_session.cpp`

**Tasks**:
1. Add error callback to WebRTCSession
2. Stream ErrorEvent for pipeline errors
3. Add try-catch to all RPC handlers

**Test**: Trigger errors (invalid SDP, missing session), verify ErrorEvent

### Step 4.8: Integration Testing

**Files**: `tests/standalone/test_grpc_service.cpp`

**Tasks**:
1. Write full call flow test (C++ client → gRPC service)
2. Test concurrent sessions (multiple calls simultaneously)
3. Test session cleanup (memory leaks, dangling pointers)

**Test**: Run test suite, verify no crashes or leaks (valgrind)

---

## Testing Strategy

### Unit Tests (C++, standalone)

- `test_thread_safe_queue`: Queue operations, threading, shutdown
- `test_session_manager`: Concurrent access, session lifecycle

### Integration Tests (C++, with GStreamer)

- `test_grpc_service`: Full RPC flow (CreateSession → CreateOffer → StreamEvents → EndSession)
- `test_event_streaming`: Verify events reach Python correctly

### End-to-End Tests (Python → C++)

- Create session from Python CallBridge
- Verify events stream back
- Test concurrent calls (multiple accounts)

### Interoperability Tests (Real XMPP)

- Call Conversations.im (Android)
- Call Dino (Linux)
- Verify audio bidirectional, stats accurate

---

## Known Issues from Go Implementation

### Issues We're Fixing:

1. **No separation of ICE/peer connection state** - Fixed: proto will have both fields
2. **rtcp-mux voodoo** - Fixed: webrtcbin handles transparently
3. **Trickle ICE race conditions** - Fixed: proper candidate queuing in Jingle layer (see JINGLE-REFACTOR-PLAN.md)
4. **Component 1/2 confusion** - Fixed: webrtcbin auto-handles with bundle-policy=max-bundle

### Issues We're Keeping:

- **Heartbeat to keep service alive** - Prevents Go GC from killing idle service (same issue in C++? No, but keep for compatibility)

---

## Success Criteria

### Functional Requirements

- ✅ CreateSession creates WebRTCSession, starts pipeline
- ✅ CreateOffer returns valid SDP with bundle, rtcp-mux, trickle ICE
- ✅ StreamEvents receives ICE candidates in real-time
- ✅ Connection state transitions stream to Python (NEW → CHECKING → CONNECTED)
- ✅ GetStats returns accurate bandwidth, connection type, candidates
- ✅ SetMute works without audio glitches
- ✅ EndSession cleans up pipeline, no leaks
- ✅ Concurrent sessions work (multiple calls simultaneously)

### Non-Functional Requirements

- ✅ Binary size < 10MB (stripped)
- ✅ Startup time < 500ms
- ✅ No crashes under load (tested with valgrind)
- ✅ Thread-safe (no race conditions under tsan)

### Interoperability

- ✅ Works with Conversations.im (trickle ICE, relay mode)
- ✅ Works with Dino (standard WebRTC)
- ✅ Audio bidirectional, no echo/noise with default settings

---

**Next Steps**:
1. Review this plan with user
2. Create JINGLE-REFACTOR-PLAN.md (Python side cleanup)
3. Create PROTO-IMPROVEMENTS.md (proto changes needed)
4. Begin implementation (Step 4.1)

---

**Last Updated**: 2026-03-02
**Status**: Ready for review
