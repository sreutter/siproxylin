# This is to make calls work with GStreamer webrtcbin using C++

## **DO NOT EDIT THIS UNLESS CHANGE ACCEPTED BY USER**

**Branch**: `calls-gst`

### Documentation Philosophy:
**This is a 99% AI-coded project - docs exist to keep AI context clean and efficient**
- **NO CODE EXAMPLES** - they stale/out-of-sync immediately, reference file paths instead
- **DO NOT BLOAT** - pin-point hints only, no explanations of obvious things
- **CURRENT STATE ONLY** - document what IS, not what WAS (git handles history)

### RULES:
**Prefer deep reads, we are not saving tokens, we need quality not patches**
**Use C++, must compile on Windows and MacOS**
**Create an abstraction layer as we will want two paths - webrtcbin and rtpbin for very exotic cases - use polymorhic code or a session factory, whichever is appreciated today**
**Every and each step in the code must be covered by try-catch**
**Refer to webrtcbin official examples, read WEB whenever needed**
**In case in doubt refer to Dino code (it uses rtpbin so not exactly useful)**
**Last resort - see how our Go works (it uses Pion so masks part of webrtc deeds)**
**Speak up if something does not fit, for example existing Python code does not integrate efficiently via gRPC due to different async loops, propose solutions**
**Make sure you update status all along (document references below) so session restart allows easy resuming**

### Refer to:
- Dino code: /home/m/claude/siproxylin/drunk_call_service/tmp/dino
- GStreamer code, docs and examples:
    - /home/m/claude/siproxylin/drunk_call_service/tmp/gst-examples
    - /home/m/claude/siproxylin/drunk_call_service/tmp/gst-plugins-bad1.0-1.22.0 (our Debian version)
    - /home/m/claude/siproxylin/drunk_call_service/tmp/gst-plugins-good
- Existing Go Pion call service: /home/m/claude/siproxylin/drunk_call_service_go
- WEB resources

### The context:

- We have a working call integration with Go (stable in main branch), copy of the code is in /home/m/claude/siproxylin/drunk_call_service_go
- Rewriting is needed because Pion has certain limitations and GStreamer brings more flexibility including smaller binary
- **Known Go/Pion Limitations we're fixing:**
    - Binary size (~27MB stripped)
    - Limited codec flexibility (Pion's codec support is hardcoded)
    - GStreamer integration awkward (CGO + Go's runtime don't play well with GStreamer's threading)
    - Audio device selection issues on some platforms
- XMPP / GUI talks to call service via gRPC
    - **Proto contract**: /home/m/claude/siproxylin/drunk_call_service/proto/call.proto - THIS IS THE INTERFACE (read it first!)
    - Jingle ↔ SDP translation is handled by /home/m/claude/siproxylin/drunk_call_hook/protocol/jingle.py (Python side)
    - Service binary **must be in**: /home/m/claude/siproxylin/drunk_call_service/bin/drunk-call-service-linux (for Linux)
        - Windows: /home/m/claude/siproxylin/drunk_call_service/bin/drunk-call-service-windows.exe
        - macOS: /home/m/claude/siproxylin/drunk_call_service/bin/drunk-call-service-macos
    - Service lifecycle managed by /home/m/claude/siproxylin/drunk_call_hook/bridge.py (GoCallService class)
    - **Logs**:
        - Primary: /home/m/.siproxylin/logs/drunk-call-service.log (structured logs from service)
        - Crashes/panics: /home/m/.siproxylin/logs/drunk-call-service.err (stderr)
        - GStreamer debug: /home/m/.siproxylin/logs/drunk-call-service-stdout.log
        - Dev mode: /home/m/claude/siproxylin/sip_dev_paths/logs/ (when running from project root without --xdg)
- Go service grew up from a prototype but was never properly planned, just patch after patch until finally worked
- We need a plan of C++ integration step by step
 

### Success Criteria:
**Library level (before gRPC):**
- ✅ WebRTCSession: SDP negotiation, ICE connectivity
- ⏳ **Proxy support** (CRITICAL - old Go service had this, check drunk_call_service_go/, test with local SOCKS5)
- ⏳ Device enumeration (GStreamer GstDeviceMonitor API, see gst-plugins-good/ext/pulse/pulsesink.c)
- ⏳ Statistics (get_stats() method)
- ⏳ Video streams (add_video_stream() at library level, test in test_step3)

**gRPC service level:**
- CreateSession, CreateOffer, CreateAnswer, StreamEvents
- Audio bidirectional, mute works, stats available
- Binary <10MB, startup <500ms
- Works with Conversations.im + Dino

### Build:
- CMake 3.20+, C++17
- GStreamer 1.22+ (`gstreamer-webrtc-1.0`, `gstreamer-sdp-1.0`)
- gRPC C++ (`grpc++`, `protobuf`)
- Output: /home/m/claude/siproxylin/drunk_call_service/bin/drunk-call-service-{linux,windows,macos}

### ICE State Machine:
`NEW → CHECKING → CONNECTED → COMPLETED` (or `FAILED`/`DISCONNECTED`)
Stream state changes to Python via ConnectionStateEvent.

### WebRTC Features Status:
1. ✅ **rtcp-mux**: RTP+RTCP on same port (webrtcbin auto-handles)
2. ✅ **bundle**: Single ICE connection (`bundle-policy=max-bundle` set in webrtc_session.cpp:425)
3. ✅ **trickle-ICE**: `a=ice-options:trickle` in SDP, candidates streamed via on_ice_candidate
4. ⏳ **proxy**: MUST support SOCKS5/HTTP (old Go had it, check drunk_call_service_go/)
5. ⏳ **devices**: GstDeviceMonitor (replace pactl)
6. ⏳ **stats**: get_stats() method
7. ⏳ **video**: add_video_stream() for future Qt integration

### Error Handling:
- Try-catch all RPC handlers
- **PROPAGATE**: Stream errors to Python via CallEvent.ErrorEvent (GUI must show user feedback, not silent failures)

### The task before we begin coding:
1. Define the webrtcbin call flow steps and a diagram; *see examples, read WEB, DO NOT reinvent the wheel* (create /home/m/claude/siproxylin/docs/CALLS/PLAN.md)
2. Document GStreamer signals and/or hooks you will be using in your flow (transceiver_added, etc, see all signals in docs and examples)
3. Read /home/m/claude/siproxylin/drunk_call_service/proto to see integration (we DO NOT plan changing it as it works with Go, however some changes will likely be needed)
4. Do not try to adjust both ends at the same time to somehow work, as we tried that and eventually end up in a mess of patches trying to satisfy async caused delays and breaking the flow
5. *Define call service strictly first*, and then we will see how many adjustments we got to make to Python and Protobuf
6. You will most likely need to add to protobuf handling of:
    - rtcp-mux
    - trickle-only (Conversations)
    - bundle
7. Above are known as missing so speak up with your plan
8. Create high level plan for the above -- /home/m/claude/siproxylin/docs/CALLS/PLAN.md -- describe how you glue protobuf with the strict flow based on webrtcbin examples
9. Build up a call session skeleton with properties like "incoming call, outgoing call, rtcp-mux (true/false)" - EVERYTHING in one place, commented and easy to reach
10. Create detailed plan for each step of the call flow implementation /home/m/claude/siproxylin/docs/CALLS/{STEP}-PLAN.md with testable criteria: initiate call, parse SDP, connect ICE, prep transceivers, expose stats _this is just an example, make it right, must be testable at least by looking at logs_
11. Go step by step *documenting* the progress in /home/m/claude/siproxylin/docs/CALLS/{STEP}-STATUS.md (create STATUS file after corresponding PLAN file is complete)

