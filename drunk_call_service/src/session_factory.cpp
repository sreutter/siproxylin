/**
 * Session Factory Implementation
 *
 * Selects appropriate MediaSession implementation based on:
 * - User preference (config.preferred_type)
 * - Available GStreamer plugins
 * - Fallback logic
 */

#include "media_session.h"
#include "webrtc_session.h"
#include "rtp_session.h"
#include <gst/gst.h>

namespace drunk_call {

std::unique_ptr<MediaSession> SessionFactory::create(const SessionConfig &config) {
    // Check availability
    bool webrtc_ok = is_webrtc_available();
    bool rtp_ok = is_rtp_available();

    // Prefer webrtcbin unless explicitly requested otherwise
    if (config.preferred_type == MediaSession::Type::WEBRTC && webrtc_ok) {
        return std::make_unique<WebRTCSession>();
    }

    if (config.preferred_type == MediaSession::Type::RTP && rtp_ok) {
        return std::make_unique<RTPSession>();
    }

    // Fallback logic
    if (webrtc_ok) {
        return std::make_unique<WebRTCSession>();
    }

    if (rtp_ok) {
        return std::make_unique<RTPSession>();
    }

    // No implementation available
    return nullptr;
}

bool SessionFactory::is_webrtc_available() {
    GstRegistry *registry = gst_registry_get();
    GstPlugin *plugin = gst_registry_find_plugin(registry, "webrtc");

    if (!plugin) {
        return false;
    }

    gst_object_unref(plugin);
    return true;
}

bool SessionFactory::is_rtp_available() {
    GstRegistry *registry = gst_registry_get();

    // Check for required plugins
    const char *required[] = {"rtp", "rtpmanager", "nice", "dtls", nullptr};
    for (int i = 0; required[i]; i++) {
        GstPlugin *plugin = gst_registry_find_plugin(registry, required[i]);
        if (!plugin) {
            return false;
        }
        gst_object_unref(plugin);
    }

    return true;
}

} // namespace drunk_call
