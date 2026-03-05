/**
 * WebRTC Caller Test - Creates offer, sends audio from real microphone
 *
 * Purpose: Test WebRTC audio sending with real microphone, bypassing gRPC/Jingle complexity
 * Usage: ./test_webrtc_caller < answerer_output > answerer_input
 * Or: mkfifo pipe1 pipe2; ./test_webrtc_answerer < pipe1 > pipe2 & ./test_webrtc_caller < pipe2 > pipe1
 */

#include "media_session.h"
#include "logger.h"
#include <gst/gst.h>
#include <glib.h>
#include <iostream>
#include <string>
#include <vector>
#include <atomic>
#include <thread>
#include <chrono>

using namespace drunk_call;

// Global state for main loop control
static GMainLoop *g_main_loop = nullptr;
static std::unique_ptr<MediaSession> g_session = nullptr;
static std::atomic<bool> g_offer_created{false};
static std::atomic<bool> g_answer_received{false};
static std::atomic<bool> g_ice_gathering_complete{false};
static std::vector<std::string> g_ice_candidates;

// Protocol helpers
void print_sdp(const std::string &type, const std::string &sdp) {
    std::cout << type << std::endl;
    std::cout << sdp;
    if (sdp.back() != '\n') std::cout << std::endl;
    std::cout << "END_" << type << std::endl;
    std::cout.flush();
}

void print_ice_candidate(const ICECandidate &candidate) {
    std::cout << "ICE " << candidate.sdp_mline_index << " " << candidate.candidate << std::endl;
    std::cout.flush();
}

std::string read_until(const std::string &delimiter) {
    std::string result;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line == delimiter) {
            break;
        }
        result += line + "\n";
    }
    return result;
}

// Stats monitoring using GLib timer (runs in main loop, not separate thread!)
static int stats_counter = 0;
static gboolean stats_timer_callback(gpointer user_data) {
    if (!g_session) {
        fprintf(stderr, "[STATS][%d] Session is null, skipping\n", stats_counter);
        fflush(stderr);
        return G_SOURCE_CONTINUE;
    }

    auto stats = g_session->get_stats();

    // Print to stderr (unbuffered)
    fprintf(stderr, "[STATS][%d] bytes_sent=%ld, bytes_recv=%ld, bandwidth=%ld kbps, ice=%s\n",
            stats_counter, stats.bytes_sent, stats.bytes_received, stats.bandwidth_kbps,
            stats.ice_connection_state.c_str());
    fflush(stderr);

    // Also log via spdlog
    LOG_INFO("Stats[{}]: bytes_sent={}, bandwidth={} kbps, ice_state={}",
             stats_counter, stats.bytes_sent, stats.bandwidth_kbps, stats.ice_connection_state);

    if (stats.bandwidth_kbps > 0) {
        fprintf(stderr, "[STATS] ✅ Audio is flowing! (bandwidth > 0)\n");
        fflush(stderr);
        LOG_INFO("✅ Audio is flowing! (bandwidth > 0)");
    }

    stats_counter++;

    if (stats_counter >= 15) {  // Stop after 15 samples
        fprintf(stderr, "[STATS] Monitoring complete, stopping...\n");
        fflush(stderr);
        LOG_INFO("Stats monitoring complete, stopping...");
        g_main_loop_quit(g_main_loop);
        return G_SOURCE_REMOVE;
    }

    return G_SOURCE_CONTINUE;  // Keep timer running
}

// Stdin reader thread (reads answer and remote ICE candidates)
void stdin_reader_thread() {
    LOG_INFO("Stdin reader starting, waiting for ANSWER...");

    // Wait for answer
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line == "ANSWER") {
            LOG_INFO("Received ANSWER marker");
            std::string answer_sdp = read_until("END_ANSWER");
            LOG_INFO("Answer SDP received ({} bytes)", answer_sdp.size());

            // Set remote description
            SDPMessage answer{SDPMessage::Type::ANSWER, answer_sdp};
            g_session->set_remote_description(answer);
            g_answer_received = true;
            LOG_INFO("Remote description set");
            break;
        }
    }

    // Read remote ICE candidates
    LOG_INFO("Waiting for remote ICE candidates...");
    while (std::getline(std::cin, line)) {
        if (line.substr(0, 4) == "ICE ") {
            // Parse: "ICE <mline_index> <candidate>"
            size_t first_space = line.find(' ');
            size_t second_space = line.find(' ', first_space + 1);

            if (second_space != std::string::npos) {
                int mline_index = std::stoi(line.substr(first_space + 1, second_space - first_space - 1));
                std::string candidate = line.substr(second_space + 1);

                LOG_INFO("Adding remote ICE candidate: mline={} candidate={}", mline_index, candidate);

                ICECandidate ice{candidate, mline_index};
                g_session->add_remote_ice_candidate(ice);
            }
        } else if (line == "ICE_DONE") {
            LOG_INFO("Remote ICE gathering complete");
            break;
        }
    }

    LOG_INFO("Stdin reader complete");
}

int main(int argc, char *argv[]) {
    // Initialize GStreamer
    gst_init(&argc, &argv);

    // Initialize logger
    Logger::init("test_caller.log", "DEBUG");
    LOG_INFO("=== WebRTC Caller Test Starting ===");
    LOG_INFO("This test creates an offer and sends audio from the default microphone");

    // Create main loop
    g_main_loop = g_main_loop_new(nullptr, FALSE);

    try {
        // Configure session for outgoing call with real microphone
        SessionConfig config;
        config.session_id = "test-caller-session";
        config.peer_jid = "test-answerer";
        config.relay_only = false;
        config.stun_server = "";        // No STUN server (localhost only)
        config.turn_servers = {};       // No TURN servers
        config.microphone_device = "";  // Empty = use default microphone (autoaudiosrc)
        config.speakers_device = "";    // Empty = use default speakers
        config.echo_cancel = false;     // Disable DSP for testing
        config.noise_suppression = false;
        config.gain_control = false;
        config.preferred_type = MediaSession::Type::WEBRTC;

        LOG_INFO("Creating WebRTC session (outgoing mode)...");
        g_session = SessionFactory::create(config);

        // Set ICE candidate callback
        g_session->set_ice_candidate_callback([](const ICECandidate &candidate) {
            LOG_INFO("Local ICE candidate: mline={} candidate={}",
                     candidate.sdp_mline_index, candidate.candidate);
            g_ice_candidates.push_back(candidate.candidate);
            print_ice_candidate(candidate);
        });

        // Set connection state callback
        g_session->set_state_callback([](MediaSession::ConnectionState state) {
            LOG_INFO("Connection state changed: {}", static_cast<int>(state));

            if (state == MediaSession::ConnectionState::CONNECTED) {
                LOG_INFO("✅ ICE CONNECTED! Starting stats monitor...");
                g_ice_gathering_complete = true;

                // Print ICE_DONE marker
                std::cout << "ICE_DONE" << std::endl;
                std::cout.flush();

                // Start stats monitoring using GLib timer (every 2 seconds)
                fprintf(stderr, "[STATS] Starting stats monitoring timer...\n");
                fflush(stderr);
                g_timeout_add_seconds(2, stats_timer_callback, nullptr);
            } else if (state == MediaSession::ConnectionState::FAILED) {
                LOG_ERROR("❌ Connection FAILED");
                if (g_main_loop) {
                    g_main_loop_quit(g_main_loop);
                }
            }
        });

        // Initialize and start session
        LOG_INFO("Initializing session...");
        g_session->initialize(config);

        LOG_INFO("Starting session (pipeline → PLAYING)...");
        g_session->start();

        // Create offer
        LOG_INFO("Creating SDP offer...");
        g_session->create_offer([](bool success, const SDPMessage &offer, const std::string &error) {
            if (!success) {
                LOG_ERROR("Failed to create offer: {}", error);
                if (g_main_loop) {
                    g_main_loop_quit(g_main_loop);
                }
                return;
            }

            LOG_INFO("✅ Offer created ({} bytes)", offer.sdp_text.size());
            LOG_DEBUG("Offer SDP:\n{}", offer.sdp_text);

            // Check for a=sendrecv
            if (offer.sdp_text.find("a=sendrecv") != std::string::npos) {
                LOG_INFO("✅ Offer contains a=sendrecv (audio sending enabled)");
            } else if (offer.sdp_text.find("a=recvonly") != std::string::npos) {
                LOG_ERROR("❌ Offer contains a=recvonly (audio sending DISABLED)");
            }

            // Print offer to stdout
            print_sdp("OFFER", offer.sdp_text);

            g_offer_created = true;

            // Start stdin reader thread to get answer
            std::thread(stdin_reader_thread).detach();
        });

        // Run main loop
        LOG_INFO("Entering main loop...");
        g_main_loop_run(g_main_loop);

        LOG_INFO("Main loop exited, cleaning up...");

    } catch (const std::exception &e) {
        LOG_ERROR("Exception: {}", e.what());
        if (g_main_loop) {
            g_main_loop_unref(g_main_loop);
        }
        return 1;
    }

    // Cleanup
    if (g_session) {
        LOG_INFO("Stopping session...");
        g_session->stop();
        g_session.reset();
    }

    if (g_main_loop) {
        g_main_loop_unref(g_main_loop);
    }

    LOG_INFO("=== WebRTC Caller Test Complete ===");

    // Print summary
    std::cout << "\n=== TEST SUMMARY ===" << std::endl;
    std::cout << "Offer created: " << (g_offer_created ? "YES" : "NO") << std::endl;
    std::cout << "Answer received: " << (g_answer_received ? "YES" : "NO") << std::endl;
    std::cout << "ICE connected: " << (g_ice_gathering_complete ? "YES" : "NO") << std::endl;

    if (g_session) {
        auto stats = g_session->get_stats();
        std::cout << "Final bytes_sent: " << stats.bytes_sent << std::endl;
        std::cout << "Final bandwidth: " << stats.bandwidth_kbps << " kbps" << std::endl;
        std::cout << "SUCCESS: " << (stats.bandwidth_kbps > 0 ? "YES ✅" : "NO ❌") << std::endl;
    }

    return 0;
}
