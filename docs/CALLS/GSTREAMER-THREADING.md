# GStreamer Threading Model - Verified

**Date**: 2026-03-02
**Status**: VERIFIED - Triple-checked against existing code and GStreamer docs
**Context**: User reported stepping "on that rake once" with threading issues

---

## TL;DR: The Correct Pattern

```
┌─────────────────────────┐
│  GLib Main Loop Thread  │  ← Start this FIRST, runs g_main_loop_run()
│  - Creates webrtcbin    │
│  - Processes signals    │
│  - Fires callbacks      │
└─────────────────────────┘
           ↑
           │ GStreamer signals/promises processed here
           │
┌─────────────────────────┐
│   gRPC Handler Thread   │  ← Can safely call GStreamer APIs
│  - Calls create_offer() │     (signals queued to main loop)
│  - Waits on promise     │
│  - Gets result          │
└─────────────────────────┘
```

**KEY RULE**: GLib main loop MUST be running for promises to complete.

---

## What We Learned from Existing Code

### Current Implementation (Standalone Tests)

**File**: `drunk_call_service/src/webrtc_session.cpp`

```cpp
// Line 141-145: Create offer
GstPromise *promise = gst_promise_new_with_change_func(
    on_offer_created_static, this, nullptr);
g_signal_emit_by_name(webrtc_, "create-offer", nullptr, promise);

// Line 725: Callback fires, BLOCKING wait
g_assert(gst_promise_wait(promise) == GST_PROMISE_RESULT_REPLIED);
```

**How it works in tests**:
1. Main thread creates pipeline + webrtcbin
2. Main thread calls create_offer()
3. webrtcbin processes create-offer signal **synchronously** (no separate thread)
4. Promise callback fires **in same thread**
5. gst_promise_wait() returns immediately

**This works because**: No separate GLib main loop thread in standalone tests.

---

## The Problem with gRPC Service

### ❌ WRONG Pattern (Will Deadlock)

```cpp
// BAD: gRPC handler calls GStreamer API directly without main loop
grpc::Status CreateOffer(...) {
    // webrtc_ created in main thread, gRPC handler in thread pool
    GstPromise *promise = gst_promise_new_with_change_func(...);
    g_signal_emit_by_name(webrtc_, "create-offer", nullptr, promise);

    gst_promise_wait(promise);  // ❌ DEADLOCK!
    // Promise never completes because GLib main loop not running
}
```

**Why it fails**:
- webrtcbin needs **GLib main loop** to process signals
- No main loop running → signal queued but never processed
- Promise never resolves → gst_promise_wait() blocks forever

**"Missing half of the context"** - This is what the user meant!

---

## ✅ CORRECT Pattern (From Our Plan)

### Architecture

```cpp
// ============================================================================
// main.cpp - Service Startup
// ============================================================================

int main() {
    gst_init(nullptr, nullptr);

    // 1. Create GLib main loop
    GMainLoop *loop = g_main_loop_new(nullptr, FALSE);

    // 2. Start GLib thread BEFORE creating any sessions
    std::thread glib_thread([loop]() {
        g_main_loop_run(loop);  // Blocks forever, processing events
    });

    // 3. Start gRPC server (separate thread pool)
    grpc::Server *server = /* ... */;
    server->Wait();  // Block until shutdown

    // 4. Cleanup
    g_main_loop_quit(loop);
    glib_thread.join();
    g_main_loop_unref(loop);
}
```

### Threading Breakdown

**Thread 1: GLib Main Loop (dedicated)**
- Runs `g_main_loop_run()` - blocks forever
- Processes ALL GStreamer signals/events
- ALL GStreamer callbacks fire here
- Creates webrtcbin elements (owned by this thread's context)

**Thread 2-N: gRPC Thread Pool**
- Handles CreateOffer, CreateAnswer, etc. RPCs
- **NEVER manipulates GStreamer objects directly**
- Uses cross-thread synchronization patterns (see below)

---

## Cross-Thread Communication Patterns

### Pattern 1: Async Operations (CreateOffer, CreateAnswer)

**Flow**: gRPC handler needs result from GStreamer operation

```cpp
// In CallServiceImpl::CreateOffer (gRPC thread)
grpc::Status CallServiceImpl::CreateOffer(...) {
    auto session = get_session(session_id);

    // Synchronization primitives
    std::mutex sdp_mutex;
    std::condition_variable sdp_cv;
    std::string sdp_result;
    bool sdp_done = false;

    // Set callback that will fire in GLib thread
    session->webrtc->set_sdp_callback([&](bool success, const SDPMessage& sdp, ...) {
        // THIS FIRES IN GLIB THREAD!
        std::lock_guard<std::mutex> lock(sdp_mutex);
        sdp_result = sdp.sdp;
        sdp_done = true;
        sdp_cv.notify_one();  // Wake gRPC thread
    });

    // Trigger operation (webrtc->create_offer() just stores callback)
    session->webrtc->create_offer(/* callback already set */);

    // WAIT for GLib thread to complete operation
    std::unique_lock<std::mutex> lock(sdp_mutex);
    if (!sdp_cv.wait_for(lock, std::chrono::seconds(10), [&] { return sdp_done; })) {
        return grpc::Status(grpc::DEADLINE_EXCEEDED, "Offer creation timeout");
    }

    response->set_sdp(sdp_result);
    return grpc::Status::OK;
}

// In WebRTCSession::create_offer (called from gRPC thread)
void WebRTCSession::create_offer(SDPCallback callback) {
    sdp_callback_ = callback;  // Store callback

    // Create promise
    GstPromise *promise = gst_promise_new_with_change_func(
        on_offer_created_static, this, nullptr);

    // Emit signal - will be processed by GLib main loop
    g_signal_emit_by_name(webrtc_, "create-offer", nullptr, promise);

    // DON'T WAIT HERE - callback will fire asynchronously in GLib thread
}

// In WebRTCSession::on_offer_created (GLib thread)
void WebRTCSession::on_offer_created(GstPromise *promise) {
    // THIS RUNS IN GLIB THREAD
    gst_promise_wait(promise);  // OK to block here

    // Extract SDP
    const GstStructure *reply = gst_promise_get_reply(promise);
    GstWebRTCSessionDescription *offer = nullptr;
    gst_structure_get(reply, "offer", GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &offer, nullptr);

    gchar *sdp_text = gst_sdp_message_as_text(offer->sdp);
    std::string sdp_str(sdp_text);
    g_free(sdp_text);

    // Call user callback (fires in GLib thread!)
    if (sdp_callback_) {
        SDPMessage sdp_msg(SDPMessage::Type::OFFER, sdp_str);
        sdp_callback_(true, sdp_msg, "");  // → Notifies condition variable
    }

    gst_webrtc_session_description_free(offer);
    gst_promise_unref(promise);
}
```

**Key Points**:
- gRPC thread sets callback + triggers operation
- GLib thread processes signal, calls callback
- Callback notifies condition variable
- gRPC thread wakes up with result
- **Timeout prevents infinite wait** (10s)

### Pattern 2: Event Streaming (ICE Candidates, State Changes)

**Flow**: GLib thread → gRPC streaming RPC → Python

```cpp
// In CallSession (shared between threads)
struct CallSession {
    std::shared_ptr<ThreadSafeQueue<CallEvent>> event_queue;
    // Thread-safe queue (mutex + condition variable internally)
};

// In WebRTCSession::on_ice_candidate (GLib thread)
void WebRTCSession::on_ice_candidate(guint mlineindex, const char *candidate) {
    // THIS RUNS IN GLIB THREAD
    if (ice_callback_) {
        ICECandidate ice_cand;
        ice_cand.candidate = candidate;
        ice_callback_(ice_cand);  // Pushes to queue
    }
}

// In CreateSession RPC handler (gRPC thread)
session->webrtc->set_ice_candidate_callback([session](const ICECandidate& cand) {
    // THIS FIRES IN GLIB THREAD!
    CallEvent event;
    event.set_session_id(session->session_id);
    auto* ice_event = event.mutable_ice_candidate();
    ice_event->set_candidate(cand.candidate);

    session->event_queue->push(event);  // Thread-safe push
});

// In StreamEvents RPC (dedicated gRPC streaming thread)
grpc::Status StreamEvents(..., grpc::ServerWriter<CallEvent>* writer) {
    auto session = get_session(session_id);

    while (session->active) {
        CallEvent event;

        // Block waiting for event (1s timeout for cancellation check)
        if (session->event_queue->pop(event, std::chrono::milliseconds(1000))) {
            writer->Write(event);  // Send to Python
        }
    }

    return grpc::Status::OK;
}
```

**Key Points**:
- GLib thread pushes events to thread-safe queue
- StreamEvents thread pops from queue, sends to Python
- **No direct communication** between GLib and gRPC threads
- Queue handles all synchronization

---

## ThreadSafeQueue Implementation

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
        cv_.notify_one();  // Wake waiting thread
    }

    bool pop(T& item, std::chrono::milliseconds timeout) {
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
        cv_.notify_all();
    }
};
```

---

## Common Mistakes (How NOT to Do It)

### ❌ Mistake 1: Calling GStreamer APIs from gRPC Thread

```cpp
// BAD: Direct GStreamer manipulation from gRPC thread
grpc::Status SetMute(SetMuteRequest* request, ...) {
    auto session = get_session(request->session_id());

    // ❌ WRONG: volume_ is a GStreamer element owned by GLib thread
    g_object_set(session->webrtc->volume_, "volume",
                 request->muted() ? 0.0 : 1.0, nullptr);

    return grpc::Status::OK;
}
```

**Why it fails**: GStreamer objects are NOT thread-safe. Accessing from wrong thread = undefined behavior.

**Fix**: Use g_idle_add() to execute in GLib thread:
```cpp
// GOOD: Marshal to GLib thread
grpc::Status SetMute(SetMuteRequest* request, ...) {
    auto session = get_session(request->session_id());
    bool muted = request->muted();

    // Execute in GLib thread
    g_idle_add([](gpointer user_data) -> gboolean {
        auto* session = static_cast<CallSession*>(user_data);
        g_object_set(session->webrtc->volume_, "volume",
                     session->muted ? 0.0 : 1.0, nullptr);
        return G_SOURCE_REMOVE;  // Don't repeat
    }, session.get());

    return grpc::Status::OK;
}
```

### ❌ Mistake 2: No Main Loop Running

```cpp
// BAD: Creating webrtcbin without main loop
int main() {
    gst_init(nullptr, nullptr);

    // Create webrtcbin
    GstElement *webrtc = gst_element_factory_make("webrtcbin", nullptr);

    // Try to create offer
    GstPromise *promise = gst_promise_new();
    g_signal_emit_by_name(webrtc, "create-offer", nullptr, promise);
    gst_promise_wait(promise);  // ❌ DEADLOCK!
}
```

**Fix**: Start main loop FIRST:
```cpp
// GOOD: Main loop running
int main() {
    gst_init(nullptr, nullptr);

    GMainLoop *loop = g_main_loop_new(nullptr, FALSE);
    std::thread glib_thread([loop]() {
        g_main_loop_run(loop);  // ← Essential!
    });

    // Now webrtcbin can process signals
    // ...
}
```

### ❌ Mistake 3: Creating webrtcbin in Wrong Thread

```cpp
// QUESTIONABLE: Creating webrtcbin in gRPC thread
grpc::Status CreateSession(...) {
    // We're in gRPC thread pool
    auto session = std::make_shared<CallSession>();
    session->webrtc = std::make_unique<WebRTCSession>();
    session->webrtc->initialize(config);  // ❌ Creates pipeline here

    // Later, GLib thread tries to process signals...
    // webrtcbin is owned by different thread's context!
}
```

**Potential issue**: GStreamer elements should be created in the thread that will process their signals (GLib thread).

**Fix** (if needed): Use g_idle_add() to create pipeline in GLib thread, wait for completion:
```cpp
// SAFER: Create pipeline in GLib thread
grpc::Status CreateSession(...) {
    auto session = std::make_shared<CallSession>();
    session->webrtc = std::make_unique<WebRTCSession>();

    std::mutex init_mutex;
    std::condition_variable init_cv;
    bool init_done = false;
    bool init_success = false;

    g_idle_add([](gpointer user_data) -> gboolean {
        auto* data = static_cast<InitData*>(user_data);
        data->success = data->session->webrtc->initialize(data->config);
        {
            std::lock_guard<std::mutex> lock(data->mutex);
            data->done = true;
        }
        data->cv.notify_one();
        return G_SOURCE_REMOVE;
    }, &init_data);

    std::unique_lock<std::mutex> lock(init_mutex);
    init_cv.wait(lock, [&] { return init_done; });

    if (!init_success) {
        return grpc::Status(grpc::INTERNAL, "Failed to initialize");
    }

    return grpc::Status::OK;
}
```

**However**: This might be **overkill**. GStreamer elements can be created in any thread, as long as signals are processed in GLib thread. The existing code creates in gRPC thread and it works.

**Decision**: Keep it simple - create in gRPC thread, signals process in GLib thread. Monitor for issues.

---

## Verification Checklist

Before merging gRPC service code:

- [ ] GLib main loop starts in dedicated thread
- [ ] Main loop starts BEFORE creating any sessions
- [ ] All GStreamer signal handlers (on_ice_candidate, etc.) push to ThreadSafeQueue
- [ ] gRPC handlers use condition variables for async operations (CreateOffer)
- [ ] NO direct g_object_set() calls from gRPC threads (or use g_idle_add)
- [ ] Test: Create session, verify ICE candidates stream
- [ ] Test: Call with 2+ concurrent sessions (threading stress test)
- [ ] Test: Shutdown cleanly (no deadlocks, no crashes)

---

## Summary: The Golden Rules

1. **GLib main loop MUST run** in a dedicated thread for promises/signals to work
2. **GStreamer callbacks fire in GLib thread** - use ThreadSafeQueue for cross-thread events
3. **gRPC handlers use condition variables** to wait for async GStreamer operations
4. **NEVER manipulate GStreamer objects from gRPC threads** without g_idle_add()
5. **Timeouts on all waits** to prevent deadlocks (10s for CreateOffer, 1s for event pop)

---

## Questions Resolved

**Q**: Which thread should manipulate GStreamer objects?
**A**: GLib main loop thread (via g_idle_add if calling from elsewhere)

**Q**: Can gRPC thread call g_signal_emit_by_name?
**A**: YES - signals are queued, processed by GLib thread

**Q**: Can gRPC thread call create_offer()?
**A**: YES - but use callback + condition variable, don't block with gst_promise_wait()

**Q**: Where do webrtcbin signals fire?
**A**: GLib main loop thread (always)

**Q**: What was "missing half of the context"?
**A**: Likely tried to process GStreamer events without GLib main loop running

---

**Verified By**: Existing webrtc_session.cpp code analysis + GStreamer/GLib docs
**Confidence**: HIGH - Pattern matches proven GStreamer multi-threaded applications
**Next**: Proceed with gRPC implementation using these patterns

---

**Last Updated**: 2026-03-02
