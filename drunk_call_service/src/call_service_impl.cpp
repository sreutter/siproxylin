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

    LOG_DEBUG("CreateSession called: session_id={}", request->session_id());

    // Phase 4.3: Implement session creation
    // - Create CallSession struct
    // - Create WebRTCSession
    // - Configure proxy, TURN, audio devices
    // - Set callbacks for ICE candidates, state changes
    // - Add to SessionManager
    // See: docs/CALLS/4-GRPC-PLAN.md lines 408-486

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "CreateSession not yet implemented (Phase 4.3)");
}

grpc::Status CallServiceImpl::EndSession(
    grpc::ServerContext* context,
    const call::EndSessionRequest* request,
    call::Empty* response) {

    LOG_DEBUG("EndSession called: session_id={}", request->session_id());

    // Phase 4.7: Implement session cleanup
    // - Get session from SessionManager
    // - Set active = false
    // - Shutdown event queue
    // - Stop WebRTC session
    // - Remove from SessionManager

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "EndSession not yet implemented (Phase 4.7)");
}

// ============================================================================
// SDP Operations
// ============================================================================

grpc::Status CallServiceImpl::CreateOffer(
    grpc::ServerContext* context,
    const call::CreateOfferRequest* request,
    call::SDPResponse* response) {

    LOG_DEBUG("CreateOffer called: session_id={}", request->session_id());

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

    LOG_DEBUG("CreateAnswer called: session_id={}", request->session_id());

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

    LOG_DEBUG("SetRemoteDescription called: session_id={}, type={}",
              request->session_id(), request->sdp_type());

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

    LOG_DEBUG("AddICECandidate called: session_id={}, mid={}, mline_index={}",
              request->session_id(), request->sdp_mid(), request->sdp_mline_index());

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

    LOG_DEBUG("StreamEvents called: session_id={}", request->session_id());

    // Phase 4.3: Implement event streaming
    // - Get session from SessionManager
    // - Loop: pop from event_queue (1s timeout)
    // - Write event to stream
    // - Check context->IsCancelled() for client disconnect
    // - Continue until session->active = false
    // See: docs/CALLS/GSTREAMER-THREADING.md Pattern 2

    return grpc::Status(grpc::StatusCode::UNIMPLEMENTED,
                        "StreamEvents not yet implemented (Phase 4.3)");
}

// ============================================================================
// Audio Device Management
// ============================================================================

grpc::Status CallServiceImpl::ListAudioDevices(
    grpc::ServerContext* context,
    const call::Empty* request,
    call::ListAudioDevicesResponse* response) {

    LOG_DEBUG("ListAudioDevices called");

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

    LOG_DEBUG("SetMute called: session_id={}, muted={}",
              request->session_id(), request->muted());

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

    LOG_DEBUG("GetStats called: session_id={}", request->session_id());

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

    // Heartbeat: No logging (called every 5s from Python)
    // Just return OK to indicate service is alive
    return grpc::Status::OK;
}

grpc::Status CallServiceImpl::Shutdown(
    grpc::ServerContext* context,
    const call::Empty* request,
    call::Empty* response) {

    LOG_INFO("Shutdown requested via gRPC");

    // Phase 4.7: Implement graceful shutdown
    // - Set shutdown_requested_ = true
    // - Cleanup all sessions
    // - Signal gRPC server to stop
    // - Return OK

    shutdown_requested_ = true;
    return grpc::Status::OK;
}

} // namespace drunk_call
