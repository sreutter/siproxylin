# WebRTCBin RECVONLY Deep Dive

## Problem Statement

When creating SDP answers for incoming calls, webrtcbin generates `a=recvonly` instead of `a=sendrecv`, causing the remote peer (Dino) to not send audio to us. The peer stays in "Calling" state instead of connecting.

**Symptom**:
```sdp
m=audio 9 UDP/TLS/RTP/SAVPF 111
a=rtpmap:111 OPUS/48000/2
a=recvonly  ← WRONG! Should be a=sendrecv
```

---

## Investigation Timeline

### Session 23: Initial Discovery

**Finding**: Transceiver has `mline=4294967295` (UNASSIGNED) after `set-remote-description`.

**Evidence**:
```
Transceiver 0: mline=4294967295, direction=4 (SENDRECV)
Transceiver has sender: ✓
Codec-preferences: application/x-rtp, media=audio, encoding-name=OPUS, clock-rate=48000, encoding-params=2
```

**Root Cause**: webrtcbin cannot match our manually-created transceiver to the remote offer's m-line.

**Source Code Reference** (`gstwebrtcbin.c:4562-4571`):
```c
if (rtp_trans) {
    answer_dir = rtp_trans->direction;  // Uses SENDRECV
} else {
    // No matching transceiver found!
    answer_dir = GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_RECVONLY;
    GST_WARNING_OBJECT (webrtc, "did not find compatible transceiver...");
}
```

---

## Deep Analysis of GStreamer WebRTCBin

### How WebRTCBin Creates SDP Answers

**Function**: `_create_answer_task()` in `gstwebrtcbin.c:4293`

**Flow for each m-line in offer**:

1. **Find existing transceiver** (lines 4521-4559):
   ```c
   for (j = 0; j < webrtc->priv->transceivers->len; j++) {
       rtp_trans = g_ptr_array_index(webrtc->priv->transceivers, j);

       // Get transceiver caps
       trans_caps = _find_codec_preferences(webrtc, rtp_trans, j, error);

       // Try intersection
       answer_caps = gst_caps_intersect(offer_caps, trans_caps);

       if (answer_caps && !gst_caps_is_empty(answer_caps)) {
           // MATCH FOUND!
           break;
       }
   }
   ```

2. **Determine direction** (lines 4562-4571):
   ```c
   if (rtp_trans) {
       answer_dir = rtp_trans->direction;  // ✅ Uses our SENDRECV
   } else {
       answer_dir = GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_RECVONLY;  // ❌ Problem!
       GST_WARNING_OBJECT (webrtc, "did not find compatible transceiver...");
   }
   ```

### How `_find_codec_preferences` Works

**Function**: `gstwebrtcbin.c:1943-2062`

**Logic**:

1. **Check manual codec-preferences** (lines 1959-1964):
   ```c
   GST_OBJECT_LOCK (rtp_trans);
   if (rtp_trans->codec_preferences) {
       codec_preferences = gst_caps_ref (rtp_trans->codec_preferences);
   }
   GST_OBJECT_UNLOCK (rtp_trans);
   ```

2. **Find pad for transceiver** (lines 1971-1988):
   - For SENDRECV: Look for sink pad (our sender)
   - If not found, try source pad

3. **Query caps from pad** (lines 1990-2026):
   ```c
   if (pad) {
       if (pad->received_caps) {
           caps = gst_caps_ref(pad->received_caps);
       } else {
           caps = _query_pad_caps(webrtc, rtp_trans, pad, filter, error);
       }
   }
   ```

4. **Return result** (lines 2054-2059):
   ```c
   if (!ret) {
       if (codec_preferences)
           ret = gst_caps_ref(codec_preferences);  // Use manual preferences
       else if (trans->last_retrieved_caps)
           ret = gst_caps_ref(trans->last_retrieved_caps);  // Use cached
   }
   ```

**Key Insight**: If transceiver has no `codec-preferences` set AND pad caps are not negotiated yet, returns **NULL**, causing caps intersection to fail!

---

## Attempted Fixes

### Fix 1: Manual Transceiver Direction Setting (❌ Failed)

**Approach**: Set transceiver direction to SENDRECV before/after `set-remote-description`.

**Code** (Session 22):
```cpp
GArray* transceivers = nullptr;
g_signal_emit_by_name(webrtc_, "get-transceivers", &transceivers);
for (each transceiver) {
    g_object_set(trans, "direction", GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_SENDRECV, NULL);
}
```

**Result**: Still `a=recvonly`

**Why it failed**: Direction is irrelevant if transceiver isn't matched to the offer m-line in the first place.

---

### Fix 2: Remove Manual Codec-Preferences (❌ Failed)

**Approach**: Follow official GStreamer examples - let caps flow naturally from pipeline, don't set codec-preferences manually.

**Changes**:
- Removed all manual codec-preferences setting
- Removed transceiver direction forcing

**Result**: Still `a=recvonly`

**Why it failed**: Without codec-preferences, `_find_codec_preferences` returns NULL (caps not negotiated yet on pad), so intersection fails.

---

### Fix 3: Use `gst_element_request_pad` with Caps (❌ Partial)

**Discovery**: Found advanced pad request API!

**GStreamer API**:
```c
GstPad* gst_element_request_pad(GstElement *element,
                                GstPadTemplate *templ,
                                const gchar *name,
                                const GstCaps *caps);  // ← Advanced parameter
```

**Code** (`gstwebrtcbin.c:8120-8123`):
```c
if (!trans) {
    trans = _create_webrtc_transceiver (webrtc,
            GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_SENDRECV,  // ✅ Creates SENDRECV
            -1,
            webrtc_kind_from_caps (caps),  // Uses caps for kind
            NULL);  // ← But NO codec-preferences set!
}
```

**Result**: Transceiver created with SENDRECV, but still `a=recvonly` in answer.

**Why it failed**: The `caps` parameter only determines transceiver **kind** (audio/video), NOT codec-preferences!

---

### Fix 4: Explicit Codec-Preferences Setting (❌ Failed)

**Approach**: After requesting pad, manually set codec-preferences on the newly created transceiver.

**Code**:
```cpp
// Request pad with caps
GstPad *webrtc_sink = gst_element_request_pad(webrtc_, templ, nullptr, caps);

// Get transceivers
GArray* transceivers = nullptr;
g_signal_emit_by_name(webrtc_, "get-transceivers", &transceivers);

// Set codec-preferences on last transceiver (the one we just created)
GstWebRTCRTPTransceiver* trans =
    g_array_index(transceivers, GstWebRTCRTPTransceiver*, transceivers->len - 1);
g_object_set(trans, "codec-preferences", caps, nullptr);
```

**Caps used**:
```cpp
GstCaps *caps = gst_caps_new_simple("application/x-rtp",
    "media", G_TYPE_STRING, "audio",
    "encoding-name", G_TYPE_STRING, "OPUS",
    "payload", G_TYPE_INT, 97,  // ← Fixed payload
    "clock-rate", G_TYPE_INT, 48000,
    nullptr);
```

**Result**: Still `a=recvonly`

**Why it failed**: Payload mismatch! Dino uses `payload=111`, we specified `payload=97`. Caps intersection fails.

---

### Fix 5: Remove Fixed Payload from Codec-Preferences (❌ Still Testing)

**Approach**: Payload type is negotiated, not a codec property. Don't specify it in codec-preferences.

**Code**:
```cpp
GstCaps *caps = gst_caps_new_simple("application/x-rtp",
    "media", G_TYPE_STRING, "audio",
    "encoding-name", G_TYPE_STRING, "OPUS",
    // No payload specified - accepts any
    "clock-rate", G_TYPE_INT, 48000,
    nullptr);
```

**Expected**: Our caps should intersect with Dino's offer caps.

**Dino's offer caps** (from SDP):
```
a=rtpmap:111 opus/48000/2
```

Which becomes:
```
application/x-rtp, media=audio, payload=111, clock-rate=48000,
encoding-name=OPUS, encoding-params=2
```

**Intersection**:
```
Our caps:      media=audio, encoding-name=OPUS, clock-rate=48000
Dino's caps:   media=audio, encoding-name=OPUS, clock-rate=48000, payload=111, encoding-params=2
Result:        media=audio, encoding-name=OPUS, clock-rate=48000, payload=111, encoding-params=2 ✅
```

**Current Status**: **Still `a=recvonly`** despite correct caps!

**Logs show**:
- `[WebRTCSession] Set codec-preferences on transceiver (OPUS 48kHz)` ✅
- No GStreamer WARNING about "did not find compatible transceiver" (!)
- Answer still has `a=recvonly`

**Hypothesis**: There might be another issue beyond caps matching. Possibilities:
1. Caps matching works, but transceiver's direction is being reset somewhere
2. Caps are matched, but wrong transceiver is used for answer
3. Timing issue - caps not propagated before `create-answer` is called
4. Additional caps fields required (e.g., `encoding-params`)

---

## Official GStreamer Pattern Analysis

### webrtc-sendrecv.c Example

**Pipeline** (lines 432-445):
```c
pipe1 = gst_parse_launch(
    "webrtcbin bundle-policy=max-bundle name=sendrecv " STUN_SERVER
    "audiotestsrc is-live=true wave=red-noise ! audioconvert ! audioresample ! "
    "queue ! opusenc ! rtpopuspay ! "
    "queue ! " RTP_CAPS_OPUS "97 ! sendrecv. ", &error);
```

Where:
```c
#define RTP_CAPS_OPUS "application/x-rtp,media=audio,encoding-name=OPUS,payload="
```

**Key Differences from Our Code**:
1. Uses `audiotestsrc` (instant caps) vs our `pulsesrc` (slow caps negotiation)
2. Uses pipeline string with `sendrecv.` shorthand vs explicit pad request
3. Specifies payload in capsfilter (for pipeline flow) but NOT in codec-preferences
4. Pipeline created ONCE, used for both offer and answer

**Answer Creation** (lines 618-624):
```c
static void on_offer_set(GstPromise *promise, gpointer user_data) {
    gst_promise_unref(promise);
    promise = gst_promise_new_with_change_func(on_answer_created, NULL, NULL);
    g_signal_emit_by_name(webrtc1, "create-answer", NULL, promise);
}
```

**Pattern**: Simple, direct call to `create-answer` after offer is set. No transceiver manipulation.

---

## Key Questions Remaining

### Q1: Why doesn't caps intersection work?

**Our codec-preferences**:
```
application/x-rtp, media=audio, encoding-name=OPUS, clock-rate=48000
```

**Dino's offer**:
```
application/x-rtp, media=audio, payload=111, clock-rate=48000, encoding-name=OPUS, encoding-params=2
```

**Expected intersection**: Should succeed (our caps are more generic).

**Actual**: Unknown - no GStreamer warnings logged, but still `a=recvonly`.

### Q2: Is the transceiver being matched?

**Evidence**:
- No "did not find compatible transceiver" warning in latest logs
- But answer still has `a=recvonly`

**Possible explanations**:
1. Transceiver IS matched, but direction gets reset to RECVONLY elsewhere
2. Transceiver NOT matched, but warning suppressed/not logged at current debug level
3. Multiple transceivers exist, wrong one gets used

### Q3: When are caps negotiated?

**Timeline** (from logs):
```
12:27:59.576 - Pipeline created, codec-preferences set
12:27:59.596 - CreateAnswer called
12:27:59.887 - Offer set, creating answer (291ms after CreateAnswer)
```

**Question**: At 12:27:59.887 when `_find_codec_preferences` is called, are the pad caps negotiated yet?

**Hypothesis**: If `codec-preferences` are set correctly, it shouldn't matter - `_find_codec_preferences` should return the manual preferences (lines 2055-2056).

---

## Diagnostic Log Levels

**Current GST_DEBUG**: Appears to be at default level (no detailed webrtcbin logs).

**Needed for diagnosis**:
```bash
GST_DEBUG=webrtcbin:7,rtpbin:5 ./drunk-call-service-linux
```

This would show:
- Caps intersection attempts
- Transceiver matching details
- codec-preferences retrieval

---

## Next Steps

### 1. Enable Detailed Logging

Set `GST_DEBUG=webrtcbin:7` to see:
- `_find_codec_preferences` calls
- Caps intersection results
- Transceiver matching decisions

### 2. Create Minimal Test Case

Create standalone C program that:
1. Creates webrtcbin with audio pipeline
2. Takes Dino's SDP offer as input
3. Calls create-answer
4. Prints result

Benefits:
- Fast iteration (compile in seconds)
- Isolated from surrounding code
- Can add debug logging directly
- Can test different approaches quickly

### 3. Alternative Approaches to Try

**Approach A**: Don't pre-create transceiver for answerer
- Create webrtcbin without pipeline
- Call `set-remote-description(offer)`
- Let webrtcbin create transceiver from offer
- Dynamically link audio pipeline to the created transceiver
- Call `create-answer`

**Approach B**: Use `add-transceiver` signal explicitly
- Use `add-transceiver` signal instead of implicit creation
- Set codec-preferences immediately
- Ensure only ONE transceiver exists

**Approach C**: Match official example exactly
- Use `audiotestsrc` instead of `pulsesrc`
- Use pipeline string syntax instead of manual linking
- Test if issue persists

---

## Code References

### Key Files
- **GStreamer WebRTC**: `/drunk_call_service/tmp/gst-plugins-bad1.0-1.22.0/ext/webrtc/gstwebrtcbin.c`
- **Our Implementation**: `/drunk_call_service/src/webrtc_session.cpp`

### Critical Functions
- `_create_answer_task()` - Line 4293: Creates SDP answer
- `_find_codec_preferences()` - Line 1943: Gets transceiver caps for matching
- `gst_webrtc_bin_request_new_pad()` - Line 7989: Handles pad request, creates transceiver

### Critical Code Sections in Our Implementation
- Pipeline creation: `webrtc_session.cpp:460-610`
- Codec-preferences setting: `webrtc_session.cpp:567-583`
- Answer creation: `webrtc_session.cpp:202-220`
- Answer callback: `webrtc_session.cpp:1045-1070`

---

## Dino's SDP Offer (Reference)

```sdp
v=0
o=- 0 0 IN IP4 0.0.0.0
s=-
t=0 0
a=msid-semantic: WMS *
m=audio 9 UDP/TLS/RTP/SAVPF 111 112 113 114 0 8
c=IN IP4 0.0.0.0
a=rtcp:9 IN IP4 0.0.0.0
a=ice-ufrag:HyN7
a=ice-pwd:xr3jGnD7qB5kaJSOTzfJ87
a=ice-options:trickle
a=fingerprint:sha-256 48:76:4D:FD:20:67:6B:66:B3:22:C7:EA:E4:8C:7A:E6:6E:EA:12:03:E2:5D:17:13:B3:34:EA:AD:E7:72:3B:2B
a=setup:actpass
a=mid:audio
a=sendrecv  ← Peer wants bidirectional!
a=rtcp-mux
a=rtpmap:111 opus/48000/2
a=rtpmap:112 speex/32000
a=rtpmap:113 speex/16000
a=rtpmap:114 speex/8000
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=fmtp:111 useinbandfec=1
```

**Payload types offered**:
- **111**: OPUS/48000/2 (stereo) ← We want this
- 112: speex/32000
- 113: speex/16000
- 114: speex/8000
- 0: PCMU/8000
- 8: PCMA/8000

---

## Our SDP Answer (Actual)

```sdp
v=0
o=- 0 0 IN IP4 0.0.0.0
s=-
t=0 0
m=audio 9 UDP/TLS/RTP/SAVPF 111
c=IN IP4 0.0.0.0
a=ice-ufrag:tdb99avrAWMJAAN7rMsooI58eRldG8Mz
a=ice-pwd:eALeofs2/hG7pWIdktQR7cfcLblcVjvZ
a=mid:audio
a=rtcp-mux
a=setup:active
a=rtpmap:111 OPUS/48000/2  ← Codec matched correctly!
a=fmtp:111 useinbandfec=1
a=recvonly  ← WRONG! Should be a=sendrecv
```

**Observations**:
- Payload 111 correctly selected ✅
- OPUS codec correctly negotiated ✅
- Direction is WRONG ❌

This confirms: **Caps matching works** (OPUS 111 selected), but transceiver **direction negotiation fails**.

---

## Hypothesis: Direction Override After Caps Match

**New Theory**: WebRTCBin might be matching our transceiver correctly, but then overriding the direction based on some other logic.

**Evidence**:
- No "did not find compatible transceiver" warning
- Correct payload selected (111)
- But still `a=recvonly`

**Possible causes**:
1. `_update_transceiver_from_sdp_media` (called after SDP generation) sets direction to RECVONLY
2. Transceiver's `current-direction` vs `direction` property mismatch
3. Pad not connected → sender not active → defaults to RECVONLY

**Next investigation**: Check if transceiver has a connected sender pad at the time of answer creation.

---

## Conclusion

After 5+ attempted fixes and deep source code analysis, the root cause remains elusive. The issue appears to be:

1. ✅ **NOT** manual transceiver direction setting (doesn't help)
2. ✅ **NOT** payload type mismatch (fixed)
3. ✅ **NOT** caps intersection failure (OPUS 111 selected correctly)
4. ❓ **POSSIBLY** timing issue with pad caps negotiation
5. ❓ **POSSIBLY** missing sender pad connection
6. ❓ **POSSIBLY** direction override after caps matching

**Critical need**: Detailed GStreamer debug logs + isolated test case to iterate quickly.

<USER>
After some battle with test code Claude came back with a promising flow:
  The Working Approach

  // 1. Create transceiver with general OPUS caps (no fixed payload)
  GstCaps *caps = gst_caps_new_simple("application/x-rtp",
      "media", G_TYPE_STRING, "audio",
      "encoding-name", G_TYPE_STRING, "OPUS",
      "clock-rate", G_TYPE_INT, 48000,
      NULL);  // No payload!

  // 2. Request pad with caps (creates AUDIO transceiver)
  GstPad *sink = gst_element_request_pad(webrtc, templ, NULL, caps);

  // 3. Set codec-preferences on the transceiver
  g_object_set(transceiver, "codec-preferences", caps, NULL);

  // 4. DON'T link audio pipeline yet!

  // 5. Set remote description → create answer → SUCCESS!

  // 6. Connect audio pipeline AFTER for actual streaming
</USER>

---

## ✅ SOLUTION FOUND (Session 2026-03-05)

### Working Test Code

Created isolated test case (`drunk_call_service/tests/test_webrtc_answer.c`) that successfully generates `a=sendrecv`!

**Test results:**
- ✅ Only **1 transceiver** created (not 2)
- ✅ Answer SDP has **`a=sendrecv`** (not `a=recvonly`)
- ✅ Transceiver matched to offer via codec-preferences

### Root Causes Identified

1. **encoding-name must be UPPERCASE**
   - SDP has: `a=rtpmap:111 opus/48000/2` (lowercase)
   - GStreamer expects: `encoding-name=(string)OPUS` (UPPERCASE)
   - **Fix:** Use `g_ascii_strup()` when parsing SDP

2. **codec-preferences overridden by pad caps**
   - When audio pipeline is linked BEFORE answer creation, `_find_codec_preferences()` returns **pad caps** (with `payload=96` from rtpopuspay) instead of manual codec-preferences
   - Pad caps include session-specific fields (`ssrc`, `timestamp-offset`) that fail intersection
   - **Fix:** Create transceiver with codec-preferences but **DON'T link audio until after answer**

3. **Fixed payload in caps causes intersection failure**
   - Specifying `payload=97` in codec-preferences fails when offer has `payload=111`
   - Payload is negotiated, not a codec property
   - **Fix:** Don't specify payload in codec-preferences

### The Working Pattern

```c
// 1. Parse SDP offer to extract codec info
GstCaps *codec_caps = parse_audio_codec_from_offer(offer_sdp);
// Result: encoding-name=OPUS (uppercase!), clock-rate=48000, encoding-params=2
//         NO payload field!

// 2. Request pad to create transceiver (audio NOT linked yet!)
GstPad *sink = gst_element_request_pad(webrtc, templ, NULL, NULL);

// 3. Set codec-preferences on transceiver
g_object_set(transceiver, 
    "direction", GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_SENDRECV,
    "codec-preferences", codec_caps, 
    NULL);

// 4. Set remote description
g_signal_emit_by_name(webrtc, "set-remote-description", offer, promise);

// 5. Create answer → SUCCESS! (a=sendrecv)
g_signal_emit_by_name(webrtc, "create-answer", NULL, promise);

// 6. (Audio pipeline would be connected after for actual streaming)
```

**Key insight:** Codec-preferences are ONLY used when pad has no caps. Once audio is linked, pad caps override everything!

---

## 🔧 Implementation in Real Code (IN PROGRESS)

### Changes Made to `webrtc_session.cpp`:

1. **Added `parse_audio_codec_from_offer()` helper function**
   - Parses first audio m-line from SDP offer
   - Extracts encoding-name, clock-rate, encoding-params
   - **Uppercases encoding-name** (critical!)
   - Creates caps WITHOUT fixed payload

2. **Simplified `create_pipeline()`**
   - Removed all audio source pipeline creation
   - Now only creates webrtcbin + connects signals
   - Audio will be added dynamically later (not yet implemented)

3. **Modified `set_remote_description()`**
   - When answering (receiving offer), now:
     - Parses codec from offer
     - Creates transceiver with codec-preferences
     - Sets direction to SENDRECV
     - **Does this BEFORE calling set-remote-description**

4. **Cleaned up `on_offer_set_for_answer()`**
   - Removed all BS transceiver manipulation code
   - Now just calls create-answer (transceiver already configured)

5. **Removed ~200 lines of failed attempt code**
   - Deleted manual direction forcing
   - Deleted old capsfilter + audio pipeline setup
   - Deleted device selection (temporarily, for testing)

### Status: **NOT COMPILED/TESTED YET**

Code refactoring completed but:
- ❌ Not compiled
- ❌ Not tested
- ⚠️ Audio source pipeline creation not yet implemented
- ⚠️ No audio will flow yet (need to add pipeline after answer)

### Next Steps:

1. ✅ Compile the code (user will do this)
2. ✅ Test incoming call - verify answer SDP has `a=sendrecv`
3. ⚠️ Add audio source pipeline creation (after answer or dynamically)
4. ✅ Test actual audio flow
5. ✅ Re-enable device selection
6. ✅ Test with real Dino/XMPP calls

---

## Files Changed:

- `drunk_call_service/src/webrtc_session.cpp` - Main implementation
- `drunk_call_service/tests/test_webrtc_answer.c` - Working test (committed)
- `drunk_call_service/tests/test_webrtc_answer.c.bkp` - Backup of working test

## Commit Message Draft:

```
Fix WebRTC answerer a=recvonly issue - apply working test pattern

Root causes:
1. encoding-name must be UPPERCASE (GStreamer requirement)
2. codec-preferences must be set BEFORE audio pipeline is linked
3. No fixed payload in codec-preferences (payload is negotiated)

Solution:
- Parse codec from SDP offer (with uppercase encoding-name)
- Create transceiver with codec-preferences before set-remote-description
- Don't link audio pipeline until after answer creation

This ensures webrtcbin matches our transceiver to offer's m-line,
resulting in a=sendrecv instead of a=recvonly.

Working test: drunk_call_service/tests/test_webrtc_answer.c

Status: Code refactored but NOT TESTED yet. Audio pipeline creation
needs to be added back after answer.
```

