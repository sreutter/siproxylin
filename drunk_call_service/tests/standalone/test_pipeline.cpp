/**
 * Pipeline Creation Test
 *
 * Purpose: Verify GStreamer initialization and basic pipeline creation
 * Tests: plugin availability, element creation, state changes
 *
 * Build: make test_pipeline
 * Run: ./test_pipeline
 */

#include <gst/gst.h>
#include <iostream>

bool check_plugin(const char *name) {
    GstRegistry *registry = gst_registry_get();
    GstPlugin *plugin = gst_registry_find_plugin(registry, name);

    if (!plugin) {
        std::cerr << "✗ Plugin not found: " << name << std::endl;
        return false;
    }

    std::cout << "✓ Plugin found: " << name << std::endl;
    gst_object_unref(plugin);
    return true;
}

int main(int argc, char *argv[]) {
    gst_init(&argc, &argv);

    std::cout << "=== Pipeline Creation Test ===" << std::endl;
    std::cout << std::endl;

    // Test 1: GStreamer version
    guint major, minor, micro, nano;
    gst_version(&major, &minor, &micro, &nano);
    std::cout << "GStreamer version: " << major << "." << minor << "." << micro << std::endl;

    if (major < 1 || (major == 1 && minor < 22)) {
        std::cerr << "✗ GStreamer 1.22+ required" << std::endl;
        return 1;
    }
    std::cout << "✓ GStreamer version OK" << std::endl;
    std::cout << std::endl;

    // Test 2: Required plugins
    std::cout << "Checking required plugins:" << std::endl;
    const char *required[] = {
        "opus", "nice", "webrtc", "dtls", "srtp", "rtp", "audioconvert", "coreelements", NULL
    };

    bool all_ok = true;
    for (int i = 0; required[i]; i++) {
        if (!check_plugin(required[i])) {
            all_ok = false;
        }
    }

    if (!all_ok) {
        std::cerr << std::endl << "✗ Missing required plugins" << std::endl;
        return 1;
    }
    std::cout << "✓ All required plugins available" << std::endl;
    std::cout << std::endl;

    // Test 3: Create simple pipeline
    std::cout << "Creating test pipeline..." << std::endl;
    GstElement *pipeline = gst_pipeline_new("test-pipeline");
    GstElement *src = gst_element_factory_make("audiotestsrc", "src");
    GstElement *conv = gst_element_factory_make("audioconvert", "conv");
    GstElement *sink = gst_element_factory_make("fakesink", "sink");

    if (!pipeline || !src || !conv || !sink) {
        std::cerr << "✗ Failed to create elements" << std::endl;
        return 1;
    }
    std::cout << "✓ Elements created" << std::endl;

    gst_bin_add_many(GST_BIN(pipeline), src, conv, sink, NULL);
    if (!gst_element_link_many(src, conv, sink, NULL)) {
        std::cerr << "✗ Failed to link elements" << std::endl;
        return 1;
    }
    std::cout << "✓ Elements linked" << std::endl;

    // Test 4: State changes
    std::cout << "Testing state changes..." << std::endl;
    GstStateChangeReturn ret = gst_element_set_state(pipeline, GST_STATE_PLAYING);
    if (ret == GST_STATE_CHANGE_FAILURE) {
        std::cerr << "✗ Failed to set PLAYING state" << std::endl;
        return 1;
    }
    std::cout << "✓ Pipeline PLAYING" << std::endl;

    // Let it run briefly
    g_usleep(100000);  // 100ms

    gst_element_set_state(pipeline, GST_STATE_NULL);
    std::cout << "✓ Pipeline stopped" << std::endl;

    gst_object_unref(pipeline);
    std::cout << "✓ Pipeline cleanup" << std::endl;

    std::cout << std::endl;
    std::cout << "=== All tests passed ===" << std::endl;

    return 0;
}
