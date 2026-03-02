/**
 * WebRTC Session Implementation
 *
 * Implements MediaSession using GStreamer webrtcbin element
 * Reference: docs/CALLS/1-PIPELINE-PLAN.md
 */

#include "webrtc_session.h"
#include <gst/sdp/sdp.h>
#include <gst/webrtc/webrtc.h>
#include <iostream>
#include <stdexcept>

namespace drunk_call {

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
{
}

WebRTCSession::~WebRTCSession() {
    try {
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
            std::cerr << "[WebRTCSession] Failed to create pipeline" << std::endl;
            return false;
        }

        if (!configure_webrtcbin()) {
            std::cerr << "[WebRTCSession] Failed to configure webrtcbin" << std::endl;
            return false;
        }

        if (!configure_proxy()) {
            std::cerr << "[WebRTCSession] Failed to configure proxy" << std::endl;
            return false;
        }

        if (!add_turn_servers()) {
            std::cerr << "[WebRTCSession] Failed to add TURN servers" << std::endl;
            return false;
        }

        connect_signals();

        std::cout << "[WebRTCSession] Initialized session: " << config_.session_id << std::endl;
        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] Initialize failed: " << e.what() << std::endl;
        return false;
    }
}

bool WebRTCSession::start() {
    try {
        if (!pipeline_) {
            std::cerr << "[WebRTCSession] Pipeline not initialized" << std::endl;
            return false;
        }

        std::cout << "[WebRTCSession] Starting pipeline..." << std::endl;
        GstStateChangeReturn ret = gst_element_set_state(pipeline_, GST_STATE_PLAYING);

        if (ret == GST_STATE_CHANGE_FAILURE) {
            std::cerr << "[WebRTCSession] Failed to set pipeline to PLAYING" << std::endl;
            return false;
        }

        std::cout << "[WebRTCSession] Pipeline PLAYING" << std::endl;
        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] Start failed: " << e.what() << std::endl;
        return false;
    }
}

bool WebRTCSession::stop() {
    try {
        if (!pipeline_) {
            return true;  // Already stopped
        }

        std::cout << "[WebRTCSession] Stopping pipeline..." << std::endl;
        gst_element_set_state(pipeline_, GST_STATE_NULL);
        gst_object_unref(pipeline_);

        pipeline_ = nullptr;
        webrtc_ = nullptr;
        audio_src_ = nullptr;
        audio_sink_ = nullptr;

        std::cout << "[WebRTCSession] Pipeline stopped and cleaned up" << std::endl;
        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] Stop failed: " << e.what() << std::endl;
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

        std::cout << "[WebRTCSession] Creating offer..." << std::endl;

        // Create promise for async SDP generation
        GstPromise *promise = gst_promise_new_with_change_func(
            on_offer_created_static, this, nullptr);

        // Emit create-offer signal on webrtcbin
        g_signal_emit_by_name(webrtc_, "create-offer", nullptr, promise);

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] create_offer failed: " << e.what() << std::endl;
        if (callback) {
            callback(false, SDPMessage(), std::string("Exception: ") + e.what());
        }
    }
}

void WebRTCSession::create_answer(const SDPMessage &remote_offer, SDPCallback callback) {
    try {
        is_outgoing_ = false;
        sdp_callback_ = callback;

        std::cout << "[WebRTCSession] Creating answer..." << std::endl;

        // First set remote description (the offer)
        if (!set_remote_description(remote_offer)) {
            std::cerr << "[WebRTCSession] Failed to set remote offer" << std::endl;
            if (callback) {
                callback(false, SDPMessage(), "Failed to set remote offer");
            }
            return;
        }

        // Create answer after remote description is set
        // This will be triggered by on_offer_set_for_answer callback

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] create_answer failed: " << e.what() << std::endl;
        if (callback) {
            callback(false, SDPMessage(), std::string("Exception: ") + e.what());
        }
    }
}

bool WebRTCSession::set_remote_description(const SDPMessage &remote_sdp) {
    try {
        std::cout << "[WebRTCSession] Setting remote description..." << std::endl;

        // Parse SDP text
        GstSDPMessage *sdp_msg;
        if (gst_sdp_message_new(&sdp_msg) != GST_SDP_OK) {
            std::cerr << "[WebRTCSession] Failed to create SDP message" << std::endl;
            return false;
        }

        if (gst_sdp_message_parse_buffer(
                (const guint8*)remote_sdp.sdp_text.c_str(),
                remote_sdp.sdp_text.length(),
                sdp_msg) != GST_SDP_OK) {
            std::cerr << "[WebRTCSession] Failed to parse SDP" << std::endl;
            gst_sdp_message_free(sdp_msg);
            return false;
        }

        // Create WebRTC session description
        GstWebRTCSDPType sdp_type = (remote_sdp.type == SDPMessage::Type::OFFER) ?
            GST_WEBRTC_SDP_TYPE_OFFER : GST_WEBRTC_SDP_TYPE_ANSWER;

        GstWebRTCSessionDescription *desc = gst_webrtc_session_description_new(
            sdp_type, sdp_msg);

        if (!desc) {
            std::cerr << "[WebRTCSession] Failed to create session description" << std::endl;
            return false;
        }

        // Set remote description with promise
        GstPromise *promise;
        if (!is_outgoing_ && remote_sdp.type == SDPMessage::Type::OFFER) {
            // Answerer receiving offer - need to create answer afterward
            promise = gst_promise_new_with_change_func(
                on_offer_set_for_answer_static, this, nullptr);
        } else {
            // Offerer receiving answer - just set it
            promise = gst_promise_new();
        }

        g_signal_emit_by_name(webrtc_, "set-remote-description", desc, promise);
        gst_promise_interrupt(promise);
        gst_promise_unref(promise);

        std::cout << "[WebRTCSession] Remote description set" << std::endl;
        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] set_remote_description failed: " << e.what() << std::endl;
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
        std::cout << "[WebRTCSession] Adding remote ICE candidate: mline="
                  << candidate.sdp_mline_index << std::endl;

        g_signal_emit_by_name(webrtc_, "add-ice-candidate",
                             candidate.sdp_mline_index,
                             candidate.candidate.c_str());

        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] add_remote_ice_candidate failed: " << e.what() << std::endl;
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
            std::cout << "[WebRTCSession] Audio " << (muted ? "muted" : "unmuted") << std::endl;
        }

        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] set_mute failed: " << e.what() << std::endl;
        return false;
    }
}

// ============================================================================
// Statistics
// ============================================================================

MediaSession::Stats WebRTCSession::get_stats() const {
    Stats stats = {};

    try {
        // TODO: Implement stats retrieval using get-stats action
        // For now, return empty stats

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] get_stats failed: " << e.what() << std::endl;
    }

    return stats;
}

// ============================================================================
// Helper Methods - Pipeline Creation
// ============================================================================

bool WebRTCSession::create_pipeline() {
    try {
        std::cout << "[WebRTCSession] Creating pipeline..." << std::endl;

        // Create pipeline
        std::string pipeline_name = "call-pipeline-" + config_.session_id;
        pipeline_ = gst_pipeline_new(pipeline_name.c_str());
        if (!pipeline_) {
            std::cerr << "[WebRTCSession] Failed to create pipeline" << std::endl;
            return false;
        }

        // Create webrtcbin element
        webrtc_ = gst_element_factory_make("webrtcbin", "webrtc");
        if (!webrtc_) {
            std::cerr << "[WebRTCSession] Failed to create webrtcbin element" << std::endl;
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
            std::cerr << "[WebRTCSession] Failed to create audio source elements" << std::endl;
            return false;
        }

        // Configure audio device if specified
        if (!config_.microphone_device.empty() && audio_src_name == std::string("pulsesrc")) {
            g_object_set(audio_src_, "device", config_.microphone_device.c_str(), nullptr);
            std::cout << "[WebRTCSession] Microphone device: " << config_.microphone_device << std::endl;
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
            std::cerr << "[WebRTCSession] Failed to link audio source chain" << std::endl;
            return false;
        }

        // Link rtpopuspay to webrtcbin
        // Use capsfilter to specify exact RTP caps
        GstElement *capsfilter = gst_element_factory_make("capsfilter", "rtp_caps");
        if (!capsfilter) {
            std::cerr << "[WebRTCSession] Failed to create capsfilter" << std::endl;
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
            std::cerr << "[WebRTCSession] Failed to link payloader to capsfilter" << std::endl;
            return false;
        }

        // Now link capsfilter to webrtcbin
        GstPad *caps_src = gst_element_get_static_pad(capsfilter, "src");
        GstPad *webrtc_sink = gst_element_request_pad_simple(webrtc_, "sink_%u");

        if (!caps_src || !webrtc_sink) {
            std::cerr << "[WebRTCSession] Failed to get pads for linking" << std::endl;
            return false;
        }

        GstPadLinkReturn link_ret = gst_pad_link(caps_src, webrtc_sink);

        gst_object_unref(caps_src);
        gst_object_unref(webrtc_sink);

        if (link_ret != GST_PAD_LINK_OK) {
            std::cerr << "[WebRTCSession] Failed to link capsfilter to webrtcbin: " << link_ret << std::endl;
            return false;
        }

        std::cout << "[WebRTCSession] Pipeline created successfully" << std::endl;
        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] create_pipeline exception: " << e.what() << std::endl;
        return false;
    }
}

// ============================================================================
// Helper Methods - Configuration
// ============================================================================

bool WebRTCSession::configure_webrtcbin() {
    try {
        std::cout << "[WebRTCSession] Configuring webrtcbin..." << std::endl;

        // Set bundle policy to max-bundle (required for modern clients)
        g_object_set(webrtc_, "bundle-policy", GST_WEBRTC_BUNDLE_POLICY_MAX_BUNDLE, nullptr);

        // Set ICE transport policy
        if (config_.relay_only) {
            g_object_set(webrtc_, "ice-transport-policy",
                        GST_WEBRTC_ICE_TRANSPORT_POLICY_RELAY, nullptr);
            std::cout << "[WebRTCSession] ICE policy: RELAY only" << std::endl;
        } else {
            g_object_set(webrtc_, "ice-transport-policy",
                        GST_WEBRTC_ICE_TRANSPORT_POLICY_ALL, nullptr);
            std::cout << "[WebRTCSession] ICE policy: ALL" << std::endl;
        }

        // Set STUN server
        if (!config_.stun_server.empty()) {
            g_object_set(webrtc_, "stun-server", config_.stun_server.c_str(), nullptr);
            std::cout << "[WebRTCSession] STUN server: " << config_.stun_server << std::endl;
        }

        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] configure_webrtcbin exception: " << e.what() << std::endl;
        return false;
    }
}

bool WebRTCSession::configure_proxy() {
    try {
        if (config_.proxy_host.empty() || config_.proxy_port == 0) {
            return true;  // No proxy configured
        }

        std::cout << "[WebRTCSession] Configuring proxy..." << std::endl;

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
            std::cout << "[WebRTCSession] HTTP proxy configured: "
                      << config_.proxy_host << ":" << config_.proxy_port << std::endl;

        } else if (config_.proxy_type == "SOCKS5") {
            // Access NiceAgent directly for SOCKS5 support
            GObject *webrtc_ice = nullptr;
            GObject *nice_agent = nullptr;

            // First get the GstWebRTCICE object
            g_object_get(webrtc_, "ice-agent", &webrtc_ice, nullptr);

            if (!webrtc_ice) {
                std::cerr << "[WebRTCSession] Failed to get ice-agent for SOCKS5 proxy" << std::endl;
                return false;
            }

            // Then get the actual NiceAgent from GstWebRTCNice
            g_object_get(webrtc_ice, "agent", &nice_agent, nullptr);

            if (!nice_agent) {
                std::cerr << "[WebRTCSession] Failed to get NiceAgent for SOCKS5 proxy" << std::endl;
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

            std::cout << "[WebRTCSession] SOCKS5 proxy configured: "
                      << config_.proxy_host << ":" << config_.proxy_port << std::endl;

            g_object_unref(nice_agent);
            g_object_unref(webrtc_ice);

        } else {
            std::cerr << "[WebRTCSession] Unknown proxy type: " << config_.proxy_type << std::endl;
            return false;
        }

        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] configure_proxy exception: " << e.what() << std::endl;
        return false;
    }
}

bool WebRTCSession::add_turn_servers() {
    try {
        if (config_.turn_servers.empty()) {
            return true;  // No TURN servers to add
        }

        std::cout << "[WebRTCSession] Adding TURN servers..." << std::endl;

        for (const auto &turn_uri : config_.turn_servers) {
            gboolean success = FALSE;
            g_signal_emit_by_name(webrtc_, "add-turn-server", turn_uri.c_str(), &success);

            if (success) {
                std::cout << "[WebRTCSession] Added TURN server: " << turn_uri << std::endl;
            } else {
                std::cerr << "[WebRTCSession] Failed to add TURN server: " << turn_uri << std::endl;
            }
        }

        return true;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] add_turn_servers exception: " << e.what() << std::endl;
        return false;
    }
}

// ============================================================================
// Signal Connection
// ============================================================================

void WebRTCSession::connect_signals() {
    try {
        std::cout << "[WebRTCSession] Connecting signals..." << std::endl;

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

        std::cout << "[WebRTCSession] Signals connected" << std::endl;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] connect_signals exception: " << e.what() << std::endl;
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
    std::cout << "[WebRTCSession] on_negotiation_needed" << std::endl;
    // This will be handled by explicit create_offer call
}

void WebRTCSession::on_offer_created(GstPromise *promise) {
    try {
        std::cout << "[WebRTCSession] on_offer_created" << std::endl;

        g_assert(gst_promise_wait(promise) == GST_PROMISE_RESULT_REPLIED);

        const GstStructure *reply = gst_promise_get_reply(promise);
        GstWebRTCSessionDescription *offer = nullptr;
        gst_structure_get(reply, "offer", GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &offer, nullptr);
        gst_promise_unref(promise);

        if (!offer) {
            std::cerr << "[WebRTCSession] Failed to get offer from promise" << std::endl;
            if (sdp_callback_) {
                sdp_callback_(false, SDPMessage(), "Failed to create offer");
            }
            return;
        }

        // Set local description
        GstPromise *local_promise = gst_promise_new();
        g_signal_emit_by_name(webrtc_, "set-local-description", offer, local_promise);
        gst_promise_interrupt(local_promise);
        gst_promise_unref(local_promise);

        // Convert SDP to text
        gchar *sdp_text = gst_sdp_message_as_text(offer->sdp);
        std::string sdp_str(sdp_text);
        g_free(sdp_text);

        std::cout << "[WebRTCSession] Offer SDP created (" << sdp_str.length() << " bytes)" << std::endl;

        // Call user callback
        if (sdp_callback_) {
            SDPMessage sdp_msg(SDPMessage::Type::OFFER, sdp_str);
            sdp_callback_(true, sdp_msg, "");
        }

        gst_webrtc_session_description_free(offer);

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] on_offer_created exception: " << e.what() << std::endl;
        if (sdp_callback_) {
            sdp_callback_(false, SDPMessage(), std::string("Exception: ") + e.what());
        }
    }
}

void WebRTCSession::on_answer_created(GstPromise *promise) {
    try {
        std::cout << "[WebRTCSession] on_answer_created" << std::endl;

        g_assert(gst_promise_wait(promise) == GST_PROMISE_RESULT_REPLIED);

        const GstStructure *reply = gst_promise_get_reply(promise);
        GstWebRTCSessionDescription *answer = nullptr;
        gst_structure_get(reply, "answer", GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &answer, nullptr);
        gst_promise_unref(promise);

        if (!answer) {
            std::cerr << "[WebRTCSession] Failed to get answer from promise" << std::endl;
            if (sdp_callback_) {
                sdp_callback_(false, SDPMessage(), "Failed to create answer");
            }
            return;
        }

        // Set local description
        GstPromise *local_promise = gst_promise_new();
        g_signal_emit_by_name(webrtc_, "set-local-description", answer, local_promise);
        gst_promise_interrupt(local_promise);
        gst_promise_unref(local_promise);

        // Convert SDP to text
        gchar *sdp_text = gst_sdp_message_as_text(answer->sdp);
        std::string sdp_str(sdp_text);
        g_free(sdp_text);

        std::cout << "[WebRTCSession] Answer SDP created (" << sdp_str.length() << " bytes)" << std::endl;

        // Call user callback
        if (sdp_callback_) {
            SDPMessage sdp_msg(SDPMessage::Type::ANSWER, sdp_str);
            sdp_callback_(true, sdp_msg, "");
        }

        gst_webrtc_session_description_free(answer);

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] on_answer_created exception: " << e.what() << std::endl;
        if (sdp_callback_) {
            sdp_callback_(false, SDPMessage(), std::string("Exception: ") + e.what());
        }
    }
}

void WebRTCSession::on_offer_set_for_answer() {
    try {
        std::cout << "[WebRTCSession] Offer set, creating answer..." << std::endl;

        // Now create answer
        GstPromise *promise = gst_promise_new_with_change_func(
            on_answer_created_static, this, nullptr);

        g_signal_emit_by_name(webrtc_, "create-answer", nullptr, promise);

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] on_offer_set_for_answer exception: " << e.what() << std::endl;
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
                std::cout << "[WebRTCSession] Filtering non-relay candidate (relay-only mode): "
                          << candidate << std::endl;
                return;  // Skip this candidate
            }
        }

        std::cout << "[WebRTCSession] ICE candidate: mline=" << mlineindex
                  << " candidate=" << candidate << std::endl;

        if (ice_callback_) {
            ICECandidate ice_cand(candidate, mlineindex);
            ice_callback_(ice_cand);
        }

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] on_ice_candidate exception: " << e.what() << std::endl;
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

        std::cout << "[WebRTCSession] ICE connection state: " << state_str << std::endl;

        if (state_callback_) {
            state_callback_(mapped_state);
        }

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] on_ice_connection_state exception: " << e.what() << std::endl;
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

        std::cout << "[WebRTCSession] ICE gathering state: " << state_str << std::endl;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] on_ice_gathering_state exception: " << e.what() << std::endl;
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

        std::cout << "[WebRTCSession] Signaling state: " << state_str << std::endl;

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] on_signaling_state exception: " << e.what() << std::endl;
    }
}

void WebRTCSession::on_incoming_stream(GstPad *pad) {
    try {
        std::cout << "[WebRTCSession] Incoming stream on pad: " << GST_PAD_NAME(pad) << std::endl;

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
            std::cerr << "[WebRTCSession] Failed to create audio sink elements" << std::endl;
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
            std::cerr << "[WebRTCSession] Failed to link audio sink chain" << std::endl;
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
            std::cerr << "[WebRTCSession] Failed to link incoming pad to depay" << std::endl;
        } else {
            std::cout << "[WebRTCSession] Incoming stream linked successfully" << std::endl;
        }
        gst_object_unref(sink_pad);

    } catch (const std::exception &e) {
        std::cerr << "[WebRTCSession] on_incoming_stream exception: " << e.what() << std::endl;
    }
}

} // namespace drunk_call
