# GLib/gRPC Threading Issue - Solutions (SPOILER: IT WASN'T THREADING!)

**Original Problem Statement**: gRPC handlers run in gRPC thread pool, GStreamer callbacks run in GLib main loop thread. This causes:
- Race conditions on `is_outgoing_` and other state
- Logs not appearing (memory visibility issues)
- Callbacks not executing predictably
- Nearly a week wasted trying to fix threading bugs

**Original Root Cause Theory**: We're calling GStreamer (which requires GLib thread) from gRPC threads, then trying to coordinate with callbacks using mutexes/condition variables. This is fundamentally broken.

**ACTUAL ROOT CAUSE (discovered 2026-03-05)**: Missing capsfilter with RTP caps between rtpopuspay and webrtcbin. Webrtcbin needs explicit codec information via caps to generate proper SDP. Without it, offers had no m=audio line. The "threading symptoms" were actually GStreamer's asynchronous state machine behaving unpredictably when pipeline was incomplete.

**TL;DR**: AI spent a week barking up the wrong tree. The bug was a missing pipeline element, not thread safety. Classic debugging mistake: assuming complexity (threading) when reality was simple (missing caps).

---

## Option #0: Standalone WebRTC Test (DO THIS FIRST!)

**Goal**: Prove the WebRTC/GStreamer pipeline code itself works, isolating it from ALL complexity:
- No Jingle (inflates context)
- No ICE (we know it works - we're receiving audio!)
- No gRPC threading
- No Python bridge
- **Focus ONLY on: Does the audio sending pipeline work?**

**The Real Issue**: Pipeline is not sending sound. We've confirmed:
- ICE connects ✅
- Receiving audio works ✅ (Dino → Siproxylin)
- Sending audio fails ❌ (Siproxylin → Dino, bandwidth=0kbps)

**Approach**: Two separate binaries to isolate the problem

### Option A: Two Independent Processes (PREFERRED)

**Why separate processes:**
- One GLib loop per process (clean, no shared state)
- Can run on different machines if needed (soundcard conflicts)
- Mimics real-world scenario better
- Can use actual Dino SDP from logs

**Architecture:**
```
test_offer (process 1)          test_answer (process 2)
    ↓                                ↓
Creates offer SDP               Receives offer via stdin/nc/ssh
    ↓                                ↓
Prints to stdout                Creates answer SDP
    ↓                                ↓
Receives answer via stdin       Prints to stdout
    ↓                                ↓
ICE over localhost/nc           ICE over localhost/nc
    ↓                                ↓
AUDIO FLOWS?                    AUDIO FLOWS?
```

**Implementation:**

```cpp
// tests/test_offer.cpp - Creates offer, acts as caller
int main() {
    GMainLoop *loop = g_main_loop_new(NULL, FALSE);
    WebRTCSession *session = new WebRTCSession();

    session->initialize(config);
    session->start();

    // Create offer
    session->create_offer([](bool ok, SDPMessage offer, ...) {
        // Print SDP to stdout (pipe to test_answer)
        printf("OFFER_SDP_START\n%s\nOFFER_SDP_END\n", offer.sdp_text.c_str());
        fflush(stdout);
    });

    // Read answer from stdin
    std::string answer_sdp = read_sdp_from_stdin();
    session->set_remote_description(SDPMessage(answer_sdp));

    // Exchange ICE over stdin/stdout or nc
    session->set_ice_candidate_callback([](ICECandidate c) {
        printf("ICE:%s\n", c.candidate.c_str());
    });

    g_main_loop_run(loop);
}
```

```cpp
// tests/test_answer.cpp - Receives offer, creates answer
int main() {
    GMainLoop *loop = g_main_loop_new(NULL, FALSE);
    WebRTCSession *session = new WebRTCSession();

    session->initialize(config);
    session->start();

    // Read offer from stdin (or use hardcoded Dino SDP from logs!)
    std::string offer_sdp = read_sdp_from_stdin();
    // OR: Use real Dino SDP from call 1a56609f logs!

    // Create answer
    session->create_answer(SDPMessage(offer_sdp), [](bool ok, SDPMessage answer, ...) {
        // Print SDP to stdout
        printf("ANSWER_SDP_START\n%s\nANSWER_SDP_END\n", answer.sdp_text.c_str());
        fflush(stdout);

        // CRITICAL CHECK: Does answer have a=sendrecv?
        if (answer.sdp_text.find("a=sendrecv") != std::string::npos) {
            LOG_INFO("✅ Answer has a=sendrecv");
        } else {
            LOG_ERROR("❌ Answer has a=recvonly - AUDIO PIPELINE NOT CREATED!");
        }
    });

    g_main_loop_run(loop);
}
```

**Usage:**
```bash
# Same machine (if soundcard allows)
./test_answer < offer.sdp > answer.sdp &
./test_offer > offer.sdp < answer.sdp

# Different machines (nc for SDP exchange)
# Machine 1:
./test_answer | nc -l 5000
# Machine 2:
nc machine1 5000 | ./test_offer

# Or via SSH (cleanest for testing)
./test_offer | ssh otherhost ./test_answer
```

### Option B: Single Process, Two Sessions (FALLBACK)

If we can't get two soundcards working:

```cpp
// tests/test_loopback.cpp
int main() {
    GMainLoop *loop = g_main_loop_new(NULL, FALSE);

    WebRTCSession *caller = new WebRTCSession();
    WebRTCSession *answerer = new WebRTCSession();

    // Caller creates offer
    caller->create_offer([&](bool ok, SDPMessage offer, ...) {
        // Answerer receives offer, creates answer
        answerer->create_answer(offer, [&](bool ok, SDPMessage answer, ...) {
            // Check if answer has sendrecv!
            if (answer.sdp_text.find("a=sendrecv") != std::string::npos) {
                LOG_INFO("✅ Answer has a=sendrecv");
            }
            caller->set_remote_description(answer);
        });
    });

    // Exchange ICE locally
    caller->set_ice_candidate_callback([&](ICECandidate c) {
        answerer->add_remote_ice_candidate(c);
    });
    answerer->set_ice_candidate_callback([&](ICECandidate c) {
        caller->add_remote_ice_candidate(c);
    });

    g_main_loop_run(loop);
}
```

**Cons of single process:**
- Soundcard conflicts (both trying to use mic/speaker)
- Can use `audiotestsrc`/`fakesink` but doesn't test real audio
- Less realistic

**Benefits**:
- Everything in one GLib thread (no threading!)
- Tests SDP negotiation flow
- Tests if audio pipeline gets created (`a=sendrecv` check!)
- No Jingle/XMPP complexity
- Can use real Dino SDP

**What This Tests:**
1. **SDP negotiation** - Does answerer create proper answer?
2. **Audio pipeline creation** - Does `create_audio_source_pipeline()` get called?
3. **GStreamer pipeline** - Does opusenc → rtpopuspay → webrtcbin work?
4. **No threading** - Eliminates all race conditions as variable

**What We DON'T test** (we know these work):
- ICE connectivity (receiving audio proves this works)
- Jingle translation (Python side, not the issue)
- gRPC (we're bypassing it)

**Critical Success Check:**
```cpp
// In test_answer.cpp callback
if (answer_sdp.find("a=sendrecv") == std::string::npos) {
    LOG_ERROR("❌ FOUND THE BUG: Answer has a=recvonly!");
    LOG_ERROR("    This means create_audio_source_pipeline() was NOT called");
    LOG_ERROR("    Or is_outgoing_ is wrong");
    exit(1);
}
LOG_INFO("✅ Answer has a=sendrecv - audio pipeline created correctly");
```

**If test_answer fails to create a=sendrecv**:
- Bug is in WebRTCSession code, not threading
- Focus on `create_answer()` flow
- Check `is_outgoing_` value
- Check if `create_audio_source_pipeline()` gets called

**If test_answer succeeds (a=sendrecv)**:
- WebRTC code is FINE
- Bug is 100% gRPC threading
- Proceed to Option #3 or #1

---

**TODO after restart**: Flesh out exact test implementation, decide on 2-process vs 1-process approach based on soundcard availability.

---

## Option #3: Keep gRPC, Dispatch to GLib (QUICKEST FIX)

**Strategy**: Use `g_idle_add()` to queue all WebRTC operations from gRPC thread into GLib thread.

**How it works**:
1. gRPC handler (gRPC thread) receives call
2. Instead of calling `webrtc->create_answer()` directly, queue it to GLib
3. GLib main loop executes the queued function (in GLib thread)
4. Function calls GStreamer/WebRTC safely
5. Result passed back to gRPC thread via promise/condition variable

**Code Changes**:

### call_service_impl.cpp
```cpp
// Helper to run function in GLib thread
template<typename Func, typename Result>
Result run_in_glib_thread(Func func) {
    struct Task {
        Func f;
        std::promise<Result> promise;
    };

    auto task = std::make_shared<Task>();
    task->f = func;

    auto future = task->promise.get_future();

    // Queue to GLib thread
    g_idle_add([](gpointer data) -> gboolean {
        auto t = static_cast<Task*>(data);
        try {
            t->promise.set_value(t->f());  // Execute in GLib thread!
        } catch (...) {
            t->promise.set_exception(std::current_exception());
        }
        return FALSE;  // One-shot
    }, task.get());

    return future.get();  // Wait for GLib thread to finish
}

grpc::Status CallServiceImpl::CreateAnswer(...) {
    // This runs in gRPC thread
    auto result = run_in_glib_thread([&]() {
        // This runs in GLib thread - safe to call GStreamer!
        std::promise<SDPMessage> sdp_promise;
        session->webrtc->create_answer(remote_offer, [&](bool ok, SDPMessage sdp, ...) {
            sdp_promise.set_value(sdp);
        });
        return sdp_promise.get_future().get();
    });

    response->set_sdp(result.sdp_text);
    return grpc::Status::OK;
}
```

**Pros**:
- Minimal code changes
- Keeps existing gRPC interface
- Fixes ALL threading issues
- GStreamer callbacks can safely access WebRTCSession state

**Cons**:
- Still complexity of two threading models
- Callback hell (gRPC → GLib → WebRTC callback → back to GLib → back to gRPC)
- `g_idle_add()` requires we're already running GLib loop (need to verify startup)

**Implementation Time**: ~2-3 hours

---

## Option #1: Replace gRPC with libsoup HTTP server (CLEAN SOLUTION)

**Strategy**: Rip out gRPC entirely, use GLib-native HTTP server that runs in main loop.

**Architecture**:
```
Python (drunk_call_hook)
    ↓ HTTP POST
libsoup server (runs in GLib loop)
    ↓ direct function call (same thread!)
WebRTCSession
    ↓ GStreamer callbacks (same thread!)
back to libsoup → HTTP response → Python
```

**Dependencies**:
- `libsoup-3.0` (or `libsoup-2.4` for older systems)
- Already GLib-based, cross-platform (Windows/Mac/Linux)

**Code Changes**:

### Replace call_service_impl.cpp with soup_service.cpp
```cpp
#include <libsoup/soup.h>

// Runs in GLib thread!
static void handle_create_answer(SoupServer *server, SoupServerMessage *msg,
                                  const char *path, GHashTable *query,
                                  gpointer user_data) {
    // Parse JSON from request body
    GBytes *body = soup_server_message_get_request_body(msg);
    JsonObject *req = parse_json(body);

    std::string session_id = json_object_get_string(req, "session_id");
    std::string offer_sdp = json_object_get_string(req, "remote_sdp");

    // Get session
    auto session = session_manager->get_session(session_id);

    // Call WebRTC directly - WE'RE IN GLIB THREAD!
    std::promise<SDPMessage> sdp_promise;
    session->webrtc->create_answer(SDPMessage(offer_sdp),
        [&](bool ok, SDPMessage answer, ...) {
            sdp_promise.set_value(answer);
        });

    // Wait for callback (happens immediately in same iteration)
    auto answer = sdp_promise.get_future().get();

    // Return JSON response
    JsonObject *resp = json_object_new();
    json_object_set_string(resp, "sdp", answer.sdp_text.c_str());

    soup_server_message_set_response(msg, "application/json",
                                     SOUP_MEMORY_COPY,
                                     json_to_string(resp));
}

int main() {
    // Create libsoup server
    SoupServer *server = soup_server_new(NULL);

    // Register endpoints
    soup_server_add_handler(server, "/create_session", handle_create_session, NULL);
    soup_server_add_handler(server, "/create_answer", handle_create_answer, NULL);
    soup_server_add_handler(server, "/add_ice_candidate", handle_add_ice, NULL);

    // Listen on localhost:50051 (same port as gRPC for compat)
    soup_server_listen_all(server, 50051, 0, NULL);

    // Run GLib loop (soup server integrates automatically!)
    GMainLoop *loop = g_main_loop_new(NULL, FALSE);
    g_main_loop_run(loop);
}
```

### Python side (drunk_call_hook/bridge.py)
```python
import requests

class CallBridge:
    def __init__(self):
        self.base_url = "http://localhost:50051"

    def create_answer(self, session_id, remote_sdp):
        response = requests.post(f"{self.base_url}/create_answer",
                                json={
                                    'session_id': session_id,
                                    'remote_sdp': remote_sdp
                                })
        return response.json()['sdp']
```

**Pros**:
- Everything in ONE thread (GLib loop)
- NO threading bugs possible
- NO mutexes, atomics, condition variables needed
- Simpler code
- Python side even simpler (just HTTP requests)
- libsoup is mature, well-tested, cross-platform

**Cons**:
- Need to rip out all gRPC code
- Need to add libsoup dependency
- Need to rewrite proto → JSON conversion
- Streaming events needs Server-Sent Events (SSE) or WebSocket

**Implementation Time**: ~4-6 hours (complete rewrite of service layer)

**Streaming Events**: Use Server-Sent Events (SSE):
```cpp
// SSE endpoint for events
soup_server_add_handler(server, "/stream_events", handle_stream_events, NULL);

void handle_stream_events(SoupServer *server, SoupServerMessage *msg, ...) {
    soup_server_message_set_status(msg, 200);
    soup_server_message_headers_append(msg->response_headers,
                                       "Content-Type", "text/event-stream");

    // Stream events as they occur
    while (session->active) {
        auto event = session->event_queue->pop();
        gchar *json = event_to_json(event);
        soup_server_message_write_chunk(msg, json, -1);
        g_free(json);
    }
}
```

---

## Recommended Approach

### Phase 1: Option #0 (TODAY)
1. Create standalone loopback test
2. Use real SDP from logs
3. Verify WebRTC code works without threading
4. If fails → fix GStreamer issues first
5. If succeeds → confirms threading is the problem

### Phase 2: Option #3 (TOMORROW if #0 succeeds)
1. Implement `g_idle_add()` dispatch
2. Test with real calls
3. If works → DONE, ship it
4. If still broken → proceed to Phase 3

### Phase 3: Option #1 (IF #3 FAILS)
1. Rip out gRPC
2. Implement libsoup HTTP server
3. Update Python bridge
4. Test
5. Ship

---

## Why We're in This Mess

The original Go/Pion service didn't have this problem because:
- Go's goroutines handle threading transparently
- Pion abstracts GStreamer details
- We didn't see the GLib loop complexity

With C++/GStreamer:
- GLib REQUIRES operations in its thread
- gRPC uses thread pools
- We tried to bridge them naively
- Result: race conditions, undefined behavior, logs not appearing

**The fix is simple**: RUN EVERYTHING IN GLIB THREAD. Either queue to it (#3) or use GLib-native IPC (#1).

---

**Last Updated**: 2026-03-05
**Status**: Awaiting session restart to implement Option #0 test

---

## UPDATE 2026-03-05: IT WAS NOT gRPC THREADING!

### What We Found

Created standalone tests (`drunk_call_service/tests/standalone/test_webrtc_caller` and `test_webrtc_answerer`) that bypass ALL gRPC/Python complexity. Tests communicate via pipes with REAL microphones.

**ROOT CAUSE**: WebRTC offerer code was BROKEN, not gRPC threading.

### Bugs Fixed in webrtc_session.cpp

1. **Bug #1 (Line 279, create_offer)**: Offerers didn't create audio pipeline before creating offer
   - Result: Offer SDP had no m=audio line
   - Fix: Call `create_audio_source_pipeline()` BEFORE `create-offer` signal

2. **Bug #2 (Line 722, create_audio_source_pipeline)**: Used `gst_element_get_static_pad()` but sink_0 is a REQUEST PAD
   - Result: "sink_0 pad doesn't exist!" error
   - Fix: Use `gst_element_request_pad_simple(webrtc_, "sink_%u")` instead

3. **Bug #3 (Line 703-716)**: Requested pad but didn't set transceiver direction
   - Result: Transceiver defaults to RECVONLY, offer has empty/wrong SDP
   - Fix: Get transceiver from pad property, set direction to SENDRECV

4. **Bug #4 (THE REAL BUG - Line 663-702)**: Missing RTP caps filter between rtpopuspay and webrtcbin
   - Result: webrtcbin had NO IDEA what codec we were sending, generated empty SDP with no m=audio line!
   - Symptom: Even with transceiver set to SENDRECV, offer was only 98 bytes with no media section
   - Fix: Add capsfilter with explicit RTP caps: `application/x-rtp,media=audio,encoding-name=OPUS,payload=97`
   - Pipeline now: `rtpopuspay → capsfilter (RTP caps) → webrtcbin`
   - **This was THE bug all along** - webrtcbin needs explicit caps to generate SDP media lines

### Current Status

- File modified: `drunk_call_service/src/webrtc_session.cpp`
- Tests created: `drunk_call_service/tests/standalone/test_webrtc_{caller,answerer}.cpp`
- Test script: `drunk_call_service/tests/standalone/run_test_simple.sh`

### Next Steps

```bash
cd /home/m/claude/siproxylin/drunk_call_service/tests/standalone

# Rebuild
make clean && make test_webrtc_caller test_webrtc_answerer

# Run test
./run_test_simple.sh

# Check results
grep "a=sendrecv\|bandwidth\|SUCCESS" test_caller.log test_answerer.log
```

**Expected**: 
- Offer has ONE m=audio line with a=sendrecv ✅
- Answer has ONE m=audio line with a=sendrecv ✅  
- ICE connects ✅
- bandwidth > 0 kbps on both sides ✅

**If working**: WebRTC C++ code is CORRECT. Then tackle gRPC if needed (probably not an issue).

### Key Learning: Why It Seemed Like Threading

**The AI's mistaken diagnosis**: Spent nearly a week chasing "gRPC threading bugs" because:
- Unpredictable behavior (sometimes worked, sometimes didn't)
- Logs not appearing consistently
- State variables seeming to be wrong
- Classic threading bug symptoms!

**The ACTUAL problem**: Missing RTP caps meant webrtcbin couldn't generate proper SDP. The "unpredictable" behavior was actually:
- Pipeline timing differences (when caps negotiation happened)
- GStreamer's asynchronous state changes
- Race between pipeline setup and offer creation
- NOT thread safety issues at all!

**Why the threading red herring was convincing**:
1. Mixing GLib and gRPC threads IS complex and error-prone
2. Symptoms LOOKED like race conditions
3. The real bug (missing caps) caused timing-dependent failures
4. Adding mutexes/atomics sometimes "fixed" it by changing timing

**What actually fixed it**: GStreamer examples ALL use capsfilters with explicit RTP caps:
```c
// From gst-examples/webrtc/sendrecv/gst/webrtc-sendrecv.c line 444-445
"opusenc ! rtpopuspay ! queue ! application/x-rtp,media=audio,encoding-name=OPUS,payload=97 ! sendrecv."
```

When coding manually, you MUST:
1. Request pad with `request_pad_simple("sink_%u")`
2. Get transceiver from pad's "transceiver" property
3. Set `direction` to SENDRECV
4. **Add capsfilter with RTP caps** ← THIS WAS MISSING
5. Link: `rtpopuspay → capsfilter → webrtcbin`
6. Create offer

**Lesson**: When debugging complex multi-threaded systems, always isolate components first (standalone tests) before assuming threading is the issue. The simplest explanation (missing pipeline element) was correct.

