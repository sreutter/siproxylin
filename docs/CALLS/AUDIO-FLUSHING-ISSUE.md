# Audio Source Flushing Issue

**Session**: c9a80de9-44da-4717-8683-cecbfa0432e5
**Problem**: bandwidth=0kbps, no audio flowing
**Root Cause**: Audio source in FLUSHING state

## Evidence

```
audio_src-actual-src-puls: pausing after gst_base_src_get_range() = flushing
```

## Analysis

When we add audio elements AFTER pipeline is already PLAYING:
1. Pipeline already in PLAYING state
2. We add new elements (audio_src, opusenc, etc.)
3. We call `gst_element_sync_state_with_parent()`
4. Elements go to PLAYING but pads are FLUSHING
5. No data flows

## Solution

Temporarily pause pipeline, add elements, then resume to PLAYING.

Fix in `create_audio_source_pipeline()`:
```cpp
// Pause pipeline before adding elements
gst_element_set_state(pipeline_, GST_STATE_PAUSED);

// ... add and link elements ...

// Resume pipeline
gst_element_set_state(pipeline_, GST_STATE_PLAYING);
```
