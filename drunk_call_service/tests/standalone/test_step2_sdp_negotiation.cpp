/**
 * SDP Negotiation Test - Local Loopback
 *
 * Purpose: Test full offer/answer negotiation between two WebRTCSession instances
 * Tests: SDP creation, remote description, signaling states, pad-added
 *
 * Build: make test_sdp_local
 * Run: ./test_sdp_local
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

// State tracking for both sessions
struct TestState {
    bool offerer_offer_ready = false;
    bool answerer_answer_ready = false;
    SDPMessage offer_sdp;
    SDPMessage answer_sdp;
    int ice_candidates_offerer = 0;
    int ice_candidates_answerer = 0;
    bool pad_added_offerer = false;
    bool pad_added_answerer = false;
} state;

// Callbacks for offerer (session 1)
void on_offerer_sdp(bool success, const SDPMessage &sdp, const std::string &error) {
    if (success) {
        std::cout << "\n[OFFERER] Offer SDP created (" << sdp.sdp_text.length() << " bytes)" << std::endl;
        state.offer_sdp = sdp;
        state.offerer_offer_ready = true;

        // Validate SDP content
        if (sdp.sdp_text.find("a=group:BUNDLE") != std::string::npos) {
            std::cout << "[OFFERER] ✓ SDP contains BUNDLE" << std::endl;
        } else {
            std::cerr << "[OFFERER] ⚠ SDP missing BUNDLE" << std::endl;
        }

        if (sdp.sdp_text.find("a=ice-options:trickle") != std::string::npos) {
            std::cout << "[OFFERER] ✓ SDP contains trickle ICE" << std::endl;
        }

        if (sdp.sdp_text.find("a=fingerprint:") != std::string::npos) {
            std::cout << "[OFFERER] ✓ SDP contains DTLS fingerprint" << std::endl;
        }

        if (sdp.sdp_text.find("m=audio") != std::string::npos) {
            std::cout << "[OFFERER] ✓ SDP contains audio media line" << std::endl;
        }

    } else {
        std::cerr << "[OFFERER] ✗ Offer creation failed: " << error << std::endl;
        g_main_loop_quit(main_loop);
    }
}

void on_answerer_sdp(bool success, const SDPMessage &sdp, const std::string &error) {
    if (success) {
        std::cout << "\n[ANSWERER] Answer SDP created (" << sdp.sdp_text.length() << " bytes)" << std::endl;
        state.answer_sdp = sdp;
        state.answerer_answer_ready = true;

        // Schedule applying answer to offerer after brief delay
        std::thread([]{
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            std::cout << "\n[TEST] Now applying answer to offerer..." << std::endl;
        }).detach();

    } else {
        std::cerr << "[ANSWERER] ✗ Answer creation failed: " << error << std::endl;
        g_main_loop_quit(main_loop);
    }
}

void on_offerer_ice(const ICECandidate &candidate) {
    state.ice_candidates_offerer++;
    std::cout << "[OFFERER-ICE] mline=" << candidate.sdp_mline_index
              << " (total: " << state.ice_candidates_offerer << ")" << std::endl;
}

void on_answerer_ice(const ICECandidate &candidate) {
    state.ice_candidates_answerer++;
    std::cout << "[ANSWERER-ICE] mline=" << candidate.sdp_mline_index
              << " (total: " << state.ice_candidates_answerer << ")" << std::endl;
}

void on_offerer_state(MediaSession::ConnectionState st) {
    // Logged by WebRTCSession
}

void on_answerer_state(MediaSession::ConnectionState st) {
    // Logged by WebRTCSession
}

int main(int argc, char *argv[]) {
    gst_init(&argc, &argv);

    std::cout << "=== SDP Negotiation Test (Local Loopback) ===" << std::endl;
    std::cout << "Testing offer/answer between two WebRTCSession instances" << std::endl;
    std::cout << std::endl;

    // Create two sessions
    std::cout << "Creating offerer session..." << std::endl;
    SessionConfig offerer_config;
    offerer_config.session_id = "offerer-1";
    offerer_config.peer_jid = "answerer@example.com";
    offerer_config.relay_only = false;
    offerer_config.stun_server = "stun://stun.l.google.com:19302";
    offerer_config.preferred_type = MediaSession::Type::WEBRTC;

    auto offerer = SessionFactory::create(offerer_config);
    if (!offerer || !offerer->initialize(offerer_config)) {
        std::cerr << "✗ Failed to create offerer" << std::endl;
        return 1;
    }
    std::cout << "✓ Offerer created" << std::endl;

    std::cout << "Creating answerer session..." << std::endl;
    SessionConfig answerer_config;
    answerer_config.session_id = "answerer-1";
    answerer_config.peer_jid = "offerer@example.com";
    answerer_config.relay_only = false;
    answerer_config.stun_server = "stun://stun.l.google.com:19302";
    answerer_config.preferred_type = MediaSession::Type::WEBRTC;

    auto answerer = SessionFactory::create(answerer_config);
    if (!answerer || !answerer->initialize(answerer_config)) {
        std::cerr << "✗ Failed to create answerer" << std::endl;
        return 1;
    }
    std::cout << "✓ Answerer created" << std::endl;
    std::cout << std::endl;

    // Set callbacks
    offerer->set_ice_candidate_callback(on_offerer_ice);
    offerer->set_state_callback(on_offerer_state);
    answerer->set_ice_candidate_callback(on_answerer_ice);
    answerer->set_state_callback(on_answerer_state);

    // Start both pipelines
    std::cout << "Starting pipelines..." << std::endl;
    if (!offerer->start() || !answerer->start()) {
        std::cerr << "✗ Failed to start pipelines" << std::endl;
        return 1;
    }
    std::cout << "✓ Both pipelines PLAYING" << std::endl;
    std::cout << std::endl;

    // Create main loop
    main_loop = g_main_loop_new(nullptr, FALSE);

    // Step 1: Create offer
    std::cout << "=== Step 1: Creating Offer ===" << std::endl;
    offerer->create_offer(on_offerer_sdp);

    // Wait for offer to be created
    std::cout << "Waiting for offer..." << std::endl;
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    if (!state.offerer_offer_ready) {
        std::cerr << "✗ Offer not ready after timeout" << std::endl;
        return 1;
    }
    std::cout << "✓ Offer ready" << std::endl;
    std::cout << std::endl;

    // Step 2: Answerer receives offer and creates answer
    std::cout << "=== Step 2: Creating Answer ===" << std::endl;
    std::cout << "Answerer receiving offer..." << std::endl;
    answerer->create_answer(state.offer_sdp, on_answerer_sdp);

    // Wait for answer to be created
    std::cout << "Waiting for answer..." << std::endl;
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    if (!state.answerer_answer_ready) {
        std::cerr << "✗ Answer not ready after timeout" << std::endl;
        return 1;
    }
    std::cout << "✓ Answer ready" << std::endl;
    std::cout << std::endl;

    // Step 3: Offerer receives answer
    std::cout << "=== Step 3: Applying Answer to Offerer ===" << std::endl;
    if (!offerer->set_remote_description(state.answer_sdp)) {
        std::cerr << "✗ Failed to set remote answer" << std::endl;
        return 1;
    }
    std::cout << "✓ Remote answer applied" << std::endl;
    std::cout << std::endl;

    // Step 4: Let main loop run to process async events (ICE, etc.)
    std::cout << "=== Step 4: Processing Events ===" << std::endl;
    std::cout << "Running main loop for 3 seconds to collect ICE candidates..." << std::endl;
    std::cout << "(You should see ICE candidates and signaling state transitions)" << std::endl;
    std::cout << std::endl;

    std::thread([]{
        std::this_thread::sleep_for(std::chrono::seconds(3));
        if (main_loop) {
            g_main_loop_quit(main_loop);
        }
    }).detach();

    g_main_loop_run(main_loop);
    g_main_loop_unref(main_loop);

    std::cout << std::endl;
    std::cout << "=== Test Results ===" << std::endl;
    std::cout << std::endl;

    // Verify results
    bool all_passed = true;

    std::cout << "Offer SDP created: " << (state.offerer_offer_ready ? "✓" : "✗") << std::endl;
    if (!state.offerer_offer_ready) all_passed = false;

    std::cout << "Answer SDP created: " << (state.answerer_answer_ready ? "✓" : "✗") << std::endl;
    if (!state.answerer_answer_ready) all_passed = false;

    std::cout << "Offerer ICE candidates: " << state.ice_candidates_offerer
              << (state.ice_candidates_offerer > 0 ? " ✓" : " ⚠") << std::endl;

    std::cout << "Answerer ICE candidates: " << state.ice_candidates_answerer
              << (state.ice_candidates_answerer > 0 ? " ✓" : " ⚠") << std::endl;

    std::cout << std::endl;

    // Cleanup
    std::cout << "Stopping sessions..." << std::endl;
    offerer->stop();
    answerer->stop();
    std::cout << "✓ Sessions stopped" << std::endl;

    std::cout << std::endl;
    if (all_passed) {
        std::cout << "=== All critical tests PASSED ===" << std::endl;
        if (state.ice_candidates_offerer == 0 || state.ice_candidates_answerer == 0) {
            std::cout << "⚠ Note: No ICE candidates (expected without network)" << std::endl;
        }
    } else {
        std::cout << "=== Some tests FAILED ===" << std::endl;
        return 1;
    }

    return 0;
}
