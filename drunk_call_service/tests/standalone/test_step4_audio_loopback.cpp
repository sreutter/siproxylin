/**
 * Audio Loopback Test - Based on GStreamer webrtc.c example
 *
 * Purpose: Test full WebRTC flow without gRPC
 * Two webrtcbin elements in same process, local ICE loopback
 *
 * Based on: drunk_call_service/tmp/gst-plugins-bad1.0-1.22.0/tests/examples/webrtc/webrtc.c
 *
 * Build:
 *   g++ test_audio_loopback.cpp -o test_audio_loopback \
 *       $(pkg-config --cflags --libs gstreamer-webrtc-1.0 gstreamer-sdp-1.0)
 *
 * Run:
 *   GST_DEBUG=3 ./test_audio_loopback
 *   Expected: Hear mic audio from speakers with ~200ms delay
 */

#include <gst/gst.h>
#include <gst/sdp/sdp.h>
#include <gst/webrtc/webrtc.h>
#include <iostream>

static GMainLoop *loop;
static GstElement *pipeline, *webrtc1, *webrtc2;

// Forward declarations
static void on_negotiation_needed(GstElement *element, gpointer user_data);
static void on_ice_candidate(GstElement *webrtc, guint mlineindex, gchar *candidate, GstElement *other);
static void on_offer_created(GstPromise *promise, gpointer user_data);
static void on_answer_created(GstPromise *promise, gpointer user_data);
static void on_incoming_stream(GstElement *webrtc, GstPad *pad, GstElement *pipe);

int main(int argc, char *argv[]) {
    gst_init(&argc, &argv);

    std::cout << "=== WebRTC Audio Loopback Test ===" << std::endl;
    std::cout << "Based on GStreamer examples/webrtc/webrtc.c" << std::endl;
    std::cout << std::endl;

    loop = g_main_loop_new(NULL, FALSE);

    // Create pipeline with two webrtcbin elements
    // webrtc1 = sender (offerer), webrtc2 = receiver (answerer)
    pipeline = gst_parse_launch(
        "audiotestsrc wave=red-noise ! "
        "audioconvert ! audioresample ! queue ! opusenc ! rtpopuspay ! "
        "application/x-rtp,media=audio,encoding-name=OPUS,payload=97 ! "
        "webrtcbin name=send "
        "webrtcbin name=recv",
        NULL);

    if (!pipeline) {
        std::cerr << "Failed to create pipeline" << std::endl;
        return 1;
    }

    // Get webrtcbin elements
    webrtc1 = gst_bin_get_by_name(GST_BIN(pipeline), "send");
    webrtc2 = gst_bin_get_by_name(GST_BIN(pipeline), "recv");

    if (!webrtc1 || !webrtc2) {
        std::cerr << "Failed to get webrtcbin elements" << std::endl;
        return 1;
    }

    std::cout << "Pipeline created successfully" << std::endl;
    std::cout << "  webrtc1 (sender): " << GST_ELEMENT_NAME(webrtc1) << std::endl;
    std::cout << "  webrtc2 (receiver): " << GST_ELEMENT_NAME(webrtc2) << std::endl;

    // Configure webrtcbin properties
    g_object_set(webrtc1, "bundle-policy", 3, NULL);  // max-bundle
    g_object_set(webrtc2, "bundle-policy", 3, NULL);

    std::cout << "Bundle policy: max-bundle" << std::endl;

    // Connect signals
    // webrtc1 creates offer, negotiates
    g_signal_connect(webrtc1, "on-negotiation-needed",
        G_CALLBACK(on_negotiation_needed), NULL);
    g_signal_connect(webrtc1, "on-ice-candidate",
        G_CALLBACK(on_ice_candidate), webrtc2);

    // webrtc2 receives offer, creates answer
    g_signal_connect(webrtc2, "on-ice-candidate",
        G_CALLBACK(on_ice_candidate), webrtc1);
    g_signal_connect(webrtc2, "pad-added",
        G_CALLBACK(on_incoming_stream), pipeline);

    std::cout << "Signals connected" << std::endl;

    // Start pipeline
    std::cout << std::endl << "Starting pipeline..." << std::endl;
    GstStateChangeReturn ret = gst_element_set_state(pipeline, GST_STATE_PLAYING);
    if (ret == GST_STATE_CHANGE_FAILURE) {
        std::cerr << "Failed to start pipeline" << std::endl;
        return 1;
    }

    std::cout << "Pipeline PLAYING" << std::endl;
    std::cout << "Waiting for WebRTC negotiation..." << std::endl;
    std::cout << "(Press Ctrl+C to stop)" << std::endl;
    std::cout << std::endl;

    // Run main loop
    g_main_loop_run(loop);

    // Cleanup
    std::cout << "Stopping pipeline..." << std::endl;
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(webrtc1);
    gst_object_unref(webrtc2);
    gst_object_unref(pipeline);
    g_main_loop_unref(loop);

    std::cout << "Test complete" << std::endl;

    return 0;
}

static void on_negotiation_needed(GstElement *element, gpointer user_data) {
    std::cout << "[SIGNAL] on-negotiation-needed" << std::endl;

    GstPromise *promise = gst_promise_new_with_change_func(on_offer_created, user_data, NULL);
    g_signal_emit_by_name(webrtc1, "create-offer", NULL, promise);

    std::cout << "  → create-offer emitted" << std::endl;
}

static void on_offer_created(GstPromise *promise, gpointer user_data) {
    std::cout << "[CALLBACK] on_offer_created" << std::endl;

    g_assert(gst_promise_wait(promise) == GST_PROMISE_RESULT_REPLIED);

    const GstStructure *reply = gst_promise_get_reply(promise);
    GstWebRTCSessionDescription *offer = NULL;
    gst_structure_get(reply, "offer", GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &offer, NULL);
    gst_promise_unref(promise);

    // Print offer SDP
    gchar *sdp_text = gst_sdp_message_as_text(offer->sdp);
    std::cout << "  Offer SDP created:" << std::endl;
    std::cout << "  ---" << std::endl;
    std::cout << sdp_text << std::endl;
    std::cout << "  ---" << std::endl;
    g_free(sdp_text);

    // Set local description on webrtc1
    promise = gst_promise_new();
    g_signal_emit_by_name(webrtc1, "set-local-description", offer, promise);
    gst_promise_interrupt(promise);
    gst_promise_unref(promise);

    std::cout << "  → set-local-description on webrtc1" << std::endl;

    // Set remote description on webrtc2
    g_signal_emit_by_name(webrtc2, "set-remote-description", offer, NULL);
    std::cout << "  → set-remote-description on webrtc2" << std::endl;

    // Create answer
    promise = gst_promise_new_with_change_func(on_answer_created, user_data, NULL);
    g_signal_emit_by_name(webrtc2, "create-answer", NULL, promise);
    std::cout << "  → create-answer emitted" << std::endl;

    gst_webrtc_session_description_free(offer);
}

static void on_answer_created(GstPromise *promise, gpointer user_data) {
    std::cout << "[CALLBACK] on_answer_created" << std::endl;

    g_assert(gst_promise_wait(promise) == GST_PROMISE_RESULT_REPLIED);

    const GstStructure *reply = gst_promise_get_reply(promise);
    GstWebRTCSessionDescription *answer = NULL;
    gst_structure_get(reply, "answer", GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &answer, NULL);
    gst_promise_unref(promise);

    // Print answer SDP
    gchar *sdp_text = gst_sdp_message_as_text(answer->sdp);
    std::cout << "  Answer SDP created:" << std::endl;
    std::cout << "  ---" << std::endl;
    std::cout << sdp_text << std::endl;
    std::cout << "  ---" << std::endl;
    g_free(sdp_text);

    // Set local description on webrtc2
    promise = gst_promise_new();
    g_signal_emit_by_name(webrtc2, "set-local-description", answer, promise);
    gst_promise_interrupt(promise);
    gst_promise_unref(promise);

    std::cout << "  → set-local-description on webrtc2" << std::endl;

    // Set remote description on webrtc1
    g_signal_emit_by_name(webrtc1, "set-remote-description", answer, NULL);
    std::cout << "  → set-remote-description on webrtc1" << std::endl;

    gst_webrtc_session_description_free(answer);

    std::cout << std::endl << "SDP negotiation complete!" << std::endl;
    std::cout << "Waiting for ICE candidates..." << std::endl;
}

static void on_ice_candidate(GstElement *webrtc, guint mlineindex,
                            gchar *candidate, GstElement *other) {
    std::cout << "[SIGNAL] on-ice-candidate from " << GST_ELEMENT_NAME(webrtc) << std::endl;
    std::cout << "  mlineindex: " << mlineindex << std::endl;
    std::cout << "  candidate: " << candidate << std::endl;

    // Forward candidate to other webrtcbin
    g_signal_emit_by_name(other, "add-ice-candidate", mlineindex, candidate);
    std::cout << "  → forwarded to " << GST_ELEMENT_NAME(other) << std::endl;
}

static void on_incoming_stream(GstElement *webrtc, GstPad *pad, GstElement *pipe) {
    if (GST_PAD_DIRECTION(pad) != GST_PAD_SRC) {
        return;
    }

    std::cout << "[SIGNAL] pad-added (incoming media)" << std::endl;
    std::cout << "  Pad: " << GST_PAD_NAME(pad) << std::endl;

    // Create sink chain for incoming audio
    GstElement *out = gst_parse_bin_from_description(
        "rtpopusdepay ! opusdec ! audioconvert ! audioresample ! autoaudiosink",
        TRUE, NULL);

    gst_bin_add(GST_BIN(pipe), out);
    gst_element_sync_state_with_parent(out);

    GstPad *sink = (GstPad*)out->sinkpads->data;
    gst_pad_link(pad, sink);

    std::cout << "  → Audio sink chain created and linked" << std::endl;
    std::cout << std::endl << "=== Audio should be playing now ===" << std::endl;
}
