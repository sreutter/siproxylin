/**
 * Media Session Abstraction Layer
 *
 * Purpose: Allow switching between webrtcbin (standard) and rtpbin (exotic cases)
 * Pattern: Abstract base class with polymorphic implementations
 *
 * See: docs/CALLS/START.md requirement for dual-path support
 */

#ifndef MEDIA_SESSION_H
#define MEDIA_SESSION_H

#include <string>
#include <functional>
#include <memory>
#include <gst/gst.h>

namespace drunk_call {

// Forward declarations
struct SessionConfig;
struct SDPMessage;
struct ICECandidate;

/**
 * Abstract interface for media session implementations
 *
 * Implementations:
 * - WebRTCSession: Uses webrtcbin (standard path, full WebRTC stack)
 * - RTPSession: Uses rtpbin (exotic path, manual ICE/DTLS)
 */
class MediaSession {
public:
    virtual ~MediaSession() = default;

    // Lifecycle
    virtual bool initialize(const SessionConfig &config) = 0;
    virtual bool start() = 0;  // Set pipeline to PLAYING
    virtual bool stop() = 0;   // Set to NULL and cleanup

    // SDP operations (async via callbacks)
    using SDPCallback = std::function<void(bool success, const SDPMessage &sdp, const std::string &error)>;
    virtual void create_offer(SDPCallback callback) = 0;
    virtual void create_answer(const SDPMessage &remote_offer, SDPCallback callback) = 0;
    virtual bool set_remote_description(const SDPMessage &remote_sdp) = 0;

    // ICE operations
    using ICECandidateCallback = std::function<void(const ICECandidate &candidate)>;
    virtual void set_ice_candidate_callback(ICECandidateCallback callback) = 0;
    virtual bool add_remote_ice_candidate(const ICECandidate &candidate) = 0;

    // State callbacks
    enum class ConnectionState {
        NEW, CHECKING, CONNECTED, COMPLETED, FAILED, DISCONNECTED, CLOSED
    };
    using StateCallback = std::function<void(ConnectionState state)>;
    virtual void set_state_callback(StateCallback callback) = 0;

    // Audio control
    virtual bool set_mute(bool muted) = 0;
    virtual bool is_muted() const = 0;

    // Statistics
    struct Stats {
        uint64_t bytes_sent;
        uint64_t bytes_received;
        double packet_loss_pct;
        int rtt_ms;
        int jitter_ms;
        std::string connection_type;
    };
    virtual Stats get_stats() const = 0;

    // Pipeline access (for debugging/visualization)
    virtual GstElement* get_pipeline() const = 0;

    // Implementation type query
    enum class Type { WEBRTC, RTP };
    virtual Type get_type() const = 0;
};

/**
 * Session configuration
 */
struct SessionConfig {
    std::string session_id;
    std::string peer_jid;

    // Audio devices
    std::string microphone_device;  // Empty = default
    std::string speakers_device;    // Empty = default

    // Network configuration
    bool relay_only;                // ICE transport policy
    std::string stun_server;        // "stun://host:port"
    std::vector<std::string> turn_servers;  // "turn://user:pass@host:port"

    // Audio processing (WebRTC DSP)
    bool echo_cancel;
    bool noise_suppression;
    bool gain_control;

    // Implementation selection
    MediaSession::Type preferred_type;  // Hint for factory
};

/**
 * SDP message wrapper
 */
struct SDPMessage {
    enum class Type { OFFER, ANSWER };
    Type type;
    std::string sdp_text;

    SDPMessage() : type(Type::OFFER) {}
    SDPMessage(Type t, const std::string &text) : type(t), sdp_text(text) {}
};

/**
 * ICE candidate wrapper
 */
struct ICECandidate {
    std::string candidate;      // Full candidate string
    uint32_t sdp_mline_index;   // Media line index (0 for audio)
    std::string sdp_mid;        // Media ID (optional with mlineindex)

    ICECandidate() : sdp_mline_index(0) {}
    ICECandidate(const std::string &cand, uint32_t idx)
        : candidate(cand), sdp_mline_index(idx) {}
};

/**
 * Factory for creating media sessions
 *
 * Usage:
 *   auto session = SessionFactory::create(config);
 *   session->initialize(config);
 */
class SessionFactory {
public:
    static std::unique_ptr<MediaSession> create(const SessionConfig &config);

    // Check if implementation is available
    static bool is_webrtc_available();
    static bool is_rtp_available();
};

} // namespace drunk_call

#endif // MEDIA_SESSION_H
