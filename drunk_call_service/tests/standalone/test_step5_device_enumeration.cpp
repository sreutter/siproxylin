/**
 * Device Enumeration Test
 *
 * Purpose: Test cross-platform audio device enumeration
 * Tests: List input/output devices, identify defaults
 *
 * Build: make test_devices
 * Run: ./test_devices
 */

#include "../../src/media_session.h"
#include "../../src/device_enumerator.cpp"

#include <gst/gst.h>
#include <iostream>

using namespace drunk_call;

int main(int argc, char *argv[]) {
    gst_init(&argc, &argv);

    std::cout << "=== Audio Device Enumeration Test ===" << std::endl;
    std::cout << "Platform: " << OS_FAMILY << std::endl;
    std::cout << std::endl;

    // Test 1: List input devices
    std::cout << "=== Test 1: List Audio Input Devices (Microphones) ===" << std::endl;
    auto inputs = DeviceEnumerator::list_audio_inputs();

    if (inputs.empty()) {
        std::cerr << "✗ No input devices found!" << std::endl;
        return 1;
    }

    std::cout << "Found " << inputs.size() << " input device(s):" << std::endl;
    for (size_t i = 0; i < inputs.size(); i++) {
        const auto &dev = inputs[i];
        std::cout << "  [" << (i+1) << "] " << (dev.is_default ? "✓ DEFAULT" : "         ")
                  << " " << dev.name << std::endl;
        std::cout << "      ID: " << dev.id << std::endl;
        if (!dev.description.empty()) {
            std::cout << "      Class: " << dev.description << std::endl;
        }
    }
    std::cout << std::endl;

    // Test 2: List output devices
    std::cout << "=== Test 2: List Audio Output Devices (Speakers) ===" << std::endl;
    auto outputs = DeviceEnumerator::list_audio_outputs();

    if (outputs.empty()) {
        std::cerr << "✗ No output devices found!" << std::endl;
        return 1;
    }

    std::cout << "Found " << outputs.size() << " output device(s):" << std::endl;
    for (size_t i = 0; i < outputs.size(); i++) {
        const auto &dev = outputs[i];
        std::cout << "  [" << (i+1) << "] " << (dev.is_default ? "✓ DEFAULT" : "         ")
                  << " " << dev.name << std::endl;
        std::cout << "      ID: " << dev.id << std::endl;
        if (!dev.description.empty()) {
            std::cout << "      Class: " << dev.description << std::endl;
        }
    }
    std::cout << std::endl;

    // Test 3: Get default devices
    std::cout << "=== Test 3: Get Default Devices ===" << std::endl;

    auto default_input = DeviceEnumerator::get_default_input();
    if (!default_input.id.empty()) {
        std::cout << "✓ Default Input: " << default_input.name << std::endl;
        std::cout << "  ID: " << default_input.id << std::endl;
    } else {
        std::cerr << "✗ No default input device found" << std::endl;
        return 1;
    }

    auto default_output = DeviceEnumerator::get_default_output();
    if (!default_output.id.empty()) {
        std::cout << "✓ Default Output: " << default_output.name << std::endl;
        std::cout << "  ID: " << default_output.id << std::endl;
    } else {
        std::cerr << "✗ No default output device found" << std::endl;
        return 1;
    }

    std::cout << std::endl;

    // Test 4: List video devices
    std::cout << "=== Test 4: List Video Source Devices (Cameras) ===" << std::endl;
    auto video_sources = DeviceEnumerator::list_video_sources();

    if (video_sources.empty()) {
        std::cout << "⚠ No video devices found (may not have camera)" << std::endl;
    } else {
        std::cout << "Found " << video_sources.size() << " video device(s):" << std::endl;
        for (size_t i = 0; i < video_sources.size(); i++) {
            const auto &dev = video_sources[i];
            std::cout << "  [" << (i+1) << "] " << (dev.is_default ? "✓ DEFAULT" : "         ")
                      << " " << dev.name << std::endl;
            std::cout << "      ID: " << dev.id << std::endl;
            if (!dev.device_path.empty()) {
                std::cout << "      Path: " << dev.device_path << std::endl;
            }
            if (!dev.description.empty()) {
                std::cout << "      Class: " << dev.description << std::endl;
            }
        }

        auto default_video = DeviceEnumerator::get_default_video_source();
        if (!default_video.id.empty()) {
            std::cout << "✓ Default Video: " << default_video.name << std::endl;
            std::cout << "  ID: " << default_video.id << std::endl;
        }
    }

    std::cout << std::endl;

    // Summary
    std::cout << "=== Test Summary ===" << std::endl;
    std::cout << "✓ Input devices found: " << inputs.size() << std::endl;
    std::cout << "✓ Output devices found: " << outputs.size() << std::endl;
    std::cout << "✓ Default input: " << default_input.name << std::endl;
    std::cout << "✓ Default output: " << default_output.name << std::endl;
    if (!video_sources.empty()) {
        std::cout << "✓ Video devices found: " << video_sources.size() << std::endl;
    } else {
        std::cout << "⚠ Video devices: 0 (no camera available)" << std::endl;
    }
    std::cout << std::endl;
    std::cout << "=== ✓ ALL TESTS PASSED ===" << std::endl;

    return 0;
}
