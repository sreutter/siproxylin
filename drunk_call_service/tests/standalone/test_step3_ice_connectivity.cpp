/**
 * ICE Connectivity Test - Local Loopback with Candidate Exchange
 *
 * Purpose: Test full ICE candidate gathering and connectivity between two WebRTCSession instances
 * Tests: ICE candidate exchange, gathering states, connection states, connectivity establishment
 *
 * Reference: docs/CALLS/3-ICE-PLAN.md
 * Build: make test_ice
 * Run: ./test_ice
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
#include <vector>
#include <mutex>
#include <atomic>

using namespace drunk_call;

static GMainLoop *main_loop = nullptr;

// State tracking for both sessions
struct TestState {
    // SDP exchange
    bool offerer_offer_ready = false;
    bool answerer_answer_ready = false;
    SDPMessage offer_sdp;
    SDPMessage answer_sdp;

    // ICE candidates
    std::vector<ICECandidate> offerer_candidates;
    std::vector<ICECandidate> answerer_candidates;
    std::mutex offerer_candidates_mutex;
    std::mutex answerer_candidates_mutex;

    // ICE connection states
    MediaSession::ConnectionState offerer_ice_state = MediaSession::ConnectionState::NEW;
    MediaSession::ConnectionState answerer_ice_state = MediaSession::ConnectionState::NEW;
    std::mutex offerer_state_mutex;
    std::mutex answerer_state_mutex;

    // Timing
    std::chrono::steady_clock::time_point start_time;
    std::chrono::steady_clock::time_point sdp_exchange_time;
    std::chrono::steady_clock::time_point first_candidate_time;
    std::chrono::steady_clock::time_point connected_time;

} state;

// Helper to get elapsed time in milliseconds
int64_t elapsed_ms(std::chrono::steady_clock::time_point from) {
    auto now = std::chrono::steady_clock::now();
    return std::chrono::duration_cast<std::chrono::milliseconds>(now - from).count();
}

// Callbacks for offerer (session 1)
void on_offerer_sdp(bool success, const SDPMessage &sdp, const std::string &error) {
    if (success) {
        std::cout << "\n[OFFERER] Offer SDP created (" << sdp.sdp_text.length() << " bytes)" << std::endl;
        std::cout << "[OFFERER] Time elapsed: " << elapsed_ms(state.start_time) << " ms" << std::endl;
        state.offer_sdp = sdp;
        state.offerer_offer_ready = true;

        // Validate SDP content
        if (sdp.sdp_text.find("a=group:BUNDLE") != std::string::npos) {
            std::cout << "[OFFERER] ✓ SDP contains BUNDLE" << std::endl;
        }
        if (sdp.sdp_text.find("a=ice-options:trickle") != std::string::npos) {
            std::cout << "[OFFERER] ✓ SDP contains trickle ICE" << std::endl;
        }
        if (sdp.sdp_text.find("a=fingerprint:") != std::string::npos) {
            std::cout << "[OFFERER] ✓ SDP contains DTLS fingerprint" << std::endl;
        }
    } else {
        std::cerr << "[OFFERER] ✗ Offer creation failed: " << error << std::endl;
        g_main_loop_quit(main_loop);
    }
}

void on_answerer_sdp(bool success, const SDPMessage &sdp, const std::string &error) {
    if (success) {
        std::cout << "\n[ANSWERER] Answer SDP created (" << sdp.sdp_text.length() << " bytes)" << std::endl;
        std::cout << "[ANSWERER] Time elapsed: " << elapsed_ms(state.start_time) << " ms" << std::endl;
        state.answer_sdp = sdp;
        state.answerer_answer_ready = true;
        state.sdp_exchange_time = std::chrono::steady_clock::now();
    } else {
        std::cerr << "[ANSWERER] ✗ Answer creation failed: " << error << std::endl;
        g_main_loop_quit(main_loop);
    }
}

void on_offerer_ice(const ICECandidate &candidate) {
    std::lock_guard<std::mutex> lock(state.offerer_candidates_mutex);
    state.offerer_candidates.push_back(candidate);

    if (state.offerer_candidates.size() == 1) {
        state.first_candidate_time = std::chrono::steady_clock::now();
    }

    // Log candidate type
    const char *typ = "unknown";
    if (candidate.candidate.find("typ host") != std::string::npos) typ = "host";
    else if (candidate.candidate.find("typ srflx") != std::string::npos) typ = "srflx";
    else if (candidate.candidate.find("typ relay") != std::string::npos) typ = "relay";

    std::cout << "[OFFERER-ICE] Candidate #" << state.offerer_candidates.size()
              << " (typ " << typ << ") mline=" << candidate.sdp_mline_index << std::endl;
}

void on_answerer_ice(const ICECandidate &candidate) {
    std::lock_guard<std::mutex> lock(state.answerer_candidates_mutex);
    state.answerer_candidates.push_back(candidate);

    // Log candidate type
    const char *typ = "unknown";
    if (candidate.candidate.find("typ host") != std::string::npos) typ = "host";
    else if (candidate.candidate.find("typ srflx") != std::string::npos) typ = "srflx";
    else if (candidate.candidate.find("typ relay") != std::string::npos) typ = "relay";

    std::cout << "[ANSWERER-ICE] Candidate #" << state.answerer_candidates.size()
              << " (typ " << typ << ") mline=" << candidate.sdp_mline_index << std::endl;
}

void on_offerer_state(MediaSession::ConnectionState st) {
    std::lock_guard<std::mutex> lock(state.offerer_state_mutex);
    state.offerer_ice_state = st;

    const char *state_str = "UNKNOWN";
    switch (st) {
        case MediaSession::ConnectionState::NEW: state_str = "NEW"; break;
        case MediaSession::ConnectionState::CHECKING: state_str = "CHECKING"; break;
        case MediaSession::ConnectionState::CONNECTED:
            state_str = "CONNECTED";
            if (state.connected_time.time_since_epoch().count() == 0) {
                state.connected_time = std::chrono::steady_clock::now();
                std::cout << "[OFFERER] ⭐ First peer CONNECTED after "
                          << elapsed_ms(state.start_time) << " ms" << std::endl;
            }
            break;
        case MediaSession::ConnectionState::COMPLETED: state_str = "COMPLETED"; break;
        case MediaSession::ConnectionState::FAILED: state_str = "FAILED"; break;
        case MediaSession::ConnectionState::DISCONNECTED: state_str = "DISCONNECTED"; break;
        case MediaSession::ConnectionState::CLOSED: state_str = "CLOSED"; break;
    }

    std::cout << "[OFFERER-STATE] ICE connection state → " << state_str << std::endl;
}

void on_answerer_state(MediaSession::ConnectionState st) {
    std::lock_guard<std::mutex> lock(state.answerer_state_mutex);
    state.answerer_ice_state = st;

    const char *state_str = "UNKNOWN";
    switch (st) {
        case MediaSession::ConnectionState::NEW: state_str = "NEW"; break;
        case MediaSession::ConnectionState::CHECKING: state_str = "CHECKING"; break;
        case MediaSession::ConnectionState::CONNECTED:
            state_str = "CONNECTED";
            if (state.connected_time.time_since_epoch().count() == 0) {
                state.connected_time = std::chrono::steady_clock::now();
                std::cout << "[ANSWERER] ⭐ First peer CONNECTED after "
                          << elapsed_ms(state.start_time) << " ms" << std::endl;
            }
            break;
        case MediaSession::ConnectionState::COMPLETED: state_str = "COMPLETED"; break;
        case MediaSession::ConnectionState::FAILED: state_str = "FAILED"; break;
        case MediaSession::ConnectionState::DISCONNECTED: state_str = "DISCONNECTED"; break;
        case MediaSession::ConnectionState::CLOSED: state_str = "CLOSED"; break;
    }

    std::cout << "[ANSWERER-STATE] ICE connection state → " << state_str << std::endl;
}

int main(int argc, char *argv[]) {
    gst_init(&argc, &argv);

    state.start_time = std::chrono::steady_clock::now();

    // Parse command-line arguments for proxy
    std::string proxy_url;
    std::string proxy_host;
    int proxy_port = 0;
    std::string proxy_type;
    std::string proxy_username;
    std::string proxy_password;

    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--proxy" && i + 1 < argc) {
            proxy_url = argv[++i];
            // Parse proxy URL: protocol://[user:pass@]host:port
            size_t proto_end = proxy_url.find("://");
            if (proto_end != std::string::npos) {
                std::string proto = proxy_url.substr(0, proto_end);
                if (proto == "socks5") {
                    proxy_type = "SOCKS5";
                } else if (proto == "http") {
                    proxy_type = "HTTP";
                }

                std::string rest = proxy_url.substr(proto_end + 3);
                size_t at_pos = rest.find('@');
                if (at_pos != std::string::npos) {
                    // Has credentials
                    std::string creds = rest.substr(0, at_pos);
                    size_t colon = creds.find(':');
                    if (colon != std::string::npos) {
                        proxy_username = creds.substr(0, colon);
                        proxy_password = creds.substr(colon + 1);
                    } else {
                        proxy_username = creds;
                    }
                    rest = rest.substr(at_pos + 1);
                }

                // Parse host:port
                size_t colon = rest.find(':');
                if (colon != std::string::npos) {
                    proxy_host = rest.substr(0, colon);
                    proxy_port = std::stoi(rest.substr(colon + 1));
                } else {
                    proxy_host = rest;
                    proxy_port = (proxy_type == "SOCKS5") ? 1080 : 3128;
                }
            }
        }
    }

    std::cout << "=== ICE Connectivity Test (Local Loopback) ===" << std::endl;
    std::cout << "Testing ICE candidate exchange and connectivity between two WebRTCSession instances" << std::endl;
    if (!proxy_host.empty()) {
        std::cout << "Proxy: " << proxy_type << " " << proxy_host << ":" << proxy_port << std::endl;
    }
    std::cout << std::endl;

    // Create two sessions
    std::cout << "Creating offerer session..." << std::endl;
    SessionConfig offerer_config;
    offerer_config.session_id = "offerer-ice";
    offerer_config.peer_jid = "answerer@example.com";
    offerer_config.relay_only = false;
    offerer_config.stun_server = "stun://turn.jami.net:3478";
    offerer_config.proxy_host = proxy_host;
    offerer_config.proxy_port = proxy_port;
    offerer_config.proxy_type = proxy_type;
    offerer_config.proxy_username = proxy_username;
    offerer_config.proxy_password = proxy_password;
    offerer_config.preferred_type = MediaSession::Type::WEBRTC;

    auto offerer = SessionFactory::create(offerer_config);
    if (!offerer || !offerer->initialize(offerer_config)) {
        std::cerr << "✗ Failed to create offerer" << std::endl;
        return 1;
    }
    std::cout << "✓ Offerer created" << std::endl;

    std::cout << "Creating answerer session..." << std::endl;
    SessionConfig answerer_config;
    answerer_config.session_id = "answerer-ice";
    answerer_config.peer_jid = "offerer@example.com";
    answerer_config.relay_only = false;
    answerer_config.stun_server = "stun://turn.jami.net:3478";
    answerer_config.proxy_host = proxy_host;
    answerer_config.proxy_port = proxy_port;
    answerer_config.proxy_type = proxy_type;
    answerer_config.proxy_username = proxy_username;
    answerer_config.proxy_password = proxy_password;
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

    // Wait for offer
    std::cout << "Waiting for offer..." << std::endl;
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    if (!state.offerer_offer_ready) {
        std::cerr << "✗ Offer not ready after timeout" << std::endl;
        return 1;
    }
    std::cout << "✓ Offer ready" << std::endl;
    std::cout << std::endl;

    // Step 2: Create answer
    std::cout << "=== Step 2: Creating Answer ===" << std::endl;
    std::cout << "Answerer receiving offer..." << std::endl;
    answerer->create_answer(state.offer_sdp, on_answerer_sdp);

    // Wait for answer
    std::cout << "Waiting for answer..." << std::endl;
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    if (!state.answerer_answer_ready) {
        std::cerr << "✗ Answer not ready after timeout" << std::endl;
        return 1;
    }
    std::cout << "✓ Answer ready" << std::endl;
    std::cout << std::endl;

    // Step 3: Apply answer to offerer
    std::cout << "=== Step 3: Applying Answer to Offerer ===" << std::endl;
    if (!offerer->set_remote_description(state.answer_sdp)) {
        std::cerr << "✗ Failed to set remote answer" << std::endl;
        return 1;
    }
    std::cout << "✓ Remote answer applied" << std::endl;
    std::cout << std::endl;

    // Step 4: Exchange ICE candidates (trickle ICE simulation)
    std::cout << "=== Step 4: Exchanging ICE Candidates ===" << std::endl;
    std::cout << "Collecting ICE candidates for 3 seconds..." << std::endl;
    std::cout << "(Watch for ICE gathering and connection state transitions)" << std::endl;
    std::cout << std::endl;

    // Background thread to exchange candidates as they arrive
    std::atomic<bool> keep_exchanging{true};
    std::thread candidate_exchanger([&]() {
        size_t offerer_last_sent = 0;
        size_t answerer_last_sent = 0;

        while (keep_exchanging) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));

            // Send offerer's new candidates to answerer
            {
                std::lock_guard<std::mutex> lock(state.offerer_candidates_mutex);
                while (offerer_last_sent < state.offerer_candidates.size()) {
                    const auto &cand = state.offerer_candidates[offerer_last_sent];
                    answerer->add_remote_ice_candidate(cand);
                    offerer_last_sent++;
                }
            }

            // Send answerer's new candidates to offerer
            {
                std::lock_guard<std::mutex> lock(state.answerer_candidates_mutex);
                while (answerer_last_sent < state.answerer_candidates.size()) {
                    const auto &cand = state.answerer_candidates[answerer_last_sent];
                    offerer->add_remote_ice_candidate(cand);
                    answerer_last_sent++;
                }
            }
        }
    });

    // Run main loop for candidate gathering and connectivity
    std::thread timeout_thread([]{
        std::this_thread::sleep_for(std::chrono::seconds(5));
        if (main_loop) {
            g_main_loop_quit(main_loop);
        }
    });
    timeout_thread.detach();

    g_main_loop_run(main_loop);
    g_main_loop_unref(main_loop);

    // Stop candidate exchanger
    keep_exchanging = false;
    candidate_exchanger.join();

    std::cout << std::endl;
    std::cout << "=== Test Results ===" << std::endl;
    std::cout << std::endl;

    // Verify results
    bool all_passed = true;

    std::cout << "SDP Negotiation:" << std::endl;
    std::cout << "  Offer created: " << (state.offerer_offer_ready ? "✓" : "✗") << std::endl;
    if (!state.offerer_offer_ready) all_passed = false;

    std::cout << "  Answer created: " << (state.answerer_answer_ready ? "✓" : "✗") << std::endl;
    if (!state.answerer_answer_ready) all_passed = false;

    std::cout << std::endl;
    std::cout << "ICE Candidates:" << std::endl;
    std::cout << "  Offerer candidates: " << state.offerer_candidates.size()
              << (state.offerer_candidates.size() > 0 ? " ✓" : " ✗") << std::endl;
    if (state.offerer_candidates.size() == 0) all_passed = false;

    std::cout << "  Answerer candidates: " << state.answerer_candidates.size()
              << (state.answerer_candidates.size() > 0 ? " ✓" : " ✗") << std::endl;
    if (state.answerer_candidates.size() == 0) all_passed = false;

    std::cout << std::endl;
    std::cout << "ICE Connection State:" << std::endl;

    auto state_to_string = [](MediaSession::ConnectionState s) {
        switch (s) {
            case MediaSession::ConnectionState::NEW: return "NEW";
            case MediaSession::ConnectionState::CHECKING: return "CHECKING";
            case MediaSession::ConnectionState::CONNECTED: return "CONNECTED";
            case MediaSession::ConnectionState::COMPLETED: return "COMPLETED";
            case MediaSession::ConnectionState::FAILED: return "FAILED";
            case MediaSession::ConnectionState::DISCONNECTED: return "DISCONNECTED";
            case MediaSession::ConnectionState::CLOSED: return "CLOSED";
            default: return "UNKNOWN";
        }
    };

    std::cout << "  Offerer state: " << state_to_string(state.offerer_ice_state);
    if (state.offerer_ice_state == MediaSession::ConnectionState::CONNECTED ||
        state.offerer_ice_state == MediaSession::ConnectionState::COMPLETED) {
        std::cout << " ✓" << std::endl;
    } else {
        std::cout << " ⚠ (expected CONNECTED or COMPLETED)" << std::endl;
    }

    std::cout << "  Answerer state: " << state_to_string(state.answerer_ice_state);
    if (state.answerer_ice_state == MediaSession::ConnectionState::CONNECTED ||
        state.answerer_ice_state == MediaSession::ConnectionState::COMPLETED) {
        std::cout << " ✓" << std::endl;
    } else {
        std::cout << " ⚠ (expected CONNECTED or COMPLETED)" << std::endl;
    }

    std::cout << std::endl;
    std::cout << "Timing:" << std::endl;
    if (state.first_candidate_time.time_since_epoch().count() > 0) {
        std::cout << "  First candidate after: "
                  << elapsed_ms(state.start_time) << " ms" << std::endl;
    }
    if (state.connected_time.time_since_epoch().count() > 0) {
        std::cout << "  First CONNECTED after: "
                  << elapsed_ms(state.start_time) << " ms" << std::endl;
    }

    std::cout << std::endl;

    // Cleanup
    std::cout << "Stopping sessions..." << std::endl;
    offerer->stop();
    answerer->stop();
    std::cout << "✓ Sessions stopped" << std::endl;

    std::cout << std::endl;
    if (all_passed &&
        (state.offerer_ice_state == MediaSession::ConnectionState::CONNECTED ||
         state.offerer_ice_state == MediaSession::ConnectionState::COMPLETED) &&
        (state.answerer_ice_state == MediaSession::ConnectionState::CONNECTED ||
         state.answerer_ice_state == MediaSession::ConnectionState::COMPLETED)) {
        std::cout << "=== ✓ ALL TESTS PASSED ===" << std::endl;
        std::cout << "ICE connectivity successfully established!" << std::endl;
        return 0;
    } else {
        std::cout << "=== ⚠ SOME TESTS INCOMPLETE ===" << std::endl;
        if (state.offerer_candidates.size() > 0 && state.answerer_candidates.size() > 0) {
            std::cout << "Note: ICE candidates were gathered but connection may need more time" << std::endl;
            std::cout << "This can happen in restrictive network environments" << std::endl;
        }
        return 1;
    }
}
