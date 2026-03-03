/**
 * WebRTC Session Implementation
 *
 * Implements MediaSession using GStreamer webrtcbin element
 * Reference: docs/CALLS/1-PIPELINE-PLAN.md
 */

#include "webrtc_session.h"
#include "logger.h"
#include <gst/sdp/sdp.h>
#include <gst/webrtc/webrtc.h>
#include <stdexcept>
#include <cstring>

namespace drunk_call {

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Extract ICE candidate type without exposing IP addresses (privacy-safe).
 * Returns: "host", "srflx", "relay", "prflx", or "unknown"
 */
static std::string extract_candidate_type(const char* candidate) {
    if (!candidate) return "unknown";

    if (strstr(candidate, "typ host")) return "host";
    if (strstr(candidate, "typ srflx")) return "srflx";
    if (strstr(candidate, "typ relay")) return "relay";
    if (strstr(candidate, "typ prflx")) return "prflx";

    return "unknown";
}

// ============================================================================
// Constructor / Destructor
// ============================================================================

WebRTCSession::WebRTCSession()
    : pipeline_(nullptr)
    , webrtc_(nullptr)
    , audio_src_(nullptr)
    , audio_sink_(nullptr)
    , volume_(nullptr)
    , is_muted_(false)
    , is_outgoing_(false)
    , sdp_done_(false)
    , last_bytes_sent_(0)
    , last_bytes_received_(0)
{
}

WebRTCSession::~WebRTCSession() {
    try {
        // CRITICAL: Disconnect all signals BEFORE stopping pipeline
        // If GStreamer fires a signal during/after destruction, the callback
        // receives a 'this' pointer to a partially-destroyed object → crash
        if (webrtc_) {
            g_signal_handlers_disconnect_by_data(webrtc_, this);
        }

        stop();
    } catch (...) {
        // Suppress exceptions in destructor
    }
}

// ============================================================================
// Lifecycle Methods
// ============================================================================

bool WebRTCSession::initialize(const SessionConfig &config) {
    try {
        config_ = config;

        if (!create_pipeline()) {
            LOG_ERROR("[WebRTCSession] Failed to create pipeline");
            return false;
        }

        if (!configure_webrtcbin()) {
            LOG_ERROR("[WebRTCSession] Failed to configure webrtcbin");
            return false;
        }

        if (!configure_proxy()) {
            LOG_ERROR("[WebRTCSession] Failed to configure proxy");
            return false;
        }

        if (!add_turn_servers()) {
            LOG_ERROR("[WebRTCSession] Failed to add TURN servers");
            return false;
        }

        connect_signals();

        LOG_INFO("[WebRTCSession] Initialized session: {}", config_.session_id);
        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] Initialize failed: {}", e.what());
        return false;
    }
}

bool WebRTCSession::start() {
    try {
        if (!pipeline_) {
            LOG_ERROR("[WebRTCSession] Pipeline not initialized");
            return false;
        }

        LOG_INFO("[WebRTCSession] Starting pipeline...");
        GstStateChangeReturn ret = gst_element_set_state(pipeline_, GST_STATE_PLAYING);

        if (ret == GST_STATE_CHANGE_FAILURE) {
            LOG_ERROR("[WebRTCSession] Failed to set pipeline to PLAYING");
            return false;
        }

        LOG_INFO("[WebRTCSession] Pipeline PLAYING");
        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] Start failed: {}", e.what());
        return false;
    }
}

bool WebRTCSession::stop() {
    try {
        if (!pipeline_) {
            return true;  // Already stopped
        }

        LOG_INFO("[WebRTCSession] Stopping pipeline...");
        gst_element_set_state(pipeline_, GST_STATE_NULL);
        gst_object_unref(pipeline_);

        pipeline_ = nullptr;
        webrtc_ = nullptr;
        audio_src_ = nullptr;
        audio_sink_ = nullptr;

        LOG_INFO("[WebRTCSession] Pipeline stopped and cleaned up");
        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] Stop failed: {}", e.what());
        return false;
    }
}

// ============================================================================
// SDP Operations
// ============================================================================

void WebRTCSession::create_offer(SDPCallback callback) {
    try {
        is_outgoing_ = true;
        sdp_callback_ = callback;

        LOG_INFO("[WebRTCSession] Creating offer...");

        // Create promise for async SDP generation
        GstPromise *promise = gst_promise_new_with_change_func(
            on_offer_created_static, this, nullptr);

        // Emit create-offer signal on webrtcbin
        g_signal_emit_by_name(webrtc_, "create-offer", nullptr, promise);

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] create_offer failed: {}", e.what());
        if (callback) {
            callback(false, SDPMessage(), std::string("Exception: ") + e.what());
        }
    }
}

void WebRTCSession::create_answer(const SDPMessage &remote_offer, SDPCallback callback) {
    try {
        is_outgoing_ = false;
        sdp_callback_ = callback;

        LOG_INFO("[WebRTCSession] Creating answer...");

        // First set remote description (the offer)
        if (!set_remote_description(remote_offer)) {
            LOG_ERROR("[WebRTCSession] Failed to set remote offer");
            if (callback) {
                callback(false, SDPMessage(), "Failed to set remote offer");
            }
            return;
        }

        // Create answer after remote description is set
        // This will be triggered by on_offer_set_for_answer callback

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] create_answer failed: {}", e.what());
        if (callback) {
            callback(false, SDPMessage(), std::string("Exception: ") + e.what());
        }
    }
}

bool WebRTCSession::set_remote_description(const SDPMessage &remote_sdp) {
    try {
        LOG_INFO("[WebRTCSession] Setting remote description...");

        // Parse SDP text
        GstSDPMessage *sdp_msg;
        if (gst_sdp_message_new(&sdp_msg) != GST_SDP_OK) {
            LOG_ERROR("[WebRTCSession] Failed to create SDP message");
            return false;
        }

        if (gst_sdp_message_parse_buffer(
                (const guint8*)remote_sdp.sdp_text.c_str(),
                remote_sdp.sdp_text.length(),
                sdp_msg) != GST_SDP_OK) {
            LOG_ERROR("[WebRTCSession] Failed to parse SDP");
            gst_sdp_message_free(sdp_msg);
            return false;
        }

        // Create WebRTC session description
        GstWebRTCSDPType sdp_type = (remote_sdp.type == SDPMessage::Type::OFFER) ?
            GST_WEBRTC_SDP_TYPE_OFFER : GST_WEBRTC_SDP_TYPE_ANSWER;

        GstWebRTCSessionDescription *desc = gst_webrtc_session_description_new(
            sdp_type, sdp_msg);

        if (!desc) {
            LOG_ERROR("[WebRTCSession] Failed to create session description");
            return false;
        }

        // Set remote description with promise
        // CRITICAL: Do NOT interrupt/unref promise immediately after emitting!
        // The promise callback may execute asynchronously, and we'd cause use-after-free.
        // GStreamer will unref the promise when done.
        GstPromise *promise;
        if (!is_outgoing_ && remote_sdp.type == SDPMessage::Type::OFFER) {
            // Answerer receiving offer - need to create answer afterward
            promise = gst_promise_new_with_change_func(
                on_offer_set_for_answer_static, this, nullptr);
        } else {
            // Offerer receiving answer - just set it (no callback needed)
            promise = gst_promise_new();
        }

        g_signal_emit_by_name(webrtc_, "set-remote-description", desc, promise);

        // FIXED: Don't interrupt/unref here - GStreamer owns the promise now
        // Old buggy code was:
        //   gst_promise_interrupt(promise);  // ❌ BAD!
        //   gst_promise_unref(promise);      // ❌ BAD!

        LOG_INFO("[WebRTCSession] Remote description set");
        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] set_remote_description failed: {}", e.what());
        return false;
    }
}

// ============================================================================
// ICE Operations
// ============================================================================

void WebRTCSession::set_ice_candidate_callback(ICECandidateCallback callback) {
    ice_callback_ = callback;
}

bool WebRTCSession::add_remote_ice_candidate(const ICECandidate &candidate) {
    try {
        LOG_TRACE("[WebRTCSession] Adding remote ICE candidate: mline={}", candidate.sdp_mline_index);

        g_signal_emit_by_name(webrtc_, "add-ice-candidate",
                             candidate.sdp_mline_index,
                             candidate.candidate.c_str());

        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] add_remote_ice_candidate failed: {}", e.what());
        return false;
    }
}

// ============================================================================
// State Callbacks
// ============================================================================

void WebRTCSession::set_state_callback(StateCallback callback) {
    state_callback_ = callback;
}

// ============================================================================
// Audio Control
// ============================================================================

bool WebRTCSession::set_mute(bool muted) {
    try {
        is_muted_ = muted;

        if (volume_) {
            // Mute by setting volume to 0 on the volume element
            g_object_set(volume_, "volume", muted ? 0.0 : 1.0, nullptr);
            LOG_INFO("[WebRTCSession] Audio {}", muted ? "muted" : "unmuted");
        }

        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] set_mute failed: {}", e.what());
        return false;
    }
}

// ============================================================================
// Statistics
// ============================================================================

MediaSession::Stats WebRTCSession::get_stats() const {
    Stats stats;

    try {
        if (!webrtc_) {
            return stats;
        }

        // Get stats synchronously using get-stats action
        GstPromise *promise = gst_promise_new();
        g_signal_emit_by_name(webrtc_, "get-stats", nullptr, promise);

        // Wait for promise (blocking, but stats should be fast)
        GstPromiseResult result = gst_promise_wait(promise);

        if (result == GST_PROMISE_RESULT_REPLIED) {
            const GstStructure *reply = gst_promise_get_reply(promise);
            if (reply) {
                parse_stats(reply, stats);
            }
        }

        gst_promise_unref(promise);

        // Get ICE states from webrtcbin properties (not in stats structure)
        GstWebRTCICEConnectionState ice_conn_state;
        GstWebRTCICEGatheringState ice_gather_state;
        g_object_get(webrtc_,
                    "ice-connection-state", &ice_conn_state,
                    "ice-gathering-state", &ice_gather_state,
                    nullptr);

        // Convert enums to strings
        const char *ice_conn_names[] = {"new", "checking", "connected", "completed", "failed", "disconnected", "closed"};
        const char *ice_gather_names[] = {"new", "gathering", "complete"};

        if (ice_conn_state < 7) {
            stats.ice_connection_state = ice_conn_names[ice_conn_state];
        }
        if (ice_gather_state < 3) {
            stats.ice_gathering_state = ice_gather_names[ice_gather_state];
        }

        // Calculate bandwidth based on deltas
        auto now = std::chrono::steady_clock::now();
        if (last_stats_time_.time_since_epoch().count() > 0) {
            auto delta_time = std::chrono::duration_cast<std::chrono::milliseconds>(
                now - last_stats_time_).count();

            if (delta_time > 0) {
                int64_t delta_bytes_sent = stats.bytes_sent - last_bytes_sent_;
                int64_t delta_bytes_received = stats.bytes_received - last_bytes_received_;
                int64_t delta_bytes_total = delta_bytes_sent + delta_bytes_received;

                // Convert to Kbps: (bytes * 8 bits/byte) / (ms / 1000) / 1000 = Kbps
                stats.bandwidth_kbps = (delta_bytes_total * 8) / delta_time;
            }
        }

        // Update last sample
        last_stats_time_ = now;
        last_bytes_sent_ = stats.bytes_sent;
        last_bytes_received_ = stats.bytes_received;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] get_stats failed: {}", e.what());
    }

    return stats;
}

// ============================================================================
// Helper Methods - Pipeline Creation
// ============================================================================

bool WebRTCSession::create_pipeline() {
    try {
        LOG_DEBUG("[WebRTCSession] Creating pipeline...");

        // Create pipeline
        std::string pipeline_name = "call-pipeline-" + config_.session_id;
        pipeline_ = gst_pipeline_new(pipeline_name.c_str());
        if (!pipeline_) {
            LOG_ERROR("[WebRTCSession] Failed to create pipeline");
            return false;
        }

        // Create webrtcbin element
        webrtc_ = gst_element_factory_make("webrtcbin", "webrtc");
        if (!webrtc_) {
            LOG_ERROR("[WebRTCSession] Failed to create webrtcbin element");
            return false;
        }

        // Create audio source chain
        // pulsesrc → volume → queue → opusenc → rtpopuspay → webrtcbin
        const char *audio_src_name = config_.microphone_device.empty() ?
            "autoaudiosrc" : "pulsesrc";

        audio_src_ = gst_element_factory_make(audio_src_name, "audio_src");
        volume_ = gst_element_factory_make("volume", "volume");
        GstElement *queue = gst_element_factory_make("queue", "audio_queue");
        GstElement *opusenc = gst_element_factory_make("opusenc", "opus_encoder");
        GstElement *rtpopuspay = gst_element_factory_make("rtpopuspay", "rtp_payloader");

        if (!audio_src_ || !volume_ || !queue || !opusenc || !rtpopuspay) {
            LOG_ERROR("[WebRTCSession] Failed to create audio source elements");
            return false;
        }

        // Configure audio device if specified
        if (!config_.microphone_device.empty() && audio_src_name == std::string("pulsesrc")) {
            g_object_set(audio_src_, "device", config_.microphone_device.c_str(), nullptr);
            LOG_INFO("[WebRTCSession] Microphone device: {}", config_.microphone_device);
        }

        // Configure opus encoder for VoIP
        g_object_set(opusenc,
            "bitrate", 32000,
            "frame-size", 20,
            nullptr);

        // Add elements to pipeline
        gst_bin_add_many(GST_BIN(pipeline_), webrtc_, audio_src_, volume_, queue, opusenc, rtpopuspay, nullptr);

        // Link audio source chain
        if (!gst_element_link_many(audio_src_, volume_, queue, opusenc, rtpopuspay, nullptr)) {
            LOG_ERROR("[WebRTCSession] Failed to link audio source chain");
            return false;
        }

        // Link rtpopuspay to webrtcbin
        // Use capsfilter to specify exact RTP caps
        GstElement *capsfilter = gst_element_factory_make("capsfilter", "rtp_caps");
        if (!capsfilter) {
            LOG_ERROR("[WebRTCSession] Failed to create capsfilter");
            return false;
        }

        GstCaps *caps = gst_caps_new_simple("application/x-rtp",
            "media", G_TYPE_STRING, "audio",
            "encoding-name", G_TYPE_STRING, "OPUS",
            "payload", G_TYPE_INT, 97,
            "clock-rate", G_TYPE_INT, 48000,
            nullptr);
        g_object_set(capsfilter, "caps", caps, nullptr);
        gst_caps_unref(caps);

        gst_bin_add(GST_BIN(pipeline_), capsfilter);

        if (!gst_element_link_many(rtpopuspay, capsfilter, nullptr)) {
            LOG_ERROR("[WebRTCSession] Failed to link payloader to capsfilter");
            return false;
        }

        // Now link capsfilter to webrtcbin
        GstPad *caps_src = gst_element_get_static_pad(capsfilter, "src");
        GstPad *webrtc_sink = gst_element_request_pad_simple(webrtc_, "sink_%u");

        if (!caps_src || !webrtc_sink) {
            LOG_ERROR("[WebRTCSession] Failed to get pads for linking");
            return false;
        }

        GstPadLinkReturn link_ret = gst_pad_link(caps_src, webrtc_sink);

        gst_object_unref(caps_src);
        gst_object_unref(webrtc_sink);

        if (link_ret != GST_PAD_LINK_OK) {
            LOG_ERROR("[WebRTCSession] Failed to link capsfilter to webrtcbin: {}", link_ret);
            return false;
        }

        LOG_DEBUG("[WebRTCSession] Pipeline created successfully");
        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] create_pipeline exception: {}", e.what());
        return false;
    }
}

// ============================================================================
// Helper Methods - Configuration
// ============================================================================

bool WebRTCSession::configure_webrtcbin() {
    try {
        LOG_DEBUG("[WebRTCSession] Configuring webrtcbin...");

        // Set bundle policy to max-bundle (required for modern clients)
        g_object_set(webrtc_, "bundle-policy", GST_WEBRTC_BUNDLE_POLICY_MAX_BUNDLE, nullptr);

        // Set ICE transport policy
        if (config_.relay_only) {
            g_object_set(webrtc_, "ice-transport-policy",
                        GST_WEBRTC_ICE_TRANSPORT_POLICY_RELAY, nullptr);
            LOG_INFO("[WebRTCSession] ICE policy: RELAY only");
        } else {
            g_object_set(webrtc_, "ice-transport-policy",
                        GST_WEBRTC_ICE_TRANSPORT_POLICY_ALL, nullptr);
            LOG_INFO("[WebRTCSession] ICE policy: ALL");
        }

        // Set STUN server
        if (!config_.stun_server.empty()) {
            g_object_set(webrtc_, "stun-server", config_.stun_server.c_str(), nullptr);
            LOG_INFO("[WebRTCSession] STUN server: {}", config_.stun_server);
        }

        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] configure_webrtcbin exception: {}", e.what());
        return false;
    }
}

bool WebRTCSession::configure_proxy() {
    try {
        if (config_.proxy_host.empty() || config_.proxy_port == 0) {
            return true;  // No proxy configured
        }

        LOG_DEBUG("[WebRTCSession] Configuring proxy...");

        if (config_.proxy_type == "HTTP") {
            // Use webrtcbin's http-proxy property (GStreamer 1.22+)
            std::string proxy_url = "http://";

            if (!config_.proxy_username.empty()) {
                proxy_url += config_.proxy_username;
                if (!config_.proxy_password.empty()) {
                    proxy_url += ":" + config_.proxy_password;
                }
                proxy_url += "@";
            }

            proxy_url += config_.proxy_host + ":" + std::to_string(config_.proxy_port);

            g_object_set(webrtc_, "http-proxy", proxy_url.c_str(), nullptr);
            LOG_INFO("[WebRTCSession] HTTP proxy configured: {}:{}", config_.proxy_host, config_.proxy_port);

        } else if (config_.proxy_type == "SOCKS5") {
            // Access NiceAgent directly for SOCKS5 support
            GObject *webrtc_ice = nullptr;
            GObject *nice_agent = nullptr;

            // First get the GstWebRTCICE object
            g_object_get(webrtc_, "ice-agent", &webrtc_ice, nullptr);

            if (!webrtc_ice) {
                LOG_ERROR("[WebRTCSession] Failed to get ice-agent for SOCKS5 proxy");
                return false;
            }

            // Then get the actual NiceAgent from GstWebRTCNice
            g_object_get(webrtc_ice, "agent", &nice_agent, nullptr);

            if (!nice_agent) {
                LOG_ERROR("[WebRTCSession] Failed to get NiceAgent for SOCKS5 proxy");
                g_object_unref(webrtc_ice);
                return false;
            }

            // Set SOCKS5 proxy on the NiceAgent
            // NiceProxyType: NICE_PROXY_TYPE_SOCKS5 = 1
            g_object_set(nice_agent,
                "proxy-type", 1,  // NICE_PROXY_TYPE_SOCKS5
                "proxy-ip", config_.proxy_host.c_str(),
                "proxy-port", static_cast<guint>(config_.proxy_port),
                nullptr);

            if (!config_.proxy_username.empty()) {
                g_object_set(nice_agent,
                    "proxy-username", config_.proxy_username.c_str(),
                    "proxy-password", config_.proxy_password.c_str(),
                    nullptr);
            }

            LOG_INFO("[WebRTCSession] SOCKS5 proxy configured: {}:{}", config_.proxy_host, config_.proxy_port);

            g_object_unref(nice_agent);
            g_object_unref(webrtc_ice);

        } else {
            LOG_ERROR("[WebRTCSession] Unknown proxy type: {}", config_.proxy_type);
            return false;
        }

        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] configure_proxy exception: {}", e.what());
        return false;
    }
}

bool WebRTCSession::add_turn_servers() {
    try {
        if (config_.turn_servers.empty()) {
            return true;  // No TURN servers to add
        }

        LOG_DEBUG("[WebRTCSession] Adding TURN servers...");

        for (const auto &turn_uri : config_.turn_servers) {
            gboolean success = FALSE;
            g_signal_emit_by_name(webrtc_, "add-turn-server", turn_uri.c_str(), &success);

            if (success) {
                LOG_INFO("[WebRTCSession] Added TURN server: {}", turn_uri);
            } else {
                LOG_ERROR("[WebRTCSession] Failed to add TURN server: {}", turn_uri);
            }
        }

        return true;

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] add_turn_servers exception: {}", e.what());
        return false;
    }
}

// ============================================================================
// Signal Connection
// ============================================================================

void WebRTCSession::connect_signals() {
    try {
        LOG_DEBUG("[WebRTCSession] Connecting signals...");

        g_signal_connect(webrtc_, "on-negotiation-needed",
                        G_CALLBACK(on_negotiation_needed_static), this);

        g_signal_connect(webrtc_, "on-ice-candidate",
                        G_CALLBACK(on_ice_candidate_static), this);

        g_signal_connect(webrtc_, "pad-added",
                        G_CALLBACK(on_incoming_stream_static), this);

        g_signal_connect(webrtc_, "notify::ice-connection-state",
                        G_CALLBACK(on_ice_connection_state_static), this);

        g_signal_connect(webrtc_, "notify::ice-gathering-state",
                        G_CALLBACK(on_ice_gathering_state_static), this);

        g_signal_connect(webrtc_, "notify::signaling-state",
                        G_CALLBACK(on_signaling_state_static), this);

        LOG_DEBUG("[WebRTCSession] Signals connected");

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] connect_signals exception: {}", e.what());
    }
}

// ============================================================================
// Static Signal Handlers (dispatch to instance methods)
// ============================================================================

void WebRTCSession::on_negotiation_needed_static(GstElement *webrtc, gpointer user_data) {
    WebRTCSession *self = static_cast<WebRTCSession*>(user_data);
    self->on_negotiation_needed();
}

void WebRTCSession::on_offer_created_static(GstPromise *promise, gpointer user_data) {
    WebRTCSession *self = static_cast<WebRTCSession*>(user_data);
    self->on_offer_created(promise);
}

void WebRTCSession::on_answer_created_static(GstPromise *promise, gpointer user_data) {
    WebRTCSession *self = static_cast<WebRTCSession*>(user_data);
    self->on_answer_created(promise);
}

void WebRTCSession::on_ice_candidate_static(GstElement *webrtc, guint mlineindex,
                                            gchar *candidate, gpointer user_data) {
    WebRTCSession *self = static_cast<WebRTCSession*>(user_data);
    self->on_ice_candidate(mlineindex, candidate);
}

void WebRTCSession::on_ice_connection_state_static(GstElement *webrtc, GParamSpec *pspec,
                                                   gpointer user_data) {
    WebRTCSession *self = static_cast<WebRTCSession*>(user_data);
    self->on_ice_connection_state();
}

void WebRTCSession::on_ice_gathering_state_static(GstElement *webrtc, GParamSpec *pspec,
                                                  gpointer user_data) {
    WebRTCSession *self = static_cast<WebRTCSession*>(user_data);
    self->on_ice_gathering_state();
}

void WebRTCSession::on_signaling_state_static(GstElement *webrtc, GParamSpec *pspec,
                                             gpointer user_data) {
    WebRTCSession *self = static_cast<WebRTCSession*>(user_data);
    self->on_signaling_state();
}

void WebRTCSession::on_incoming_stream_static(GstElement *webrtc, GstPad *pad,
                                              gpointer user_data) {
    WebRTCSession *self = static_cast<WebRTCSession*>(user_data);
    self->on_incoming_stream(pad);
}

void WebRTCSession::on_offer_set_for_answer_static(GstPromise *promise, gpointer user_data) {
    WebRTCSession *self = static_cast<WebRTCSession*>(user_data);
    self->on_offer_set_for_answer();
}

// ============================================================================
// Instance Signal Handlers
// ============================================================================

void WebRTCSession::on_negotiation_needed() {
    LOG_INFO("[WebRTCSession] on_negotiation_needed");
    // This will be handled by explicit create_offer call
}

void WebRTCSession::on_offer_created(GstPromise *promise) {
    try {
        LOG_INFO("[WebRTCSession] on_offer_created");

        // FIXED: Don't use g_assert (can be compiled out in release builds)
        // Use proper error handling instead
        GstPromiseResult result = gst_promise_wait(promise);
        if (result != GST_PROMISE_RESULT_REPLIED) {
            LOG_ERROR("[WebRTCSession] Promise did not reply: {}", result);
            gst_promise_unref(promise);
            if (sdp_callback_) {
                sdp_callback_(false, SDPMessage(), "Promise failed to reply");
            }
            return;
        }

        const GstStructure *reply = gst_promise_get_reply(promise);
        GstWebRTCSessionDescription *offer = nullptr;
        gst_structure_get(reply, "offer", GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &offer, nullptr);
        gst_promise_unref(promise);

        if (!offer) {
            LOG_ERROR("[WebRTCSession] Failed to get offer from promise");
            if (sdp_callback_) {
                sdp_callback_(false, SDPMessage(), "Failed to create offer");
            }
            return;
        }

        // Set local description
        // FIXED: Don't interrupt/unref after emitting - GStreamer owns the promise
        GstPromise *local_promise = gst_promise_new();
        g_signal_emit_by_name(webrtc_, "set-local-description", offer, local_promise);
        // Promise is now owned by GStreamer - don't touch it!

        // Convert SDP to text
        gchar *sdp_text = gst_sdp_message_as_text(offer->sdp);
        std::string sdp_str(sdp_text);
        g_free(sdp_text);

        LOG_INFO("[WebRTCSession] Offer SDP created ({} bytes)", sdp_str.length());

        // Call user callback
        if (sdp_callback_) {
            SDPMessage sdp_msg(SDPMessage::Type::OFFER, sdp_str);
            sdp_callback_(true, sdp_msg, "");
        }

        gst_webrtc_session_description_free(offer);

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] on_offer_created exception: {}", e.what());
        if (sdp_callback_) {
            sdp_callback_(false, SDPMessage(), std::string("Exception: ") + e.what());
        }
    }
}

void WebRTCSession::on_answer_created(GstPromise *promise) {
    try {
        LOG_INFO("[WebRTCSession] on_answer_created");

        // FIXED: Don't use g_assert (can be compiled out in release builds)
        // Use proper error handling instead
        GstPromiseResult result = gst_promise_wait(promise);
        if (result != GST_PROMISE_RESULT_REPLIED) {
            LOG_ERROR("[WebRTCSession] Promise did not reply: {}", result);
            gst_promise_unref(promise);
            if (sdp_callback_) {
                sdp_callback_(false, SDPMessage(), "Promise failed to reply");
            }
            return;
        }

        const GstStructure *reply = gst_promise_get_reply(promise);
        GstWebRTCSessionDescription *answer = nullptr;
        gst_structure_get(reply, "answer", GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &answer, nullptr);
        gst_promise_unref(promise);

        if (!answer) {
            LOG_ERROR("[WebRTCSession] Failed to get answer from promise");
            if (sdp_callback_) {
                sdp_callback_(false, SDPMessage(), "Failed to create answer");
            }
            return;
        }

        // Set local description
        // FIXED: Don't interrupt/unref after emitting - GStreamer owns the promise
        GstPromise *local_promise = gst_promise_new();
        g_signal_emit_by_name(webrtc_, "set-local-description", answer, local_promise);
        // Promise is now owned by GStreamer - don't touch it!

        // Convert SDP to text
        gchar *sdp_text = gst_sdp_message_as_text(answer->sdp);
        std::string sdp_str(sdp_text);
        g_free(sdp_text);

        LOG_INFO("[WebRTCSession] Answer SDP created ({} bytes)", sdp_str.length());

        // Call user callback
        if (sdp_callback_) {
            SDPMessage sdp_msg(SDPMessage::Type::ANSWER, sdp_str);
            sdp_callback_(true, sdp_msg, "");
        }

        gst_webrtc_session_description_free(answer);

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] on_answer_created exception: {}", e.what());
        if (sdp_callback_) {
            sdp_callback_(false, SDPMessage(), std::string("Exception: ") + e.what());
        }
    }
}

void WebRTCSession::on_offer_set_for_answer() {
    try {
        LOG_INFO("[WebRTCSession] Offer set, creating answer...");

        // Now create answer
        GstPromise *promise = gst_promise_new_with_change_func(
            on_answer_created_static, this, nullptr);

        g_signal_emit_by_name(webrtc_, "create-answer", nullptr, promise);

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] on_offer_set_for_answer exception: {}", e.what());
        if (sdp_callback_) {
            sdp_callback_(false, SDPMessage(), std::string("Exception: ") + e.what());
        }
    }
}

void WebRTCSession::on_ice_candidate(guint mlineindex, const char *candidate) {
    try {
        // Candidate filtering for privacy (relay-only mode)
        if (config_.relay_only) {
            // In relay-only mode, only send relay candidates to prevent IP leaks
            if (strstr(candidate, "typ host") != nullptr ||
                strstr(candidate, "typ srflx") != nullptr) {
                // PRIVACY: Don't log IP addresses! Only log candidate type.
                LOG_DEBUG("[WebRTCSession] Filtering non-relay candidate (relay-only mode): type={}",
                         extract_candidate_type(candidate));
                return;  // Skip this candidate
            }
        }

        // PRIVACY: Don't log full candidate string (contains IP addresses)
        // Only log mline index and candidate type
        LOG_TRACE("[WebRTCSession] ICE candidate: mline={} type={}",
                 mlineindex, extract_candidate_type(candidate));

        if (ice_callback_) {
            ICECandidate ice_cand(candidate, mlineindex);
            ice_callback_(ice_cand);
        }

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] on_ice_candidate exception: {}", e.what());
    }
}

void WebRTCSession::on_ice_connection_state() {
    try {
        GstWebRTCICEConnectionState ice_state;
        g_object_get(webrtc_, "ice-connection-state", &ice_state, nullptr);

        const char *state_str = "";
        ConnectionState mapped_state = ConnectionState::NEW;

        switch (ice_state) {
            case GST_WEBRTC_ICE_CONNECTION_STATE_NEW:
                state_str = "NEW";
                mapped_state = ConnectionState::NEW;
                break;
            case GST_WEBRTC_ICE_CONNECTION_STATE_CHECKING:
                state_str = "CHECKING";
                mapped_state = ConnectionState::CHECKING;
                break;
            case GST_WEBRTC_ICE_CONNECTION_STATE_CONNECTED:
                state_str = "CONNECTED";
                mapped_state = ConnectionState::CONNECTED;
                break;
            case GST_WEBRTC_ICE_CONNECTION_STATE_COMPLETED:
                state_str = "COMPLETED";
                mapped_state = ConnectionState::COMPLETED;
                break;
            case GST_WEBRTC_ICE_CONNECTION_STATE_FAILED:
                state_str = "FAILED";
                mapped_state = ConnectionState::FAILED;
                break;
            case GST_WEBRTC_ICE_CONNECTION_STATE_DISCONNECTED:
                state_str = "DISCONNECTED";
                mapped_state = ConnectionState::DISCONNECTED;
                break;
            case GST_WEBRTC_ICE_CONNECTION_STATE_CLOSED:
                state_str = "CLOSED";
                mapped_state = ConnectionState::CLOSED;
                break;
        }

        LOG_INFO("[WebRTCSession] ICE connection state: {}", state_str);

        if (state_callback_) {
            state_callback_(mapped_state);
        }

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] on_ice_connection_state exception: {}", e.what());
    }
}

void WebRTCSession::on_ice_gathering_state() {
    try {
        GstWebRTCICEGatheringState gathering_state;
        g_object_get(webrtc_, "ice-gathering-state", &gathering_state, nullptr);

        const char *state_str = "";
        switch (gathering_state) {
            case GST_WEBRTC_ICE_GATHERING_STATE_NEW:
                state_str = "NEW";
                break;
            case GST_WEBRTC_ICE_GATHERING_STATE_GATHERING:
                state_str = "GATHERING";
                break;
            case GST_WEBRTC_ICE_GATHERING_STATE_COMPLETE:
                state_str = "COMPLETE";
                break;
        }

        LOG_TRACE("[WebRTCSession] ICE gathering state: {}", state_str);

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] on_ice_gathering_state exception: {}", e.what());
    }
}

void WebRTCSession::on_signaling_state() {
    try {
        GstWebRTCSignalingState state;
        g_object_get(webrtc_, "signaling-state", &state, nullptr);

        const char *state_str = "UNKNOWN";
        switch (state) {
            case GST_WEBRTC_SIGNALING_STATE_STABLE:
                state_str = "STABLE";
                break;
            case GST_WEBRTC_SIGNALING_STATE_CLOSED:
                state_str = "CLOSED";
                break;
            case GST_WEBRTC_SIGNALING_STATE_HAVE_LOCAL_OFFER:
                state_str = "HAVE_LOCAL_OFFER";
                break;
            case GST_WEBRTC_SIGNALING_STATE_HAVE_REMOTE_OFFER:
                state_str = "HAVE_REMOTE_OFFER";
                break;
            case GST_WEBRTC_SIGNALING_STATE_HAVE_LOCAL_PRANSWER:
                state_str = "HAVE_LOCAL_PRANSWER";
                break;
            case GST_WEBRTC_SIGNALING_STATE_HAVE_REMOTE_PRANSWER:
                state_str = "HAVE_REMOTE_PRANSWER";
                break;
        }

        LOG_INFO("[WebRTCSession] Signaling state: {}", state_str);

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] on_signaling_state exception: {}", e.what());
    }
}

void WebRTCSession::on_incoming_stream(GstPad *pad) {
    try {
        LOG_DEBUG("[WebRTCSession] Incoming stream on pad: {}", GST_PAD_NAME(pad));

        // Only handle src pads (incoming media)
        if (GST_PAD_DIRECTION(pad) != GST_PAD_SRC) {
            return;
        }

        // Create audio sink chain: rtpopusdepay → opusdec → queue → autoaudiosink
        GstElement *depay = gst_element_factory_make("rtpopusdepay", "depay");
        GstElement *decoder = gst_element_factory_make("opusdec", "decoder");
        GstElement *queue = gst_element_factory_make("queue", "recv_queue");

        const char *sink_name = config_.speakers_device.empty() ?
            "autoaudiosink" : "pulsesink";
        audio_sink_ = gst_element_factory_make(sink_name, "audio_sink");

        if (!depay || !decoder || !queue || !audio_sink_) {
            LOG_ERROR("[WebRTCSession] Failed to create audio sink elements");
            return;
        }

        // Configure speaker device if specified
        if (!config_.speakers_device.empty() && sink_name == std::string("pulsesink")) {
            g_object_set(audio_sink_, "device", config_.speakers_device.c_str(), nullptr);
        }

        // Add elements to pipeline
        gst_bin_add_many(GST_BIN(pipeline_), depay, decoder, queue, audio_sink_, nullptr);

        // Link elements
        if (!gst_element_link_many(depay, decoder, queue, audio_sink_, nullptr)) {
            LOG_ERROR("[WebRTCSession] Failed to link audio sink chain");
            return;
        }

        // Sync state with parent
        gst_element_sync_state_with_parent(depay);
        gst_element_sync_state_with_parent(decoder);
        gst_element_sync_state_with_parent(queue);
        gst_element_sync_state_with_parent(audio_sink_);

        // Link webrtcbin pad to depay
        GstPad *sink_pad = gst_element_get_static_pad(depay, "sink");
        if (gst_pad_link(pad, sink_pad) != GST_PAD_LINK_OK) {
            LOG_ERROR("[WebRTCSession] Failed to link incoming pad to depay");
        } else {
            LOG_DEBUG("[WebRTCSession] Incoming stream linked successfully");
        }
        gst_object_unref(sink_pad);

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] on_incoming_stream exception: {}", e.what());
    }
}

// ============================================================================
// Stats Parsing
// ============================================================================

void WebRTCSession::parse_stats(const GstStructure *stats_struct, Stats &stats) const {
    try {
        // Helper struct to pass around parsing context
        struct ParseContext {
            Stats *stats;
            std::string selected_local_candidate_id;
            std::string selected_remote_candidate_id;
        };

        ParseContext ctx = { &stats, "", "" };

        // Iterate through all stats entries
        gst_structure_foreach(stats_struct,
            [](GQuark field_id, const GValue *value, gpointer user_data) -> gboolean {
                ParseContext *ctx = static_cast<ParseContext*>(user_data);

                const gchar *field_name = g_quark_to_string(field_id);

                if (!GST_VALUE_HOLDS_STRUCTURE(value)) {
                    LOG_DEBUG("[WebRTCSession] parse_stats: Field {} is not a structure", field_name);
                    return TRUE;  // Continue
                }

                const GstStructure *stat = gst_value_get_structure(value);

                // Get type enum value
                GstWebRTCStatsType type_enum = GST_WEBRTC_STATS_CODEC;  // Default
                if (!gst_structure_get_enum(stat, "type",
                    g_type_from_name("GstWebRTCStatsType"), (gint*)&type_enum)) {
                    return TRUE;  // Skip entries without type
                }

                // Parse by stat type
                if (type_enum == GST_WEBRTC_STATS_TRANSPORT) {
                    // Selected candidate pair ID
                    const gchar *selected_pair = gst_structure_get_string(stat, "selected-candidate-pair-id");
                    if (selected_pair) {
                        ctx->selected_local_candidate_id = selected_pair;  // Store for later lookup
                    }

                } else if (type_enum == GST_WEBRTC_STATS_CANDIDATE_PAIR) {
                    // Check if this is the selected (nominated) pair
                    gboolean selected = FALSE;
                    gst_structure_get_boolean(stat, "selected", &selected);

                    if (selected) {
                        // Get local and remote candidate IDs
                        const gchar *local_id = gst_structure_get_string(stat, "local-candidate-id");
                        const gchar *remote_id = gst_structure_get_string(stat, "remote-candidate-id");

                        if (local_id) ctx->selected_local_candidate_id = local_id;
                        if (remote_id) ctx->selected_remote_candidate_id = remote_id;

                        // Get bytes sent/received
                        guint64 bytes_sent = 0, bytes_received = 0;
                        gst_structure_get_uint64(stat, "bytes-sent", &bytes_sent);
                        gst_structure_get_uint64(stat, "bytes-received", &bytes_received);
                        ctx->stats->bytes_sent = bytes_sent;
                        ctx->stats->bytes_received = bytes_received;

                        // Get RTT (round-trip time)
                        gdouble rtt = 0.0;
                        if (gst_structure_get_double(stat, "round-trip-time", &rtt)) {
                            ctx->stats->rtt_ms = static_cast<int>(rtt * 1000);  // Convert seconds to ms
                        }
                    }

                } else if (type_enum == GST_WEBRTC_STATS_LOCAL_CANDIDATE) {
                    // Parse local candidate info
                    const gchar *candidate_id = gst_structure_get_string(stat, "id");
                    const gchar *candidate_type = gst_structure_get_string(stat, "candidate-type");
                    const gchar *ip = gst_structure_get_string(stat, "address");
                    if (!ip) ip = gst_structure_get_string(stat, "ip");
                    guint port = 0;
                    gst_structure_get_uint(stat, "port", &port);

                    if (ip && candidate_type) {
                        // Format: "IP:port (type)"
                        std::string formatted = std::string(ip) + ":" +
                                              std::to_string(port) + " (" +
                                              candidate_type + ")";
                        ctx->stats->local_candidates.push_back(formatted);

                        // If this is the selected candidate, use its type for connection_type
                        if (candidate_id && ctx->selected_local_candidate_id == candidate_id) {
                            if (g_strcmp0(candidate_type, "host") == 0) {
                                ctx->stats->connection_type = "P2P (direct)";
                            } else if (g_strcmp0(candidate_type, "srflx") == 0) {
                                ctx->stats->connection_type = "P2P (srflx - NAT hole-punching)";
                            } else if (g_strcmp0(candidate_type, "relay") == 0) {
                                ctx->stats->connection_type = std::string("TURN relay (") + ip + ")";
                            }
                        }
                    }

                } else if (type_enum == GST_WEBRTC_STATS_REMOTE_CANDIDATE) {
                    // Parse remote candidate info
                    const gchar *candidate_type = gst_structure_get_string(stat, "candidate-type");
                    const gchar *ip = gst_structure_get_string(stat, "address");
                    if (!ip) ip = gst_structure_get_string(stat, "ip");
                    guint port = 0;
                    gst_structure_get_uint(stat, "port", &port);

                    if (ip && candidate_type) {
                        // Format: "IP:port (type)"
                        std::string formatted = std::string(ip) + ":" +
                                              std::to_string(port) + " (" +
                                              candidate_type + ")";
                        ctx->stats->remote_candidates.push_back(formatted);
                    }

                } else if (type_enum == GST_WEBRTC_STATS_INBOUND_RTP) {
                    // Packet loss
                    guint packets_lost = 0, packets_received = 0;
                    gst_structure_get_uint(stat, "packets-lost", &packets_lost);
                    gst_structure_get_uint(stat, "packets-received", &packets_received);

                    if (packets_received > 0) {
                        ctx->stats->packet_loss_pct =
                            (100.0 * packets_lost) / (packets_lost + packets_received);
                    }

                    // Jitter (in seconds, convert to ms)
                    gdouble jitter = 0.0;
                    if (gst_structure_get_double(stat, "jitter", &jitter)) {
                        ctx->stats->jitter_ms = static_cast<int>(jitter * 1000);
                    }
                }

                return TRUE;  // Continue iteration
            },
            &ctx);

        // Set connection state based on ICE state
        if (stats.ice_connection_state == "completed" || stats.ice_connection_state == "connected") {
            stats.connection_state = "connected";
        } else if (stats.ice_connection_state == "checking") {
            stats.connection_state = "connecting";
        } else if (stats.ice_connection_state == "failed") {
            stats.connection_state = "failed";
        } else if (stats.ice_connection_state == "disconnected") {
            stats.connection_state = "disconnected";
        } else if (stats.ice_connection_state == "closed") {
            stats.connection_state = "closed";
        } else {
            stats.connection_state = "new";
        }

        // Default connection type if not determined
        if (stats.connection_type.empty()) {
            stats.connection_type = "--";
        }

    } catch (const std::exception &e) {
        LOG_ERROR("[WebRTCSession] parse_stats exception: {}", e.what());
    }
}

} // namespace drunk_call
