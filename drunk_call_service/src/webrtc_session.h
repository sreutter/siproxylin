/**
 * WebRTC Session Implementation (webrtcbin)
 *
 * Standard path - uses GStreamer webrtcbin element
 * Handles ICE, DTLS, SRTP automatically
 *
 * See: docs/CALLS/PLAN.md for full architecture
 * Reference: docs/CALLS/webrtcbin-reference.cpp for implementation patterns
 */

#ifndef WEBRTC_SESSION_H
#define WEBRTC_SESSION_H

#include "media_session.h"
#include <gst/gst.h>
#include <mutex>
#include <condition_variable>
#include <chrono>

namespace drunk_call {

class WebRTCSession : public MediaSession {
public:
    WebRTCSession();
    ~WebRTCSession() override;

    // MediaSession interface
    bool initialize(const SessionConfig &config) override;
    bool start() override;
    bool stop() override;

    void create_offer(SDPCallback callback) override;
    void create_answer(const SDPMessage &remote_offer, SDPCallback callback) override;
    bool set_remote_description(const SDPMessage &remote_sdp) override;

    void set_ice_candidate_callback(ICECandidateCallback callback) override;
    bool add_remote_ice_candidate(const ICECandidate &candidate) override;

    void set_state_callback(StateCallback callback) override;

    bool set_mute(bool muted) override;
    bool is_muted() const override { return is_muted_; }

    Stats get_stats() const override;

    GstElement* get_pipeline() const override { return pipeline_; }
    Type get_type() const override { return Type::WEBRTC; }

private:
    // Pipeline elements
    GstElement *pipeline_;
    GstElement *webrtc_;
    GstElement *audio_src_;
    GstElement *audio_sink_;  // Created dynamically on pad-added
    GstElement *volume_;      // For mute functionality

    // Configuration
    SessionConfig config_;
    bool is_muted_;
    bool is_outgoing_;  // true = offerer, false = answerer

    // Callbacks
    SDPCallback sdp_callback_;
    ICECandidateCallback ice_callback_;
    StateCallback state_callback_;

    // Synchronization for async SDP operations
    std::mutex sdp_mutex_;
    std::condition_variable sdp_ready_;
    SDPMessage local_sdp_;
    bool sdp_done_;

    // GStreamer signal handlers (static, dispatch to instance methods)
    static void on_negotiation_needed_static(GstElement *webrtc, gpointer user_data);
    static void on_offer_created_static(GstPromise *promise, gpointer user_data);
    static void on_answer_created_static(GstPromise *promise, gpointer user_data);
    static void on_ice_candidate_static(GstElement *webrtc, guint mlineindex,
                                       gchar *candidate, gpointer user_data);
    static void on_ice_connection_state_static(GstElement *webrtc, GParamSpec *pspec,
                                              gpointer user_data);
    static void on_ice_gathering_state_static(GstElement *webrtc, GParamSpec *pspec,
                                              gpointer user_data);
    static void on_signaling_state_static(GstElement *webrtc, GParamSpec *pspec,
                                         gpointer user_data);
    static void on_incoming_stream_static(GstElement *webrtc, GstPad *pad,
                                         gpointer user_data);

    // Instance methods called by static handlers
    void on_negotiation_needed();
    void on_offer_created(GstPromise *promise);
    void on_answer_created(GstPromise *promise);
    void on_ice_candidate(guint mlineindex, const char *candidate);
    void on_ice_connection_state();
    void on_ice_gathering_state();
    void on_signaling_state();
    void on_incoming_stream(GstPad *pad);

    // Helper methods
    bool create_pipeline();
    bool configure_webrtcbin();
    bool configure_proxy();
    bool add_turn_servers();
    void connect_signals();

    // Promise callback for set-remote-description before answer
    static void on_offer_set_for_answer_static(GstPromise *promise, gpointer user_data);
    void on_offer_set_for_answer();

    // Stats helpers
    static void on_stats_received_static(GstPromise *promise, gpointer user_data);
    void parse_stats(const GstStructure *stats, Stats &result) const;

    // Bandwidth tracking (for get_stats)
    mutable std::chrono::steady_clock::time_point last_stats_time_;
    mutable uint64_t last_bytes_sent_;
    mutable uint64_t last_bytes_received_;
};

} // namespace drunk_call

#endif // WEBRTC_SESSION_H
