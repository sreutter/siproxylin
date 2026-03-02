# Common GStreamer Warnings (Non-Issues)

This document explains common warnings seen during tests that are **harmless and expected**.

---

## 1. "error reading data -1 (reason: Success)"

**Full message**:
```
WARN audiosrc gstaudiosrc.c:227:audioringbuffer_thread_func:<audio_src-actual-src-puls>
error reading data -1 (reason: Success), skipping segment
```

**When it appears**: During pipeline shutdown (when stopping sessions)

**What it means**:
- The PulseAudio capture thread is still running
- Pipeline state has changed to NULL (stopping)
- Audio device is already closed
- Thread tries to read from closed device
- `read()` returns -1 (error) but `errno` is 0 (Success)
- Thread skips the segment and exits cleanly

**Why "reason: Success"**:
- In Linux, when a file descriptor is closed while another thread is reading from it, `read()` can return -1 without setting `errno`
- GStreamer interprets `errno=0` as "Success"
- This creates the confusing message "error reading data -1 (reason: Success)"

**Is this a problem?**: **NO**
- This is a **normal race condition** during multi-threaded shutdown
- The audio thread exits gracefully after this warning
- No memory leaks, no crashes
- Pipeline cleanup completes successfully

**Frequency**: Appears once per audio source when stopping

**Example**:
```
Test 9: Stopping session...
[WebRTCSession] Stopping pipeline...
0:00:02.155167950 WARN audiosrc error reading data -1 (reason: Success)
[WebRTCSession] Pipeline stopped and cleaned up
✓ Session stopped
```

**Solution**: None needed - this is expected behavior

---

## 2. "Caps are missing ssrc"

**Full message**:
```
WARN webrtcbin gstwebrtcbin.c:3532:sdp_media_from_transceiver:<webrtc>
Caps application/x-rtp, media=(string)audio, payload=(int)97,
encoding-name=(string)OPUS, clock-rate=(int)48000,
rtcp-fb-transport-cc=(boolean)true are missing ssrc
```

**When it appears**: During SDP offer/answer creation

**What it means**:
- Webrtcbin is creating SDP description
- RTP caps don't include SSRC (Synchronization Source identifier)
- SSRC is generated dynamically when media starts flowing
- At SDP negotiation time, no media is flowing yet, so no SSRC

**Is this a problem?**: **NO**
- SSRC is **not required** in SDP at negotiation time
- It's added to RTP packets when media starts
- SDP generation succeeds despite this warning
- Valid SDP is produced

**Frequency**: Once per session during offer/answer creation

**Solution**: None needed - SSRC is correctly generated later during media flow

---

## 3. "Error sending SSDP packet to 239.255.255.250"

**Full message**:
```
gssdp-client-WARNING: Error sending SSDP packet to 239.255.255.250:
Error sending message: Operation not permitted
```

**When it appears**: During ICE candidate gathering

**What it means**:
- libnice (ICE library) is trying to discover UPnP devices on the network
- It sends multicast packets to 239.255.255.250 (SSDP discovery)
- Kernel blocks the multicast (firewall, network config, or container)
- This is UPnP IGD (Internet Gateway Device) discovery

**Why it's blocked**:
- Many systems don't allow multicast by default
- Docker/containers often block it
- Firewall rules may prevent it
- Not needed for basic ICE functionality

**Is this a problem?**: **NO**
- ICE works fine without UPnP
- STUN/TURN provide connectivity
- Host and server-reflexive candidates work
- Only affects automatic port mapping discovery

**Frequency**: Multiple times during ICE gathering (6-12 times)

**Solution**: None needed - ICE candidates are gathered successfully via other methods (STUN)

---

## 4. "could not send sticky events" (occasional)

**Full message**:
```
WARN GST_PADS gstpad.c:4361:gst_pad_peer_query:<nicesrc1:src>
could not send sticky events
```

**When it appears**: During dynamic pad linking (answerer side)

**What it means**:
- GStreamer pads have "sticky events" (caps, segment, etc.)
- When dynamically linking pads, these events are sent
- Timing issue: downstream element not ready yet
- Events will be resent when element is ready

**Is this a problem?**: **NO**
- Events are retried automatically
- Pipeline continues normally
- Media flows correctly
- Self-correcting issue

**Frequency**: Occasional (timing-dependent)

**Solution**: None needed - GStreamer handles retry internally

---

## 5. "Can't determine running time for this packet without knowing configured latency"

**Full message**:
```
WARN rtpsession gstrtpsession.c:2435:gst_rtp_session_chain_send_rtp_common:<rtpsession0>
Can't determine running time for this packet without knowing configured latency
```

**When it appears**: When RTP packets first start flowing

**What it means**:
- RTP session needs to know latency for timestamp calculations
- First few packets arrive before latency is configured
- Latency is established after a few packets
- Subsequent packets use correct timing

**Is this a problem?**: **NO**
- Only affects first 1-2 packets
- Latency auto-configures quickly
- Audio/video quality unaffected
- Normal during startup

**Frequency**: Once or twice per session at start

**Solution**: None needed - latency is auto-configured

---

## Summary

All these warnings are **normal and expected** during:
- Pipeline shutdown (race conditions)
- Initial SDP negotiation (missing runtime values)
- ICE gathering (network discovery attempts)
- Dynamic pad linking (timing issues)

**When to worry**:
- ❌ ERROR messages (not WARN)
- ❌ Crashes or segfaults
- ❌ Memory leaks (use valgrind)
- ❌ Tests failing (returning non-zero)

**Current test status**: ✅ All tests pass despite these warnings

---

**Last Updated**: 2026-03-02
