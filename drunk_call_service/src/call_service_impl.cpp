/**
 * CallService gRPC Implementation (Phase 4.2)
 *
 * Phase 4.2: Stub implementations returning UNIMPLEMENTED
 * Phase 4.3+: Implement actual logic per docs/CALLS/4-GRPC-PLAN.md
 *
 * LOGGING: Use LOG_*() macros (logger.h) for all application logging
 *          DO NOT use std::cout/std::cerr in production code
 *          See: docs/LOGGING-POLICY.md
 */

#include "call_service_impl.h"
#include "logger.h"

// Global shutdown flag (defined in main.cpp, global namespace)
extern std::atomic<bool> g_shutdown_requested;

namespace drunk_call {

CallServiceImpl::CallServiceImpl()
    : shutdown_requested_(false) {
    LOG_INFO("CallServiceImpl initialized");
}

CallServiceImpl::~CallServiceImpl() {
    LOG_INFO("CallServiceImpl destroyed");
}

// ============================================================================
// Session Lifecycle
// ============================================================================

grpc::Status CallServiceImpl::CreateSession(
    grpc::ServerContext* context,
    const call::CreateSessionRequest* request,
    call::CreateSessionResponse* response) {

    std::string session_id = request->session_id();
    LOG_DEBUG("gRPC: CreateSession - session_id={}", session_id);
    LOG_INFO("CreateSession: session_id={}, peer={}", session_id, request->peer_jid());

    try {
        // Check if session already exists
        auto existing = session_manager_.get_session(session_id);
        if (existing) {
            LOG_WARN("Session already exists: {}", session_id);
            response->set_success(false);
            response->set_error("Session already exists");
            return grpc::Status::OK;
        }

        // Create session
        auto session = std::make_shared<CallSession>();
        session->session_id = session_id;
        session->peer_jid = request->peer_jid();
        session->event_queue = std::make_shared<ThreadSafeQueue<call::CallEvent>>();
        session->active = true;
        session->created_at = std::chrono::steady_clock::now();

        // Create WebRTC session
        session->webrtc = std::make_unique<WebRTCSession>();

        // Configure session
        SessionConfig config;
        config.session_id = session_id;
        config.microphone_device = request->microphone_device();
        config.speakers_device = request->speakers_device();
        config.relay_only = request->relay_only();

        // Proxy config
        if (!request->proxy_host().empty()) {
            config.proxy_host = request->proxy_host();
            config.proxy_port = request->proxy_port();
            config.proxy_username = request->proxy_username();
            config.proxy_password = request->proxy_password();
            config.proxy_type = request->proxy_type();
            LOG_DEBUG("Session {}: Proxy configured: {}:{} ({})",
                     session_id, config.proxy_host, config.proxy_port, config.proxy_type);
        }

        // TURN config
        if (!request->turn_server().empty()) {
            // Build TURN URL: turn://username:password@host:port
            std::string turn_url = "turn://";
            if (!request->turn_username().empty()) {
                turn_url += request->turn_username();
                if (!request->turn_password().empty()) {
                    turn_url += ":" + request->turn_password();
                }
                turn_url += "@";
            }
            turn_url += request->turn_server();
            config.turn_servers.push_back(turn_url);
            LOG_DEBUG("Session {}: TURN server configured: {}", session_id, turn_url);
        }

        // Audio processing
        config.echo_cancel = request->echo_cancel();
        config.noise_suppression = request->noise_suppression();
        config.gain_control = request->gain_control();

        // Set callbacks (BEFORE initialize to avoid race)
        // ICE candidate callback - fires in GLib thread, pushes to queue
        session->webrtc->set_ice_candidate_callback([session](const ICECandidate& cand) {
            // THIS RUNS IN GLIB THREAD!
            call::CallEvent event;
            event.set_session_id(session->session_id);
            auto* ice_event = event.mutable_ice_candidate();
            ice_event->set_candidate(cand.candidate);
            ice_event->set_sdp_mid(cand.sdp_mid);
            ice_event->set_sdp_mline_index(cand.sdp_mline_index);
            session->event_queue->push(event);
            LOG_DEBUG("Session {}: ICE candidate pushed to queue", session->session_id);
        });

        // State callback - fires in GLib thread, pushes to queue
        session->webrtc->set_state_callback([session](MediaSession::ConnectionState state) {
            // THIS RUNS IN GLIB THREAD!
            call::CallEvent event;
            event.set_session_id(session->session_id);
            auto* state_event = event.mutable_connection_state();

            // Map connection state to proto enum
            switch (state) {
                case MediaSession::ConnectionState::NEW:
                    state_event->set_state(call::ConnectionStateEvent::NEW);
                    break;
                case MediaSession::ConnectionState::CHECKING:
                    state_event->set_state(call::ConnectionStateEvent::CHECKING);
                    break;
                case MediaSession::ConnectionState::CONNECTED:
                case MediaSession::ConnectionState::COMPLETED:
                    state_event->set_state(call::ConnectionStateEvent::CONNECTED);
                    break;
                case MediaSession::ConnectionState::FAILED:
                    state_event->set_state(call::ConnectionStateEvent::FAILED);
                    break;
                case MediaSession::ConnectionState::DISCONNECTED:
                    state_event->set_state(call::ConnectionStateEvent::DISCONNECTED);
                    break;
                case MediaSession::ConnectionState::CLOSED:
                    state_event->set_state(call::ConnectionStateEvent::CLOSED);
                    break;
            }

            session->event_queue->push(event);
            LOG_DEBUG("Session {}: State change pushed to queue: {}",
                     session->session_id, static_cast<int>(state));
        });

        // Initialize WebRTC session
        if (!session->webrtc->initialize(config)) {
            LOG_ERROR("Session {}: Failed to initialize WebRTC session", session_id);
            response->set_success(false);
            response->set_error("Failed to initialize WebRTC session");
            return grpc::Status::OK;
        }

        // Add to SessionManager
        session_manager_.add_session(session_id, session);

        LOG_INFO("Session created successfully: {}, peer: {}", session_id, request->peer_jid());
        response->set_success(true);
        return grpc::Status::OK;

    } catch (const std::exception& e) {
        LOG_ERROR("Exception in CreateSession: {}", e.what());
        response->set_success(false);
        response->set_error(std::string("Exception: ") + e.what());
        return grpc::Status::OK;
    }
}

grpc::Status CallServiceImpl::EndSession(
    grpc::ServerContext* context,
    const call::EndSessionRequest* request,
    call::Empty* response) {

    std::string session_id = request->session_id();
    LOG_DEBUG("gRPC: EndSession - session_id={}", session_id);
    LOG_INFO("EndSession: session_id={}", session_id);

    // Get session from SessionManager
    auto session = session_manager_.get_session(session_id);
    if (!session) {
        LOG_WARN("EndSession: Session not found (already ended?): {}", session_id);
        return grpc::Status::OK;  // Not an error - session may have already ended
    }

    // Calculate session duration
    auto duration = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::steady_clock::now() - session->created_at
    ).count();

    // Mark session as inactive (stops StreamEvents loop)
    session->active = false;

    // Shutdown event queue (wakes any blocked StreamEvents threads)
    session->event_queue->shutdown();

    // Stop WebRTC session
    if (session->webrtc) {
        session->webrtc->stop();
    }

    // Remove from SessionManager
    // Note: StreamEvents may still hold a shared_ptr - that's OK!
    // Session will be destroyed when the last shared_ptr is released
    session_manager_.remove_session(session_id);

    LOG_INFO("Session ended: {}, duration: {}s", session_id, duration);
    return grpc::Status::OK;
}

// ============================================================================
// SDP Operations
// ============================================================================

grpc::Status CallServiceImpl::CreateOffer(
    grpc::ServerContext* context,
    const call::CreateOfferRequest* request,
    call::SDPResponse* response) {

    LOG_DEBUG("gRPC: CreateOffer - session_id={}", request->session_id());
    LOG_WARN("Method not implemented: CreateOffer (Phase 4.4)");

    // Phase 4.4: Implement offer creation
    // - Get session from SessionManager
    // - Set SDP callback with condition variable
    // - Call webrtc->create_offer()
    // - Wait for callback (max 10s timeout)
    // - Return SDP in response
    // See: docs/CALLS/GSTREAMER-THREADING.md Pattern 1

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "CreateOffer not yet implemented (Phase 4.4)");
}

grpc::Status CallServiceImpl::CreateAnswer(
    grpc::ServerContext* context,
    const call::CreateAnswerRequest* request,
    call::SDPResponse* response) {

    LOG_DEBUG("gRPC: CreateAnswer - session_id={}", request->session_id());
    LOG_WARN("Method not implemented: CreateAnswer (Phase 4.4)");

    // Phase 4.4: Implement answer creation
    // - Get session from SessionManager
    // - Parse remote SDP from request
    // - Set SDP callback with condition variable
    // - Call webrtc->create_answer(remote_sdp)
    // - Wait for callback (max 10s timeout)
    // - Return SDP in response

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "CreateAnswer not yet implemented (Phase 4.4)");
}

grpc::Status CallServiceImpl::SetRemoteDescription(
    grpc::ServerContext* context,
    const call::SetRemoteDescriptionRequest* request,
    call::Empty* response) {

    LOG_DEBUG("gRPC: SetRemoteDescription - session_id={}, type={}",
              request->session_id(), request->sdp_type());
    LOG_WARN("Method not implemented: SetRemoteDescription (Phase 4.4)");

    // Phase 4.4: Implement remote SDP setting
    // - Get session from SessionManager
    // - Parse remote SDP and type (offer/answer)
    // - Call webrtc->set_remote_description(sdp)
    // - Return success/error

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "SetRemoteDescription not yet implemented (Phase 4.4)");
}

// ============================================================================
// ICE Candidate Handling
// ============================================================================

grpc::Status CallServiceImpl::AddICECandidate(
    grpc::ServerContext* context,
    const call::AddICECandidateRequest* request,
    call::Empty* response) {

    LOG_DEBUG("gRPC: AddICECandidate - session_id={}, mid={}, mline_index={}",
              request->session_id(), request->sdp_mid(), request->sdp_mline_index());
    LOG_WARN("Method not implemented: AddICECandidate (Phase 4.5)");

    // Phase 4.5: Implement ICE candidate addition
    // - Get session from SessionManager
    // - Create ICECandidate struct from request
    // - Call webrtc->add_remote_ice_candidate(candidate)
    // - Return success/error

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "AddICECandidate not yet implemented (Phase 4.5)");
}

// ============================================================================
// Event Streaming (C++ → Python)
// ============================================================================

grpc::Status CallServiceImpl::StreamEvents(
    grpc::ServerContext* context,
    const call::StreamEventsRequest* request,
    grpc::ServerWriter<call::CallEvent>* writer) {

    std::string session_id = request->session_id();
    LOG_DEBUG("gRPC: StreamEvents - session_id={}", session_id);
    LOG_INFO("StreamEvents started: session_id={}", session_id);

    // Get session from SessionManager
    auto session = session_manager_.get_session(session_id);
    if (!session) {
        LOG_ERROR("StreamEvents: Session not found: {}", session_id);
        return grpc::Status(grpc::StatusCode::NOT_FOUND, "Session not found");
    }

    // Stream events until session ends or client disconnects
    int event_count = 0;
    while (session->active && !context->IsCancelled()) {
        call::CallEvent event;

        // Pop from queue with 1s timeout (allows checking cancellation)
        if (session->event_queue->pop(event, std::chrono::milliseconds(1000))) {
            // Write event to stream
            if (!writer->Write(event)) {
                LOG_WARN("StreamEvents: Failed to write event to stream (client disconnected?): {}",
                        session_id);
                break;
            }
            event_count++;
            LOG_DEBUG("StreamEvents: Event #{} sent to client: {}", event_count, session_id);
        }
        // Timeout is OK - just loop and check cancellation
    }

    if (context->IsCancelled()) {
        LOG_INFO("StreamEvents cancelled by client: {}, events sent: {}",
                session_id, event_count);
    } else {
        LOG_INFO("StreamEvents completed: {}, events sent: {}", session_id, event_count);
    }

    return grpc::Status::OK;
}

// ============================================================================
// Audio Device Management
// ============================================================================

grpc::Status CallServiceImpl::ListAudioDevices(
    grpc::ServerContext* context,
    const call::Empty* request,
    call::ListAudioDevicesResponse* response) {

    LOG_DEBUG("gRPC: ListAudioDevices");
    LOG_WARN("Method not implemented: ListAudioDevices (Phase 4.6)");

    // Phase 4.6: Implement device enumeration
    // - Call DeviceEnumerator::list_audio_inputs()
    // - Call DeviceEnumerator::list_audio_outputs()
    // - Populate response with device list

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "ListAudioDevices not yet implemented (Phase 4.6)");
}

grpc::Status CallServiceImpl::SetMute(
    grpc::ServerContext* context,
    const call::SetMuteRequest* request,
    call::Empty* response) {

    LOG_DEBUG("gRPC: SetMute - session_id={}, muted={}",
              request->session_id(), request->muted());
    LOG_WARN("Method not implemented: SetMute (Phase 4.6)");

    // Phase 4.6: Implement mute control
    // - Get session from SessionManager
    // - Call webrtc->set_mute(muted)
    // - Return success/error

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "SetMute not yet implemented (Phase 4.6)");
}

// ============================================================================
// Statistics
// ============================================================================

grpc::Status CallServiceImpl::GetStats(
    grpc::ServerContext* context,
    const call::GetStatsRequest* request,
    call::GetStatsResponse* response) {

    LOG_DEBUG("gRPC: GetStats - session_id={}", request->session_id());
    LOG_WARN("Method not implemented: GetStats (Phase 4.6)");

    // Phase 4.6: Implement statistics retrieval
    // - Get session from SessionManager
    // - Call webrtc->get_stats()
    // - Populate response with stats

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "GetStats not yet implemented (Phase 4.6)");
}

// ============================================================================
// Service Management
// ============================================================================

grpc::Status CallServiceImpl::Heartbeat(
    grpc::ServerContext* context,
    const call::Empty* request,
    call::Empty* response) {

    // Heartbeat: Minimal logging (called every 5s from Python)
    // Only log at TRACE level to avoid spam
    LOG_TRACE("gRPC: Heartbeat");
    return grpc::Status::OK;
}

grpc::Status CallServiceImpl::Shutdown(
    grpc::ServerContext* context,
    const call::Empty* request,
    call::Empty* response) {

    LOG_DEBUG("gRPC: Shutdown");
    LOG_INFO("Shutdown requested via gRPC");

    // Cleanup all sessions
    cleanup_all_sessions();

    // Set global shutdown flag (main() will detect and shutdown)
    ::g_shutdown_requested = true;

    shutdown_requested_ = true;
    return grpc::Status::OK;
}

void CallServiceImpl::cleanup_all_sessions() {
    LOG_INFO("Cleaning up all sessions...");

    // Get all session IDs
    auto session_ids = session_manager_.get_all_session_ids();

    if (session_ids.empty()) {
        LOG_INFO("No active sessions to cleanup");
        return;
    }

    LOG_INFO("Cleaning up {} active session(s)", session_ids.size());

    // Cleanup each session
    for (const auto& session_id : session_ids) {
        auto session = session_manager_.get_session(session_id);
        if (session) {
            LOG_DEBUG("Cleaning up session: {}", session_id);

            // Calculate session duration
            auto duration = std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::steady_clock::now() - session->created_at
            ).count();

            // Mark session as inactive
            session->active = false;

            // Shutdown event queue (unblocks any waiting StreamEvents)
            session->event_queue->shutdown();

            // Stop WebRTC session
            if (session->webrtc) {
                session->webrtc->stop();
            }

            LOG_INFO("Session cleaned up: {}, duration: {}s", session_id, duration);
        }

        // Remove from SessionManager
        session_manager_.remove_session(session_id);
    }

    LOG_INFO("All sessions cleaned up successfully");
}

} // namespace drunk_call
