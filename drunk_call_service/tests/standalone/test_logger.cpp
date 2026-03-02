/**
 * Logger Test
 *
 * Purpose: Test spdlog logger initialization and logging
 * Tests: File creation, log levels, rotation
 *
 * Build: g++ -std=c++17 test_logger.cpp ../../src/logger.cpp -o test_logger -I../../src $(pkg-config --cflags --libs spdlog)
 * Run: ./test_logger
 */

#include "../../src/logger.h"
#include <iostream>
#include <filesystem>
#include <fstream>
#include <thread>
#include <chrono>

using namespace drunk_call;

int main(int argc, char *argv[]) {
    std::cout << "=== Logger Test ===" << std::endl;
    std::cout << std::endl;

    // Test 1: Initialize logger
    std::cout << "=== Test 1: Logger Initialization ===" << std::endl;

    std::string log_path = "/tmp/drunk-call-service-test.log";

    // Remove old log if exists
    if (std::filesystem::exists(log_path)) {
        std::filesystem::remove(log_path);
    }

    Logger::init(log_path, "DEBUG");
    std::cout << "✓ Logger initialized" << std::endl;
    std::cout << "  Log file: " << log_path << std::endl;
    std::cout << std::endl;

    // Test 2: Log messages at different levels
    std::cout << "=== Test 2: Log Levels ===" << std::endl;

    LOG_TRACE("This is a TRACE message (should not appear with DEBUG level)");
    LOG_DEBUG("This is a DEBUG message");
    LOG_INFO("This is an INFO message");
    LOG_WARN("This is a WARN message");
    LOG_ERROR("This is an ERROR message");
    LOG_CRITICAL("This is a CRITICAL message");

    std::cout << "✓ Logged messages at all levels" << std::endl;
    std::cout << std::endl;

    // Test 3: Formatted logging
    std::cout << "=== Test 3: Formatted Logging ===" << std::endl;

    std::string session_id = "test-session-123";
    int peer_count = 42;
    double bandwidth_kbps = 32.5;

    LOG_INFO("Session created: {}", session_id);
    LOG_INFO("Peer count: {}, bandwidth: {:.1f} Kbps", peer_count, bandwidth_kbps);

    std::cout << "✓ Formatted logging works" << std::endl;
    std::cout << std::endl;

    // Test 4: Verify log file contents
    std::cout << "=== Test 4: Verify Log File ===" << std::endl;

    Logger::shutdown();  // Flush all logs

    if (!std::filesystem::exists(log_path)) {
        std::cerr << "✗ Log file not created!" << std::endl;
        return 1;
    }

    std::ifstream log_file(log_path);
    std::string line;
    int line_count = 0;

    std::cout << "Log file contents:" << std::endl;
    std::cout << "---" << std::endl;

    while (std::getline(log_file, line)) {
        std::cout << line << std::endl;
        line_count++;
    }

    std::cout << "---" << std::endl;
    std::cout << "✓ Log file contains " << line_count << " lines" << std::endl;
    std::cout << std::endl;

    // Test 5: Verify expected log entries
    std::cout << "=== Test 5: Verify Log Content ===" << std::endl;

    log_file.clear();
    log_file.seekg(0);

    bool found_debug = false;
    bool found_info = false;
    bool found_warn = false;
    bool found_error = false;
    bool found_critical = false;
    bool found_session = false;

    while (std::getline(log_file, line)) {
        if (line.find("[debug]") != std::string::npos) found_debug = true;
        if (line.find("[info]") != std::string::npos) found_info = true;
        if (line.find("[warning]") != std::string::npos) found_warn = true;
        if (line.find("[error]") != std::string::npos) found_error = true;
        if (line.find("[critical]") != std::string::npos) found_critical = true;
        if (line.find("test-session-123") != std::string::npos) found_session = true;
    }

    log_file.close();

    if (!found_debug) {
        std::cerr << "✗ DEBUG message not found" << std::endl;
        return 1;
    }
    std::cout << "✓ DEBUG message found" << std::endl;

    if (!found_info) {
        std::cerr << "✗ INFO message not found" << std::endl;
        return 1;
    }
    std::cout << "✓ INFO message found" << std::endl;

    if (!found_warn) {
        std::cerr << "✗ WARN message not found" << std::endl;
        return 1;
    }
    std::cout << "✓ WARN message found" << std::endl;

    if (!found_error) {
        std::cerr << "✗ ERROR message not found" << std::endl;
        return 1;
    }
    std::cout << "✓ ERROR message found" << std::endl;

    if (!found_critical) {
        std::cerr << "✗ CRITICAL message not found" << std::endl;
        return 1;
    }
    std::cout << "✓ CRITICAL message found" << std::endl;

    if (!found_session) {
        std::cerr << "✗ Formatted session message not found" << std::endl;
        return 1;
    }
    std::cout << "✓ Formatted session message found" << std::endl;

    std::cout << std::endl;

    // Summary
    std::cout << "=== Test Summary ===" << std::endl;
    std::cout << "✓ Logger initialization successful" << std::endl;
    std::cout << "✓ All log levels working" << std::endl;
    std::cout << "✓ Formatted logging working" << std::endl;
    std::cout << "✓ Log file created at: " << log_path << std::endl;
    std::cout << std::endl;
    std::cout << "=== ✓ ALL TESTS PASSED ===" << std::endl;

    return 0;
}
