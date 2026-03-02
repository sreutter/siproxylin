/**
 * WebRTC Call Service - GStreamer webrtcbin Reference Implementation
 *
 * This is a REFERENCE FILE with commented code examples.
 * DO NOT compile directly - used for documentation purposes.
 *
 * See: docs/CALLS/PLAN.md for architecture overview
 */

#include <gst/gst.h>
#include <gst/sdp/sdp.h>
#include <gst/webrtc/webrtc.h>

// ============================================================================
// Session Structure (see: src/session.h when implemented)
// ============================================================================

struct CallSession {
    std::string session_id;
    std::string peer_jid;

    // GStreamer objects
    GstElement *pipeline;
    GstElement *webrtc;
    GstElement *audio_src;
    GstElement *audio_sink;

    // Session properties
    bool is_outgoing;           // true = we create offer, false = we answer
    bool relay_only;            // ICE transport policy
    std::string stun_server;
    std::string turn_server;

    // State tracking
    GstWebRTCICEConnectionState ice_state;
    GstWebRTCPeerConnectionState connection_state;
    GstWebRTCSignalingState signaling_state;

    // Device configuration
    std::string microphone_device;
    std::string speakers_device;

    // Audio processing flags
    bool echo_cancel;
    bool noise_suppression;
    bool gain_control;

    // gRPC event stream
    grpc::ServerWriter<CallEvent> *event_writer;
    std::mutex event_mutex;
};

// ============================================================================
// Pipeline Creation (Audio Only)
// ============================================================================

void create_audio_pipeline(CallSession *session) {
    // Create pipeline
    session->pipeline = gst_pipeline_new("call-pipeline");

    // Create elements
    session->audio_src = gst_element_factory_make("pulsesrc", "audiosrc");
    GstElement *queue1 = gst_element_factory_make("queue", NULL);
    GstElement *opus_enc = gst_element_factory_make("opusenc", NULL);
    GstElement *rtp_opus_pay = gst_element_factory_make("rtpopuspay", NULL);
    session->webrtc = gst_element_factory_make("webrtcbin", "webrtc");

    // Configure webrtcbin properties
    g_object_set(session->webrtc,
        "bundle-policy", GST_WEBRTC_BUNDLE_POLICY_MAX_BUNDLE,
        "ice-transport-policy", session->relay_only ?
            GST_WEBRTC_ICE_TRANSPORT_POLICY_RELAY :
            GST_WEBRTC_ICE_TRANSPORT_POLICY_ALL,
        "stun-server", session->stun_server.c_str(),
        NULL);

    // Set device if specified
    if (!session->microphone_device.empty()) {
        g_object_set(session->audio_src,
            "device", session->microphone_device.c_str(), NULL);
    }

    // Add elements to pipeline
    gst_bin_add_many(GST_BIN(session->pipeline),
        session->audio_src, queue1, opus_enc, rtp_opus_pay,
        session->webrtc, NULL);

    // Link outgoing audio chain
    gst_element_link_many(session->audio_src, queue1, opus_enc, rtp_opus_pay, NULL);

    // Link to webrtcbin with RTP caps
    GstCaps *caps = gst_caps_new_simple("application/x-rtp",
        "media", G_TYPE_STRING, "audio",
        "encoding-name", G_TYPE_STRING, "OPUS",
        "payload", G_TYPE_INT, 97,
        NULL);
    GstPad *sink_pad = gst_element_request_pad_simple(session->webrtc, "sink_%u");
    GstPad *src_pad = gst_element_get_static_pad(rtp_opus_pay, "src");
    gst_pad_link_full(src_pad, sink_pad, GST_PAD_LINK_CHECK_NOTHING);
    gst_caps_unref(caps);
    gst_object_unref(src_pad);
    gst_object_unref(sink_pad);

    // Connect signals BEFORE setting to PLAYING
    g_signal_connect(session->webrtc, "on-negotiation-needed",
        G_CALLBACK(on_negotiation_needed), session);
    g_signal_connect(session->webrtc, "on-ice-candidate",
        G_CALLBACK(on_ice_candidate), session);
    g_signal_connect(session->webrtc, "pad-added",
        G_CALLBACK(on_incoming_stream), session);
    g_signal_connect(session->webrtc, "notify::ice-connection-state",
        G_CALLBACK(on_ice_connection_state), session);
    g_signal_connect(session->webrtc, "notify::connection-state",
        G_CALLBACK(on_connection_state), session);
}

// ============================================================================
// TURN/STUN Configuration
// ============================================================================

void configure_turn_stun(CallSession *session) {
    // STUN server
    if (!session->stun_server.empty()) {
        g_object_set(session->webrtc,
            "stun-server", session->stun_server.c_str(), NULL);
    }

    // TURN server (can call multiple times for multiple servers)
    if (!session->turn_server.empty()) {
        gboolean success = FALSE;
        g_signal_emit_by_name(session->webrtc, "add-turn-server",
            session->turn_server.c_str(), &success);
        // Check success and log
    }

    // Relay-only mode (privacy/TURN-only)
    if (session->relay_only) {
        g_object_set(session->webrtc, "ice-transport-policy",
            GST_WEBRTC_ICE_TRANSPORT_POLICY_RELAY, NULL);
    }
}

// ============================================================================
// Offer Creation (Outgoing Call)
// ============================================================================

void create_offer(CallSession *session) {
    GstPromise *promise = gst_promise_new_with_change_func(
        on_offer_created, session, nullptr);
    g_signal_emit_by_name(session->webrtc, "create-offer", nullptr, promise);
}

void on_offer_created(GstPromise *promise, gpointer user_data) {
    CallSession *session = (CallSession*)user_data;

    // Wait for promise to complete
    g_assert(gst_promise_wait(promise) == GST_PROMISE_RESULT_REPLIED);

    // Extract offer from promise reply
    const GstStructure *reply = gst_promise_get_reply(promise);
    GstWebRTCSessionDescription *offer = nullptr;
    gst_structure_get(reply, "offer",
        GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &offer, nullptr);

    // Set as local description
    GstPromise *local_promise = gst_promise_new();
    g_signal_emit_by_name(session->webrtc, "set-local-description",
        offer, local_promise);
    gst_promise_interrupt(local_promise);
    gst_promise_unref(local_promise);

    // Convert SDP to string for gRPC return
    gchar *sdp_text = gst_sdp_message_as_text(offer->sdp);
    // Return sdp_text to gRPC caller
    g_free(sdp_text);

    gst_webrtc_session_description_free(offer);
    gst_promise_unref(promise);
}

// ============================================================================
// Answer Creation (Incoming Call)
// ============================================================================

void create_answer(CallSession *session, const std::string &remote_sdp_str) {
    // Parse remote SDP
    GstSDPMessage *sdp_msg;
    gst_sdp_message_new(&sdp_msg);
    gst_sdp_message_parse_buffer(
        (guint8*)remote_sdp_str.c_str(),
        remote_sdp_str.size(),
        sdp_msg);

    GstWebRTCSessionDescription *offer =
        gst_webrtc_session_description_new(GST_WEBRTC_SDP_TYPE_OFFER, sdp_msg);

    // Set remote description first
    GstPromise *promise = gst_promise_new_with_change_func(
        on_offer_set_for_answer, session, nullptr);
    g_signal_emit_by_name(session->webrtc, "set-remote-description",
        offer, promise);

    gst_webrtc_session_description_free(offer);
}

void on_offer_set_for_answer(GstPromise *promise, gpointer user_data) {
    CallSession *session = (CallSession*)user_data;
    gst_promise_unref(promise);

    // Now create answer
    GstPromise *answer_promise = gst_promise_new_with_change_func(
        on_answer_created, session, nullptr);
    g_signal_emit_by_name(session->webrtc, "create-answer",
        nullptr, answer_promise);
}

void on_answer_created(GstPromise *promise, gpointer user_data) {
    CallSession *session = (CallSession*)user_data;

    g_assert(gst_promise_wait(promise) == GST_PROMISE_RESULT_REPLIED);

    const GstStructure *reply = gst_promise_get_reply(promise);
    GstWebRTCSessionDescription *answer = nullptr;
    gst_structure_get(reply, "answer",
        GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &answer, nullptr);

    // Set local description
    GstPromise *local_promise = gst_promise_new();
    g_signal_emit_by_name(session->webrtc, "set-local-description",
        answer, local_promise);
    gst_promise_interrupt(local_promise);
    gst_promise_unref(local_promise);

    // Convert to string and return via gRPC
    gchar *sdp_text = gst_sdp_message_as_text(answer->sdp);
    // Return sdp_text to gRPC caller
    g_free(sdp_text);

    gst_webrtc_session_description_free(answer);
    gst_promise_unref(promise);
}

// ============================================================================
// Set Remote Description (for outgoing calls after receiving answer)
// ============================================================================

void set_remote_description(CallSession *session, const std::string &remote_sdp_str,
                           GstWebRTCSDPType type) {
    GstSDPMessage *sdp_msg;
    gst_sdp_message_new(&sdp_msg);
    gst_sdp_message_parse_buffer(
        (guint8*)remote_sdp_str.c_str(),
        remote_sdp_str.size(),
        sdp_msg);

    GstWebRTCSessionDescription *remote_desc =
        gst_webrtc_session_description_new(type, sdp_msg);

    GstPromise *promise = gst_promise_new();
    g_signal_emit_by_name(session->webrtc, "set-remote-description",
        remote_desc, promise);
    gst_promise_interrupt(promise);
    gst_promise_unref(promise);

    gst_webrtc_session_description_free(remote_desc);
}

// ============================================================================
// ICE Candidate Handling
// ============================================================================

// Local candidates (GStreamer → Python via gRPC)
void on_ice_candidate(GstElement *webrtc, guint mlineindex,
                      gchar *candidate, gpointer user_data) {
    CallSession *session = (CallSession*)user_data;

    // Create gRPC event
    CallEvent event;
    event.set_session_id(session->session_id);
    auto *ice_event = event.mutable_ice_candidate();
    ice_event->set_candidate(candidate);
    ice_event->set_sdp_mline_index(mlineindex);

    // Thread-safe write to gRPC stream
    std::lock_guard<std::mutex> lock(session->event_mutex);
    if (session->event_writer) {
        session->event_writer->Write(event);
    }
}

// Remote candidates (Python → GStreamer via gRPC)
void add_ice_candidate(CallSession *session, guint mlineindex,
                      const std::string &candidate) {
    g_signal_emit_by_name(session->webrtc, "add-ice-candidate",
        mlineindex, candidate.c_str());
}

// ============================================================================
// Incoming Media Stream (pad-added signal)
// ============================================================================

void on_incoming_stream(GstElement *webrtc, GstPad *pad, gpointer user_data) {
    CallSession *session = (CallSession*)user_data;

    // Only handle SRC pads (incoming media)
    if (GST_PAD_DIRECTION(pad) != GST_PAD_SRC)
        return;

    // Create sink chain for incoming audio
    GstElement *depay = gst_element_factory_make("rtpopusdepay", NULL);
    GstElement *decoder = gst_element_factory_make("opusdec", NULL);
    GstElement *queue = gst_element_factory_make("queue", NULL);
    session->audio_sink = gst_element_factory_make("pulsesink", "audiosink");

    // Set speaker device if specified
    if (!session->speakers_device.empty()) {
        g_object_set(session->audio_sink,
            "device", session->speakers_device.c_str(), NULL);
    }

    // Add to pipeline
    gst_bin_add_many(GST_BIN(session->pipeline),
        depay, decoder, queue, session->audio_sink, NULL);

    // Sync state with pipeline
    gst_element_sync_state_with_parent(depay);
    gst_element_sync_state_with_parent(decoder);
    gst_element_sync_state_with_parent(queue);
    gst_element_sync_state_with_parent(session->audio_sink);

    // Link sink chain
    gst_element_link_many(depay, decoder, queue, session->audio_sink, NULL);

    // Link pad to depay
    GstPad *sink_pad = gst_element_get_static_pad(depay, "sink");
    gst_pad_link(pad, sink_pad);
    gst_object_unref(sink_pad);
}

// ============================================================================
// State Monitoring
// ============================================================================

void on_ice_connection_state(GstElement *webrtc, GParamSpec *pspec,
                             gpointer user_data) {
    CallSession *session = (CallSession*)user_data;

    GstWebRTCICEConnectionState state;
    g_object_get(webrtc, "ice-connection-state", &state, NULL);
    session->ice_state = state;

    // Stream state change to Python via gRPC
    CallEvent event;
    event.set_session_id(session->session_id);
    auto *state_event = event.mutable_connection_state();

    // Map GStreamer states to proto states
    // NEW → NEW, CHECKING → CHECKING, CONNECTED/COMPLETED → CONNECTED, etc.

    std::lock_guard<std::mutex> lock(session->event_mutex);
    if (session->event_writer) {
        session->event_writer->Write(event);
    }
}

void on_connection_state(GstElement *webrtc, GParamSpec *pspec,
                        gpointer user_data) {
    CallSession *session = (CallSession*)user_data;

    GstWebRTCPeerConnectionState state;
    g_object_get(webrtc, "connection-state", &state, NULL);
    session->connection_state = state;

    // Similar gRPC event streaming
}

// ============================================================================
// Statistics Gathering
// ============================================================================

void get_stats(CallSession *session) {
    GstPromise *promise = gst_promise_new_with_change_func(
        on_stats_received, session, nullptr);
    g_signal_emit_by_name(session->webrtc, "get-stats", nullptr, promise);
}

void on_stats_received(GstPromise *promise, gpointer user_data) {
    CallSession *session = (CallSession*)user_data;

    const GstStructure *stats = gst_promise_get_reply(promise);

    // Parse stats structure
    // See: gst_structure_foreach() to iterate all stats
    // Extract: bytes_sent, bytes_received, connection_type, candidates, etc.

    gst_promise_unref(promise);
}

// ============================================================================
// Audio Device Enumeration
// ============================================================================

void list_audio_devices() {
    // Use PulseAudio API or pactl command
    // Parse output and return list of devices
    // Device format: "alsa_output.pci-0000_05_00.6.analog-stereo"
    // Description: "Family 17h/19h/1ah HD Audio Controller Analog Stereo"
}

// ============================================================================
// Mute Control
// ============================================================================

void set_mute(CallSession *session, bool muted) {
    if (session->audio_src) {
        g_object_set(session->audio_src, "mute", muted, NULL);
    }
}

// ============================================================================
// GLib Main Loop (Required for GStreamer async operations)
// ============================================================================

GMainLoop *main_loop = nullptr;
GThread *main_loop_thread = nullptr;

void* main_loop_runner(void* data) {
    g_main_loop_run((GMainLoop*)data);
    return nullptr;
}

void start_main_loop() {
    main_loop = g_main_loop_new(NULL, FALSE);
    main_loop_thread = g_thread_new("glib-mainloop", main_loop_runner, main_loop);
}

void stop_main_loop() {
    if (main_loop) {
        g_main_loop_quit(main_loop);
        g_thread_join(main_loop_thread);
        g_main_loop_unref(main_loop);
    }
}

// ============================================================================
// Session Cleanup
// ============================================================================

void cleanup_session(CallSession *session) {
    // Stop pipeline
    if (session->pipeline) {
        gst_element_set_state(session->pipeline, GST_STATE_NULL);
        gst_object_unref(session->pipeline);
    }

    // Close gRPC event stream
    std::lock_guard<std::mutex> lock(session->event_mutex);
    session->event_writer = nullptr;
}
