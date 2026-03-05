# Audio Sending Issue Diagnosis

**Problem**: Siproxylin → Dino audio not working (bandwidth=0kbps)

---

## Session History

### Call: eece6699-084b-4146-9c11-337cda01a1d4 (March 5, ~14:00)
**Status**: opusenc encoding, rtpopuspay not receiving buffers

### Call: da7be3a5-bf56-41f1-819f-0d2d3f8cf98a (March 5, 16:43)
**Status**: Same - bandwidth=0kbps, 8 rtpopuspay log lines only

### Call: 1a56609f-0184-47d6-a2f3-4529765d0e29 (March 5, 17:27)
**Status**: Same symptoms after caps negotiation fix attempt

---

## Evidence

### ✅ Working Parts

1. **Pipeline creation**: Success
2. **opusenc encoding**: YES - continuously encoding audio
   ```
   0:00:21.764800 opusenc handle_frame
   0:00:21.764874 received buffer 0x62500011eea0 of 1920 bytes
   0:00:21.764915 encoding 960 samples (1920 bytes)
   0:00:21.765656 Output packet is 68 bytes
   ```
3. **rtpopuspay↔webrtcbin link**: Pads physically connected
   ```
   Pad peers: pay_src->peer=0x62900003e060, sink_0->peer=0x629000088b10
   ```
4. **ICE connection**: COMPLETED ✅
5. **Receiving audio (Dino→Siproxylin)**: WORKS ✅

### ❌ Broken Part

**opusenc → rtpopuspay**: Buffers NOT flowing!

- opusenc logs: Continuous encoding every ~20ms
- rtpopuspay logs: Only 8 lines total, no buffer handling
- bandwidth: 0kbps

---

## Root Cause Analysis

### Research Summary (March 5, 2026)

**From GStreamer Documentation & Examples:**
- Official webrtcbin examples add audio source BEFORE negotiation
- Quote: "Newly added elements will not automatically have their CAPS negotiated when dynamically added to a bin"
- webrtcbin test code: "Audio/video sources are added to the pipeline **before** `set_remote_description`"

**From GPT-5 Checklist:**
- Point #8: "If you attached source after the current SDP exchange, create a new offer so remote will enable receiving from you"
- Confirms: Caps negotiation problem when adding audio after answer

**From ./docs/CALLS/WEBRTCBIN-RECVONLY-DEEP-DIVE.md:**
- Lines 574-609: "codec-preferences are ONLY used when pad has no caps"
- "Once audio is linked, pad caps override everything!"
- We solved `a=sendrecv` but never implemented Step 6: "Connect audio pipeline AFTER"

### The Problem

**Current Flow:**
1. Create transceiver with codec-preferences (BEFORE set-remote-description) ✅
2. Answer has `a=sendrecv` ✅
3. Caps negotiate on sink_0 during answer creation ✅
4. **Link audio source AFTER answer** ← Audio pipeline added too late!
5. rtpopuspay tries to send data but sink_0 caps already negotiated
6. Caps mismatch → buffers blocked

**Why It Fails:**
- sink_0 already has negotiated caps (from answer SDP exchange)
- rtpopuspay has different caps (default RTP payload=96)
- GStreamer blocks data flow when caps don't match
- No automatic renegotiation happens

---

## Fix Attempts

### Attempt #1: Add Audio Before set-remote-description
**Date**: March 5, 17:04
**Call ID**: 06ce1beb-4d31-4c59-b380-fa63749e5773

**Result**: ❌ **BROKE RECEIVING AUDIO**
- We occupied sink_0 with our audio source
- webrtcbin also needs sink_0 for incoming stream
- Dino→Siproxylin audio stopped working

**Reverted immediately.**

### Attempt #2: Force Caps Negotiation After Linking
**Date**: March 5, 17:27
**Call ID**: 1a56609f-0184-47d6-a2f3-4529765d0e29

**Code** (`webrtc_session.cpp:683-713`):
```cpp
// Get negotiated caps from sink_0 (already negotiated during answer creation)
GstCaps *sink_caps = gst_pad_get_current_caps(webrtc_sink);
if (sink_caps) {
    gchar *caps_str = gst_caps_to_string(sink_caps);
    LOG_INFO("[WebRTCSession] sink_0 negotiated caps: {}", caps_str);
    g_free(caps_str);
}

// Link to webrtcbin
GstPad *pay_src = gst_element_get_static_pad(rtpopuspay, "src");
GstPadLinkReturn link_ret = gst_pad_link(pay_src, webrtc_sink);

// Force caps negotiation on the link we just made
if (sink_caps) {
    if (!gst_pad_set_caps(pay_src, sink_caps)) {
        LOG_WARN("[WebRTCSession] Failed to set caps on rtpopuspay src pad");
    } else {
        LOG_INFO("[WebRTCSession] ✓ Set negotiated caps on rtpopuspay");
    }
    gst_caps_unref(sink_caps);
}
```

**Result**: ❌ **Still bandwidth=0kbps**

**Why It Failed**: Unknown - need to check logs for:
- What caps sink_0 has
- Whether gst_pad_set_caps() succeeded
- Whether rtpopuspay rejected the caps

---

## Next Steps

### Option A: Check Logs From Latest Test
**Priority**: HIGH
**Call ID**: 1a56609f-0184-47d6-a2f3-4529765d0e29

Check drunk-call-service.log for:
1. "sink_0 negotiated caps: ..." - what caps were there?
2. "✓ Set negotiated caps on rtpopuspay" - did it succeed?
3. Any GStreamer errors about caps

### Option B: Use Caps Filter Instead of gst_pad_set_caps()
**Rationale**: gst_pad_set_caps() is deprecated, may not work

```cpp
// Add capsfilter between rtpopuspay and webrtcbin
GstElement *capsfilter = gst_element_factory_make("capsfilter", nullptr);
GstCaps *sink_caps = gst_pad_get_current_caps(webrtc_sink);
g_object_set(capsfilter, "caps", sink_caps, nullptr);

// Link: rtpopuspay → capsfilter → webrtcbin
gst_element_link_many(rtpopuspay, capsfilter, nullptr);
GstPad *capsfilter_src = gst_element_get_static_pad(capsfilter, "src");
gst_pad_link(capsfilter_src, webrtc_sink);
```

### Option C: Full Renegotiation
**Rationale**: GPT-5 point #8 - "create a new offer so remote will enable receiving from you"

**Concerns**:
- Jingle buffering complexity (./drunk_call_hook/protocol/jingle has state machine for sequencing)
- May not send second negotiation via XMPP if buffered
- Need to verify Jingle adapter handles mid-call renegotiation

**Implementation**:
1. Add flag to track when audio source is added
2. Modify `on_negotiation_needed()` to trigger new offer
3. Send offer via Jingle (check if state machine allows)
4. Dino answers → caps renegotiate with audio present

### Option D: Alternative Architecture - Create Audio During initialize()
**Rationale**: Match official GStreamer examples exactly

**Flow**:
1. In `initialize()`: Create full pipeline including audio source
2. In `set_remote_description()`: Just create transceiver with codec-preferences
3. Caps negotiate naturally with audio already present
4. No dynamic addition needed

**Concerns**:
- Might still create 2 transceivers (need to verify)
- Receiving audio might break (like Attempt #1)

---

## Critical Questions

1. **Does sink_0 have negotiated caps after answer?**
   - Check log: "sink_0 negotiated caps: ..."

2. **Did gst_pad_set_caps() succeed?**
   - Check log: "✓ Set negotiated caps on rtpopuspay"

3. **What payload does rtpopuspay use by default?**
   - Likely 96, but sink_0 expects 111 (from SDP)

4. **Can we see GST_DEBUG for rtpopuspay caps events?**
   - Need GST_DEBUG=rtpopuspay:6 to see caps negotiation

---

## Files Modified

- `drunk_call_service/src/webrtc_session.cpp:683-713` - Added caps negotiation attempt
- `docs/CALLS/AUDIO-SENDING-DIAGNOSIS.md` - This file

## Status: CRITICAL BUG FOUND - WebRTCSession::create_answer() NOT BEING CALLED

### Latest Finding (March 5, 18:00)
**Call ID**: 7b2e8ebd-14ae-47e9-8b6e-aea7a073b2fb

**Discovery:**
- gRPC `CreateAnswer` IS called (logs confirm)
- But `WebRTCSession::create_answer()` is NEVER called (no "Creating answer" log)
- SDP answer IS generated somehow ("CreateAnswer: SDP generated")
- This means gRPC layer is NOT calling `session->webrtc->create_answer()`!

**Evidence:**
- Binary has updated log: "Creating answer... (set is_outgoing_=false)"
- But this log NEVER appears
- No WebRTCSession logs at all during answer creation
- Only logs: "Initialized session" and GStreamer warnings

**Root Cause:**
The gRPC implementation is bypassing WebRTCSession::create_answer() entirely!
Need to check call_service_impl.cpp to see what it's actually calling.
