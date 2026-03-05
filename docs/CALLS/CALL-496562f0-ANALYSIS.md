# Call 496562f0 Analysis

**Date**: 2026-03-05
**Issue**: Dino stayed "Calling", never connected

---

## Your Questions

### 1. Was there only one transceiver created?

**YES** ✅

Code at `webrtc_session.cpp:364-404` creates exactly ONE transceiver in answer mode.

GST_DEBUG logs show only one RTP session (session 0).

### 2. Why did Dino keep saying "Calling"?

**ROOT CAUSE: No audio source pipeline exists.**

```cpp
// webrtc_session.cpp:581-629
bool WebRTCSession::create_pipeline() {
    webrtc_ = gst_element_factory_make("webrtcbin", "webrtc");

    LOG_INFO("Audio source will be added dynamically after offer processing");
    //        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    //        THIS NEVER HAPPENS!
}
```

**Evidence**:
- Bandwidth = 0kbps throughout call (no media flowing)
- ICE connected ✅ but no `audio_src` in GST_DEBUG logs
- SDP answer likely has `a=recvonly` (can't send without audio source)

**Dino's perspective**:
1. Sees SDP with `a=recvonly` → Won't send audio to us
2. Expects us to send audio → Nothing arrives
3. Stays in "Calling" state waiting for media

---

## The Fix Needed

Add audio source pipeline AFTER answer is created:

```cpp
void WebRTCSession::on_answer_created(GstPromise *promise) {
    // ... extract SDP answer ...

    // NEW: Add audio source NOW (after answer generated)
    if (!is_outgoing_) {
        create_audio_source_pipeline();  // ← MISSING FUNCTION
    }

    // ... callback with SDP ...
}
```

This was documented in WEBRTCBIN-RECVONLY-DEEP-DIVE.md but never implemented.

---

## Verify

1. Add SDP logging to see if answer has `a=recvonly` or `a=sendrecv`
2. Implement `create_audio_source_pipeline()`
3. Test: bandwidth should be >0kbps, Dino says "Connected"
