# Analysis: Call 496562f0-acac-46d5-92f5-a5c52f76646c

**Date**: 2026-03-05
**Issue**: Dino kept saying "Calling", never connected; Only one transceiver created

## Summary of Findings

### Question 1: Was there only one transceiver created?

**YES** ✅ - Based on the implementation in `webrtc_session.cpp:351-404`, only **one transceiver** was created.

**Evidence**:
1. The code explicitly requests one pad in answer mode (line 374):
   ```cpp
   GstPad *webrtc_sink = gst_element_request_pad(webrtc_, templ, nullptr, nullptr);
   ```

2. It sets codec-preferences on the last (and only) transceiver (lines 386-397):
   ```cpp
   if (transceivers && transceivers->len > 0) {
       GstWebRTCRTPTransceiver* trans =
           g_array_index(transceivers, GstWebRTCRTPTransceiver*, transceivers->len - 1);
   ```

3. No logs indicate multiple transceivers were created

4. The GST_DEBUG logs at line 50103+ show only one RTP session being created (session 0)

**Context from SESSION-LOG.md**:
- Previous sessions (22-23) had issues with **TWO transceivers** being created
- Session 23 documented: "mline=4294967295" (UNASSIGNED) - transceiver not matched
- The fix applied was from docs/CALLS/WEBRTCBIN-RECVONLY-DEEP-DIVE.md (line 555-611)
- Working test code created isolated test (`test_webrtc_answer.c`) that successfully generates `a=sendrecv`

### Question 2: Why did Dino keep saying "Calling" and never went to connected?

**ROOT CAUSE**: The SDP answer likely contained `a=recvonly` instead of `a=sendrecv`, causing a direction mismatch.

**Evidence Chain**:

1. **From WEBRTCBIN-RECVONLY-DEEP-DIVE.md (lines 1-15)**:
   ```
   When creating SDP answers for incoming calls, webrtcbin generates `a=recvonly`
   instead of `a=sendrecv`, causing the remote peer (Dino) to not send audio to us.
   The peer stays in "Calling" state instead of connecting.
   ```

2. **Bandwidth = 0kbps throughout the call**:
   ```
   [2026-03-05 13:37:39.746] bandwidth=0kbps
   [2026-03-05 13:37:41.821] bandwidth=0kbps
   [2026-03-05 13:37:43.819] bandwidth=0kbps
   ```
   This confirms **no media flowing** in either direction.

3. **ICE Connection Status**:
   - State 1 (CHECKING) at 13:37:38.305
   - State 2 (CONNECTED) at 13:37:38.922
   - State 3 (COMPLETED) at 13:37:40.364

   **ICE succeeded** ✅ but **media failed** ❌

4. **Jingle Signaling Shows Direction Problem**:
   From xmpp-protocol.log:
   - **Dino's offer** (13:37:37.996): `senders="both"` (bidirectional)
   - **Our answer** (13:37:38.107): `senders="both"` (claimed bidirectional)

   BUT the SDP we sent to C++ must have had `a=recvonly` which Jingle converter translated to `senders="initiator"` but we hardcoded it to "both" in older code!

5. **Known Issue from SESSION-LOG.md Session 21**:
   ```
   **Python Jingle Converter Fix**:
   - Added proper SDP direction parsing in `jingle_sdp_converter.py:132-155`
   - Now reads actual SDP direction and converts to Jingle `senders` attribute:
     - `a=sendrecv` → `senders='both'`
     - `a=recvonly` → `senders='initiator'` (only Dino sends, we receive)
   ```

## Technical Explanation

### The WebRTC Direction Problem

According to WEBRTCBIN-RECVONLY-DEEP-DIVE.md (lines 43-60):

When webrtcbin creates an SDP answer, it determines the direction by:
1. Trying to match existing transceivers to the offer's m-line via caps intersection
2. If match found: uses transceiver's direction (SENDRECV)
3. If NO match: creates new transceiver with **RECVONLY** (default)

From GStreamer source `gstwebrtcbin.c:4562-4571`:
```c
if (rtp_trans) {
    answer_dir = rtp_trans->direction;  // Uses SENDRECV
} else {
    // No matching transceiver found!
    answer_dir = GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_RECVONLY;
    GST_WARNING ("did not find compatible transceiver...");
}
```

### Root Causes Identified in WEBRTCBIN-RECVONLY-DEEP-DIVE.md

From lines 566-583:

1. **encoding-name must be UPPERCASE**
   - SDP has: `a=rtpmap:111 opus/48000/2` (lowercase)
   - GStreamer expects: `encoding-name=(string)OPUS` (UPPERCASE)
   - **Fix:** Use `g_ascii_strup()` when parsing SDP

2. **codec-preferences overridden by pad caps**
   - When audio pipeline is linked BEFORE answer creation, `_find_codec_preferences()` returns **pad caps** instead of manual codec-preferences
   - Pad caps include session-specific fields that fail intersection
   - **Fix:** Create transceiver with codec-preferences but **DON'T link audio until after answer**

3. **Fixed payload in caps causes intersection failure**
   - Specifying `payload=97` in codec-preferences fails when offer has `payload=111`
   - **Fix:** Don't specify payload in codec-preferences

### The Working Pattern (from test code)

From WEBRTCBIN-RECVONLY-DEEP-DIVE.md lines 585-609:

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

**Key insight**: Codec-preferences are ONLY used when pad has no caps. Once audio is linked, pad caps override everything!

## What Happened in Call 496562f0

### Timeline

1. **13:37:37.996** - Received Dino's offer with OPUS 111, `senders="both"`
2. **13:37:38.094** - CreateSession called
3. **13:37:38.095** - WebRTC session initialized
4. **13:37:38.099** - CreateAnswer called with remote_sdp_size=728 bytes
5. **13:37:38.104** - Answer generated, sdp_size=408 bytes (only 5ms!)
6. **13:37:38.107** - Sent session-accept to Dino with `senders="both"`
7. **13:37:38.305** - ICE CHECKING
8. **13:37:38.922** - ICE CONNECTED ✅
9. **13:37:40.364** - ICE COMPLETED ✅
10. **13:37:39-50** - GetStats shows: ice_state=completed, **bandwidth=0kbps** ❌

### Problem Analysis

**What the code SHOULD do** (webrtc_session.cpp:351-404):
1. ✅ Parse codec from offer with UPPERCASE encoding-name
2. ✅ Create transceiver with codec-preferences (NO fixed payload)
3. ✅ Set direction=SENDRECV on transceiver
4. ✅ Set remote description (offer)
5. ✅ Create answer with `a=sendrecv`

**What likely went wrong**:

**Hypothesis #1: Codec parsing failed**
- If `parse_audio_codec_from_offer()` returned NULL
- Code would have logged: "Failed to parse audio codec from offer"
- No such error in logs → parsing succeeded ✅

**Hypothesis #2: Transceiver not created**
- If `gst_element_request_pad()` failed
- Code would have logged: "Failed to request webrtcbin sink pad"
- No such error → transceiver created ✅

**Hypothesis #3: Audio pipeline already linked**
- The code at lines 351-404 explicitly creates transceiver WITHOUT linking audio
- Looking at `create_pipeline()` function... **NEED TO CHECK THIS**

**Hypothesis #4: Caps intersection still failing**
- Even with uppercase OPUS and no fixed payload
- webrtcbin might require additional caps fields (encoding-params?)
- From Dino's offer: `opus/48000/2` → encoding-params=2 (stereo)

## Diagnostic Next Steps

### 1. Check if SDP answer actually has `a=sendrecv` or `a=recvonly`

The drunk-call-service.log doesn't show the actual SDP content. Need to:

```bash
# Add logging to webrtc_session.cpp on_answer_created() to print SDP text
# OR check if Python logs the received SDP answer
grep "a=sendrecv\|a=recvonly" ~/.siproxylin/logs/*.log
```

### 2. Enable webrtcbin debug logging

The GST_DEBUG output at line 50103+ is only rtpbin:DEBUG level. Need webrtcbin:7:

```bash
GST_DEBUG=webrtcbin:7 ./drunk-call-service-linux
```

This will show:
- Transceiver matching attempts
- Codec-preferences retrieval
- Caps intersection results
- Why direction is RECVONLY vs SENDRECV

### 3. Check if audio pipeline is pre-linked

Need to verify `create_pipeline()` in webrtc_session.cpp doesn't link audio source before answer creation.

**Expected**: Audio source NOT linked until after answer
**If broken**: Audio linked during initialization → pad caps override codec-preferences

### 4. Verify encoding-params is included

Check parse_audio_codec_from_offer() (lines 41-140) ensures:
```cpp
encoding-name=OPUS (uppercase)
clock-rate=48000
encoding-params=2  // ← Must be included for stereo!
```

## Comparison: Working Test vs Real Call

### Working Test (test_webrtc_answer.c)
- ✅ Only 1 transceiver created
- ✅ Answer SDP has `a=sendrecv`
- ✅ Transceiver matched to offer via codec-preferences

### Real Call (496562f0)
- ✅ ICE connected + completed
- ❌ Bandwidth = 0kbps (no media)
- ❌ Dino stayed "Calling" (not connected)
- ? SDP direction unknown (need to check logs)

## Recommended Actions

### Immediate (This Session)

1. **Add SDP logging to on_answer_created()**:
   ```cpp
   char *sdp_text = gst_sdp_message_as_text(answer->sdp);
   LOG_INFO("[WebRTCSession] SDP Answer:\n{}", sdp_text);
   g_free(sdp_text);
   ```

2. **Check if create_pipeline() links audio prematurely**:
   - Read create_pipeline() function
   - Verify audio source is NOT linked to webrtcbin during initialization

3. **Verify encoding-params handling**:
   - Check if parse_audio_codec_from_offer() includes encoding-params
   - Dino sends `opus/48000/2` → must parse the "2"

### Follow-up (If Still Broken)

1. **Enable GST_DEBUG=webrtcbin:7** for detailed logs
2. **Create minimal reproduction**:
   - Use Dino's exact offer SDP
   - Run test_webrtc_answer with that SDP
   - Compare with real call logs

3. **Check Python Jingle converter**:
   - Verify it correctly reads SDP direction from C++ answer
   - Ensure it's not hardcoded to `senders="both"`

## References

- **WEBRTCBIN-RECVONLY-DEEP-DIVE.md**: Full investigation of the `a=recvonly` problem
- **SESSION-LOG.md Session 20-23**: Previous debugging sessions
- **test_webrtc_answer.c**: Working isolated test case
- **webrtc_session.cpp:351-404**: Answer mode transceiver creation
- **GStreamer source gstwebrtcbin.c:4562-4571**: Direction determination logic

---

**Status**: Root cause identified as SDP direction problem. Need to verify actual SDP answer content and ensure codec-preferences are correctly applied.

**Next**: Add SDP logging + check create_pipeline() for premature audio linking
