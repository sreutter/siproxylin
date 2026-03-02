/**
 * WebRTCSession Class Test
 *
 * Purpose: Test WebRTCSession class (MediaSession interface)
 * Tests: Session creation, offer generation, cleanup
 *
 * Build: make test_webrtc_session
 * Run: ./test_webrtc_session
 */

#include "../../src/media_session.h"
#include "../../src/webrtc_session.h"
#include "../../src/session_factory.cpp"
#include "../../src/webrtc_session.cpp"
#include "../../src/rtp_session.cpp"

#include <gst/gst.h>
#include <iostream>
#include <thread>
#include <chrono>

using namespace drunk_call;

static GMainLoop *main_loop = nullptr;
static bool offer_received = false;
static bool ice_candidates_received = false;

void on_sdp_ready(bool success, const SDPMessage &sdp, const std::string &error) {
    if (success) {
        std::cout << "\n=== SDP Offer Created ===" << std::endl;
        std::cout << "Type: " << (sdp.type == SDPMessage::Type::OFFER ? "OFFER" : "ANSWER") << std::endl;
        std::cout << "Length: " << sdp.sdp_text.length() << " bytes" << std::endl;
        std::cout << "\n--- SDP Content (first 500 chars) ---" << std::endl;
        std::cout << sdp.sdp_text.substr(0, 500) << std::endl;
        std::cout << "..." << std::endl;
        std::cout << "---" << std::endl;

        offer_received = true;

        // Give it a moment for ICE candidates, then quit
        std::thread([]{
            std::this_thread::sleep_for(std::chrono::seconds(2));
            if (main_loop) {
                g_main_loop_quit(main_loop);
            }
        }).detach();

    } else {
        std::cerr << "\n✗ SDP creation failed: " << error << std::endl;
        if (main_loop) {
            g_main_loop_quit(main_loop);
        }
    }
}

void on_ice_candidate(const ICECandidate &candidate) {
    std::cout << "[ICE] mline=" << candidate.sdp_mline_index
              << " candidate=" << candidate.candidate.substr(0, 60) << "..." << std::endl;
    ice_candidates_received = true;
}

void on_state_change(MediaSession::ConnectionState state) {
    const char *state_str = "UNKNOWN";
    switch (state) {
        case MediaSession::ConnectionState::NEW: state_str = "NEW"; break;
        case MediaSession::ConnectionState::CHECKING: state_str = "CHECKING"; break;
        case MediaSession::ConnectionState::CONNECTED: state_str = "CONNECTED"; break;
        case MediaSession::ConnectionState::COMPLETED: state_str = "COMPLETED"; break;
        case MediaSession::ConnectionState::FAILED: state_str = "FAILED"; break;
        case MediaSession::ConnectionState::DISCONNECTED: state_str = "DISCONNECTED"; break;
        case MediaSession::ConnectionState::CLOSED: state_str = "CLOSED"; break;
    }
    std::cout << "[STATE] Connection state: " << state_str << std::endl;
}

int main(int argc, char *argv[]) {
    gst_init(&argc, &argv);

    std::cout << "=== WebRTCSession Class Test ===" << std::endl;
    std::cout << std::endl;

    // Test 1: Factory availability check
    std::cout << "Test 1: Checking WebRTC availability..." << std::endl;
    if (!SessionFactory::is_webrtc_available()) {
        std::cerr << "✗ WebRTC not available" << std::endl;
        return 1;
    }
    std::cout << "✓ WebRTC available" << std::endl;
    std::cout << std::endl;

    // Test 2: Create session using factory
    std::cout << "Test 2: Creating session via factory..." << std::endl;
    SessionConfig config;
    config.session_id = "test-session-1";
    config.peer_jid = "test@example.com";
    config.relay_only = false;
    config.stun_server = "stun://stun.l.google.com:19302";
    config.preferred_type = MediaSession::Type::WEBRTC;

    auto session = SessionFactory::create(config);
    if (!session) {
        std::cerr << "✗ Failed to create session" << std::endl;
        return 1;
    }
    std::cout << "✓ Session created, type: "
              << (session->get_type() == MediaSession::Type::WEBRTC ? "WEBRTC" : "RTP")
              << std::endl;
    std::cout << std::endl;

    // Test 3: Initialize session
    std::cout << "Test 3: Initializing session..." << std::endl;
    if (!session->initialize(config)) {
        std::cerr << "✗ Failed to initialize session" << std::endl;
        return 1;
    }
    std::cout << "✓ Session initialized" << std::endl;
    std::cout << std::endl;

    // Test 4: Set callbacks
    std::cout << "Test 4: Setting callbacks..." << std::endl;
    session->set_ice_candidate_callback(on_ice_candidate);
    session->set_state_callback(on_state_change);
    std::cout << "✓ Callbacks set" << std::endl;
    std::cout << std::endl;

    // Test 5: Start pipeline
    std::cout << "Test 5: Starting pipeline..." << std::endl;
    if (!session->start()) {
        std::cerr << "✗ Failed to start pipeline" << std::endl;
        return 1;
    }
    std::cout << "✓ Pipeline started (PLAYING)" << std::endl;
    std::cout << std::endl;

    // Test 6: Create offer
    std::cout << "Test 6: Creating offer..." << std::endl;
    std::cout << "(This will trigger async SDP generation)" << std::endl;
    session->create_offer(on_sdp_ready);

    // Run main loop to process async events
    std::cout << "\nRunning main loop to process events..." << std::endl;
    std::cout << "(Will auto-quit after SDP + 2 seconds)" << std::endl;
    std::cout << std::endl;

    main_loop = g_main_loop_new(nullptr, FALSE);
    g_main_loop_run(main_loop);
    g_main_loop_unref(main_loop);

    std::cout << std::endl;
    std::cout << "Main loop exited" << std::endl;

    // Test 7: Verify results
    std::cout << std::endl << "Test 7: Verifying results..." << std::endl;
    if (!offer_received) {
        std::cerr << "✗ Offer not received" << std::endl;
        return 1;
    }
    std::cout << "✓ Offer received" << std::endl;

    if (!ice_candidates_received) {
        std::cerr << "⚠ Warning: No ICE candidates received (may need STUN server)" << std::endl;
    } else {
        std::cout << "✓ ICE candidates received" << std::endl;
    }
    std::cout << std::endl;

    // Test 8: Mute test
    std::cout << "Test 8: Testing mute..." << std::endl;
    if (!session->set_mute(true)) {
        std::cerr << "⚠ Mute failed" << std::endl;
    } else {
        std::cout << "✓ Muted" << std::endl;
    }
    if (!session->set_mute(false)) {
        std::cerr << "⚠ Unmute failed" << std::endl;
    } else {
        std::cout << "✓ Unmuted" << std::endl;
    }
    std::cout << std::endl;

    // Test 9: Cleanup
    std::cout << "Test 9: Stopping session..." << std::endl;
    if (!session->stop()) {
        std::cerr << "⚠ Stop failed" << std::endl;
    } else {
        std::cout << "✓ Session stopped" << std::endl;
    }
    std::cout << std::endl;

    std::cout << "=== All tests passed ===" << std::endl;

    return 0;
}
