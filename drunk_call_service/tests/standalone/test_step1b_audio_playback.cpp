/**
 * Audio Playback Test
 *
 * Purpose: Verify audio output to default device
 * Tests: Play 2-second 440Hz tone (A4 note) to default speaker
 *
 * Build: make test_step1b_audio_playback
 * Run: ./test_step1b_audio_playback
 *
 * Note: This test should produce audible sound on your speakers/headphones
 */

#include <gst/gst.h>
#include <iostream>
#include <thread>
#include <chrono>

int main(int argc, char *argv[]) {
    gst_init(&argc, &argv);

    std::cout << "=== Audio Playback Test ===" << std::endl;
    std::cout << "Playing 2-second 440Hz tone to default audio device..." << std::endl;
    std::cout << "(You should hear a pure 'A' note through your speakers/headphones)" << std::endl;
    std::cout << std::endl;

    // Create pipeline: audiotestsrc (440Hz) ! audioconvert ! autoaudiosink
    GstElement *pipeline = gst_pipeline_new("audio-test-pipeline");
    GstElement *source = gst_element_factory_make("audiotestsrc", "source");
    GstElement *convert = gst_element_factory_make("audioconvert", "convert");
    GstElement *sink = gst_element_factory_make("autoaudiosink", "sink");

    if (!pipeline || !source || !convert || !sink) {
        std::cerr << "✗ Failed to create elements" << std::endl;
        std::cerr << "  pipeline: " << (pipeline ? "✓" : "✗") << std::endl;
        std::cerr << "  source: " << (source ? "✓" : "✗") << std::endl;
        std::cerr << "  convert: " << (convert ? "✓" : "✗") << std::endl;
        std::cerr << "  sink: " << (sink ? "✓" : "✗") << std::endl;
        return 1;
    }
    std::cout << "✓ Pipeline elements created" << std::endl;

    // Configure audiotestsrc: 440Hz sine wave (musical note A4)
    g_object_set(G_OBJECT(source),
        "wave", 0,              // 0 = sine wave
        "freq", 440.0,          // 440 Hz = A4 note
        "volume", 0.3,          // 30% volume (not too loud)
        nullptr);
    std::cout << "✓ Source configured: 440Hz sine wave, 30% volume" << std::endl;

    // Add elements to pipeline
    gst_bin_add_many(GST_BIN(pipeline), source, convert, sink, nullptr);

    // Link elements: source -> convert -> sink
    if (!gst_element_link_many(source, convert, sink, nullptr)) {
        std::cerr << "✗ Failed to link elements" << std::endl;
        gst_object_unref(pipeline);
        return 1;
    }
    std::cout << "✓ Pipeline linked: audiotestsrc -> audioconvert -> autoaudiosink" << std::endl;

    // Start playing
    GstStateChangeReturn ret = gst_element_set_state(pipeline, GST_STATE_PLAYING);
    if (ret == GST_STATE_CHANGE_FAILURE) {
        std::cerr << "✗ Failed to start pipeline" << std::endl;
        gst_object_unref(pipeline);
        return 1;
    }
    std::cout << "✓ Pipeline PLAYING" << std::endl;
    std::cout << std::endl;

    // Play for 2 seconds
    std::cout << "[Playing 440Hz tone for 2 seconds...]" << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(2));

    // Stop pipeline
    gst_element_set_state(pipeline, GST_STATE_NULL);
    std::cout << "✓ Pipeline stopped" << std::endl;

    // Cleanup
    gst_object_unref(pipeline);
    std::cout << "✓ Pipeline cleaned up" << std::endl;
    std::cout << std::endl;

    std::cout << "=== Audio playback test PASSED ===" << std::endl;
    std::cout << "(If you didn't hear a tone, check your audio settings)" << std::endl;

    return 0;
}
