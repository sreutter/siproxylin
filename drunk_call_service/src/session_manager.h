/**
 * Thread-Safe Session Manager (Phase 4.1)
 *
 * Provides mutex-protected session map for gRPC handlers + GLib callbacks
 *
 * LOGGING: Use LOG_*() macros (logger.h) for all application logging
 *          DO NOT use std::cout/std::cerr in production code
 *          See: docs/LOGGING-POLICY.md
 *
 * Usage: docs/THREAD-INFRASTRUCTURE-USAGE.md
 * Threading: docs/CALLS/GSTREAMER-THREADING.md
 */

#ifndef SESSION_MANAGER_H
#define SESSION_MANAGER_H

#include "webrtc_session.h"
#include "thread_safe_queue.h"
#include <string>
#include <memory>
#include <unordered_map>
#include <mutex>
#include <atomic>
#include <chrono>

// Forward declarations (proto types will be defined when we integrate with gRPC)
// For now, using placeholder - will be replaced with actual proto::CallEvent
struct CallEvent {
    std::string session_id;
    // TODO: Replace with actual proto::CallEvent when integrating gRPC
};

namespace drunk_call {

/**
 * Call session data structure.
 *
 * Shared between threads:
 * - Created in gRPC thread (CreateSession RPC)
 * - Accessed by GLib thread (GStreamer callbacks push events)
 * - Accessed by StreamEvents thread (polls event queue)
 *
 * Pattern from docs/CALLS/4-GRPC-PLAN.md lines 123-140
 */
struct CallSession {
    std::string session_id;           // Jingle session ID (from Python)
    std::string peer_jid;             // Remote peer JID

    // WebRTC session (library layer)
    std::unique_ptr<WebRTCSession> webrtc;

    // Event streaming
    std::shared_ptr<ThreadSafeQueue<CallEvent>> event_queue;

    // State
    std::atomic<bool> active;         // Session is active (not ended)
    std::chrono::steady_clock::time_point created_at;
};

/**
 * Thread-safe session manager.
 *
 * Provides mutex-protected access to session map.
 * Used by gRPC handlers (thread pool) and GStreamer callbacks (GLib thread).
 *
 * Pattern from docs/CALLS/4-GRPC-PLAN.md lines 186-209
 */
class SessionManager {
public:
    SessionManager() = default;
    ~SessionManager() = default;

    // Non-copyable
    SessionManager(const SessionManager&) = delete;
    SessionManager& operator=(const SessionManager&) = delete;

    /**
     * Get session by ID (thread-safe).
     *
     * @param session_id Jingle session ID
     * @return Shared pointer to session, or nullptr if not found
     */
    std::shared_ptr<CallSession> get_session(const std::string& session_id);

    /**
     * Add session to map (thread-safe).
     *
     * @param session_id Jingle session ID
     * @param session Session object
     */
    void add_session(const std::string& session_id, std::shared_ptr<CallSession> session);

    /**
     * Remove session from map (thread-safe).
     *
     * @param session_id Jingle session ID
     */
    void remove_session(const std::string& session_id);

    /**
     * Get all session IDs (thread-safe).
     * Used for cleanup on shutdown.
     *
     * @return Vector of session IDs
     */
    std::vector<std::string> get_all_session_ids();

private:
    std::unordered_map<std::string, std::shared_ptr<CallSession>> sessions_;
    mutable std::mutex mutex_;
};

} // namespace drunk_call

#endif // SESSION_MANAGER_H
