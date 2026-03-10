# Audio DSP Implementation Guide

**Date**: 2026-03-10
**Status**: Implemented
**Components**: webrtcdsp, webrtcechoprobe (gst-plugins-bad)

---

## Overview

This document describes the implementation of WebRTC-based audio processing (echo cancellation, noise suppression, automatic gain control) in the drunk_call_service using GStreamer's webrtcdsp plugin.

**Key Features**:
- Acoustic echo cancellation (AEC)
- Noise suppression
- Automatic gain control (AGC)
- High-pass filtering
- Conditional pipeline injection (zero overhead when disabled)

---

## Architecture

### Bidirectional DSP Design

WebRTC echo cancellation requires audio from **both directions**:
1. **Capture path** (microphone → network): webrtcdsp processes outgoing audio
2. **Playback path** (network → speakers): webrtcechoprobe captures reference audio for echo cancellation

```
Outgoing Audio (Capture):
  pulsesrc → webrtcdsp → volume → queue → convert → resample → opusenc → rtpopuspay → webrtcbin
               ↑
               | references probe for echo cancel
               |
Incoming Audio (Playback):
  webrtcbin → rtpopusdepay → opusdec → queue → webrtcechoprobe → pulsesink
                                                  ↑
                                                  captures playback for echo reference
```

### Echo Probe Creation Timing

**Critical**: The echo probe must exist **before** webrtcdsp starts, but the playback pipeline is created dynamically when the remote stream arrives (`pad-added` signal).

**Solution**: Create `webrtcechoprobe0` during pipeline initialization as an **unlinked element**, then link it when the incoming stream arrives.

**Implementation** (`webrtc_session.cpp:814-827`):
```cpp
bool WebRTCSession::create_pipeline() {
    // Create pipeline and webrtcbin
    pipeline_ = gst_pipeline_new("call-pipeline-...");
    webrtc_ = gst_element_factory_make("webrtcbin", "webrtc");
    gst_bin_add(GST_BIN(pipeline_), webrtc_);

    // Create echoprobe UPFRONT (before audio source setup)
    echoprobe_ = gst_element_factory_make("webrtcechoprobe", "webrtcechoprobe0");
    gst_bin_add(GST_BIN(pipeline_), echoprobe_);  // Added to pipeline but NOT linked

    // Later: webrtcdsp can reference probe by name "webrtcechoprobe0"
    return true;
}
```

**When incoming stream arrives** (`webrtc_session.cpp:2063`):
```cpp
void WebRTCSession::on_incoming_stream(GstPad *pad) {
    // Create playback elements
    GstElement *depay = gst_element_factory_make("rtpopusdepay", "depay");
    GstElement *decoder = gst_element_factory_make("opusdec", "decoder");
    GstElement *queue = gst_element_factory_make("queue", "recv_queue");
    // audio_sink_ created here

    // Link through pre-created echoprobe_
    gst_element_link_many(depay, decoder, queue, echoprobe_, audio_sink_, nullptr);
}
```

---

## Configuration Parameters

All parameters configurable via protobuf (`CreateSessionRequest`):

### Boolean Flags

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `echo_cancel` | bool | true | Enable acoustic echo cancellation |
| `noise_suppression` | bool | true | Enable noise suppression |
| `gain_control` | bool | true | Enable automatic gain control (AGC) |

### Suppression Levels

| Parameter | Type | Range | Default | Enum Values |
|-----------|------|-------|---------|-------------|
| `echo_suppression_level` | int32 | 0-2 | 1 | 0=low, 1=moderate, 2=high |
| `noise_suppression_level` | int32 | 0-3 | 1 | 0=low, 1=moderate, 2=high, 3=very-high |

**Higher levels** = more aggressive suppression but may affect speech quality during simultaneous talking (double-talk).

---

## Conditional DSP Injection

**Philosophy**: When all DSP features are disabled, the webrtcdsp element is **not created** and **not linked** into the pipeline. This ensures zero processing overhead and latency when users don't want audio processing.

**Implementation** (`webrtc_session.cpp:878`):
```cpp
// Check if ANY DSP feature is enabled
bool use_dsp = config_.echo_cancel || config_.noise_suppression || config_.gain_control;

GstElement *webrtcdsp = nullptr;
if (use_dsp) {
    webrtcdsp = gst_element_factory_make("webrtcdsp", "webrtcdsp");
    // Configure DSP...
}

// Conditional linking
if (use_dsp) {
    // With DSP: src → webrtcdsp → volume → queue → ...
    gst_element_link_many(audio_src_, webrtcdsp, volume_, queue, ...);
} else {
    // Without DSP: src → volume → queue → ... (bypass)
    gst_element_link_many(audio_src_, volume_, queue, ...);
}
```

**Logs**:
- When enabled: `"✓ Configured webrtcdsp: probe=webrtcechoprobe0, echo_cancel=true, ..."`
- When disabled: `"DSP disabled (all features off)"`

---

## Protobuf Integration

### Field Mapping

**Source**: `drunk_call_service/proto/call_service.proto`

```protobuf
message CreateSessionRequest {
  // ... other fields ...

  // Audio processing (WebRTC DSP)
  bool echo_cancel = 14;                    // Enable echo cancellation, default: true
  int32 echo_suppression_level = 15;        // 0=low, 1=moderate, 2=high, default: 1
  bool noise_suppression = 16;              // Enable noise suppression, default: true
  int32 noise_suppression_level = 17;       // 0=low, 1=moderate, 2=high, 3=very-high, default: 1
  bool gain_control = 18;                   // Enable automatic gain control, default: true
}
```

**Wire to SessionConfig** (`call_service_impl.cpp:91-95`):
```cpp
// Audio processing
config.echo_cancel = request->echo_cancel();
config.echo_suppression_level = request->echo_suppression_level();
config.noise_suppression = request->noise_suppression();
config.noise_suppression_level = request->noise_suppression_level();
config.gain_control = request->gain_control();
```

**Apply to webrtcdsp** (`webrtc_session.cpp:911-918`):
```cpp
g_object_set(webrtcdsp,
    "probe", "webrtcechoprobe0",
    "echo-cancel", config_.echo_cancel,
    "echo-suppression-level", config_.echo_suppression_level,
    "noise-suppression", config_.noise_suppression,
    "noise-suppression-level", config_.noise_suppression_level,
    "gain-control", config_.gain_control,
    nullptr);
```

---

## GStreamer Element Details

### webrtcdsp

**Plugin**: gst-plugins-bad (webrtcdsp)
**Class**: Audio/Filter
**Description**: Voice pre-processing using WebRTC Audio Processing Library

**Key Properties**:
```
echo-cancel               : boolean (default: true)
echo-suppression-level    : enum (0=low, 1=moderate, 2=high)
noise-suppression         : boolean (default: true)
noise-suppression-level   : enum (0=low, 1=moderate, 2=high, 3=very-high)
gain-control              : boolean (default: true)
high-pass-filter          : boolean (default: true) - always enabled internally
probe                     : string (default: "webrtcechoprobe0") - name of probe element
```

**Supported Formats**:
- Sample rate: 48000, 32000, 16000, 8000 Hz (use 48000 for WebRTC)
- Format: S16LE (16-bit signed PCM)
- Channels: 1 (mono microphone), probe can be stereo

**Inspect**:
```bash
gst-inspect-1.0 webrtcdsp
```

### webrtcechoprobe

**Plugin**: gst-plugins-bad (webrtcdsp)
**Class**: Generic/Audio
**Description**: Gathers playback buffers for webrtcdsp

**Function**: Passthrough element that captures audio being played through speakers and provides it to webrtcdsp for echo cancellation reference.

**Supported Formats**:
- Sample rate: 48000, 32000, 16000, 8000 Hz
- Format: S16LE or F32LE
- Channels: 1-N (typically 2 for stereo playback)

**Inspect**:
```bash
gst-inspect-1.0 webrtcechoprobe
```

---

## Testing & Verification

### Enable Debug Logging

Add `webrtcdsp:7` to `GST_DEBUG` environment variable:

**Python** (`drunk_xmpp/call_hook.py` or wherever service is launched):
```python
env['GST_DEBUG'] = 'webrtcbin:7,rtpbin:5,...,webrtcdsp:7'
```

### Expected Log Output

**When DSP enabled**:
```
[webrtcdsp] setting format to 16-bit signed PCM audio with 48000 Hz and 1 channels
[webrtcdsp] Enabling High Pass filter
[webrtcdsp] Enabling Echo Cancellation
[webrtcdsp] Enabling Noise Suppression
[webrtcechoprobe] setting format to 16-bit signed PCM audio with 48000 Hz and 2 channels
[webrtcechoprobe] We have a latency of 0:00:00.330000000 and delay of 200ms
```

**When DSP disabled**:
```
[WebRTCSession] DSP disabled (all features off)
```

### Functional Tests

#### 1. Echo Cancellation Test
- **Setup**: Play music/audio through speakers during a call
- **Expected**: Remote side should NOT hear the music echoed back
- **Without AEC**: Remote side hears loud echo of their own voice + music

#### 2. Noise Suppression Test
- **Setup**: Generate background noise (fan, AC, keyboard typing)
- **Expected**: Remote side hears less background noise, clearer voice
- **Test levels**: Try different `noise_suppression_level` values (0-3)

#### 3. Automatic Gain Control Test
- **Setup**: Speak at varying volumes (whisper → normal → loud)
- **Expected**: Output volume normalizes (quiet speech amplified, loud speech compressed)
- **Without AGC**: Large volume variations

#### 4. Conditional Injection Test
- **Setup**: Disable all features (`echo_cancel=false`, `noise_suppression=false`, `gain_control=false`)
- **Expected**: Logs show "DSP disabled (all features off)", no webrtcdsp element in pipeline
- **Verify**: `gst-launch-1.0 --gst-debug-level=3` or check pipeline graph

---

## Troubleshooting

### Issue: No DSP logs visible

**Cause**: webrtcdsp debug level not set
**Fix**: Add `webrtcdsp:7` to `GST_DEBUG`

### Issue: "No echo probe with name webrtcechoprobe0 found"

**Cause**: Echo probe not created before webrtcdsp starts (timing issue)
**Fix**: Ensure probe created in `create_pipeline()` before `setup_offerer_audio_pipeline()` or `setup_answerer_audio_pipeline()`
**Code**: `webrtc_session.cpp:816`

### Issue: Echo cancellation not working

**Possible causes**:
1. Probe not linked in playback pipeline → check `on_incoming_stream()` at line 2063
2. Sample rate mismatch → both must be 48000 Hz
3. Probe name mismatch → verify "webrtcechoprobe0" in both element name and probe property
4. Using headphones → no echo to cancel (AEC needs speaker→mic feedback)

**Debug**:
```bash
# Check if probe is receiving audio:
GST_DEBUG=webrtcdsp:7 | grep echoprobe
# Should see: "webrtcechoprobe setup: ... and 2 channels"
```

### Issue: Noise suppression too aggressive / robotic voice

**Cause**: `noise_suppression_level` set too high (3 = very-high)
**Fix**: Lower level to 1 (moderate) or 0 (low)
**Trade-off**: Lower levels = more background noise, higher speech quality

### Issue: Double-talk issues (cutting out when both speak)

**Cause**: `echo_suppression_level` too high (2 = high)
**Fix**: Lower to 1 (moderate) or 0 (low)
**Trade-off**: Lower echo suppression, better double-talk handling

---

## Performance Considerations

### CPU Usage

WebRTC DSP is computationally intensive:
- **Typical CPU**: 2-5% on modern x86_64 CPU
- **Embedded/ARM**: May be higher, test on target hardware

**Mitigation**: Conditional injection ensures zero overhead when disabled.

### Latency

- **Algorithmic latency**: ~10ms (WebRTC AEC inherent delay)
- **Buffering**: Additional 200-330ms from echoprobe latency calculation
- **Total impact**: Usually negligible compared to network latency

### Memory

- **Per-session overhead**: ~1-2 MB for DSP processing buffers
- **Negligible** for desktop/server deployments

---

## Future Improvements

### 1. Per-Feature Control

Currently: All features enabled/disabled together via boolean check.
**Enhancement**: Allow individual feature control (e.g., noise suppression ON, echo cancel OFF).

**Implementation**:
```cpp
// Instead of:
bool use_dsp = echo_cancel || noise_suppression || gain_control;

// Use:
if (echo_cancel || noise_suppression || gain_control) {
    webrtcdsp = create...;
    // Set individual features
}
```

### 2. Dynamic DSP Configuration

Currently: DSP configured at pipeline creation, changes require new session.
**Enhancement**: Allow runtime parameter changes via `SetAudioProcessing` RPC.

**Challenge**: Requires pipeline state management (pause → reconfigure → resume).

### 3. Voice Activity Detection (VAD)

WebRTC DSP supports VAD for:
- Bandwidth optimization (comfort noise generation)
- Privacy (mute when not speaking)

**Not currently exposed** in gst-plugins-bad webrtcdsp element.

### 4. Mobile-Optimized Profiles

**Idea**: Preset configurations for different scenarios:
- `MOBILE`: High noise suppression, moderate echo cancel
- `HEADSET`: Low echo cancel (no speakers), light noise suppression
- `CONFERENCE`: Aggressive echo cancel, balanced noise suppression

---

## References

### Code Locations

- **Probe creation**: `webrtc_session.cpp:814-827`
- **DSP configuration (answerer)**: `webrtc_session.cpp:877-924`
- **DSP configuration (offerer)**: `webrtc_session.cpp:1105-1152`
- **Probe linking**: `webrtc_session.cpp:2063`
- **Protobuf mapping**: `call_service_impl.cpp:91-95`
- **SessionConfig fields**: `media_session.h:168-172`

### GStreamer Documentation

- **webrtcdsp plugin**: https://gstreamer.freedesktop.org/documentation/webrtcdsp/
- **WebRTC Audio Processing**: https://webrtc.googlesource.com/src/+/main/modules/audio_processing/
- **Element inspection**: `gst-inspect-1.0 webrtcdsp`, `gst-inspect-1.0 webrtcechoprobe`

### Related Documentation

- `docs/CALLS/PLAN.md` - Audio Processing section (lines 289-338)
- `docs/CALLS/1-PIPELINE-PLAN.md` - Task 1.7.1 (DSP configuration)
- `docs/ADR.md` - Architecture decision records

---

**Last Updated**: 2026-03-10
**Implementation Status**: Complete and tested
**Maintainer**: Review before major GStreamer version upgrades
