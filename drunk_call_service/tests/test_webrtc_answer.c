/*
 * Minimal WebRTC Answer Test
 *
 * Reproduces the a=recvonly issue with a minimal test case.
 * Usage: ./test_webrtc_answer
 */

#define GST_USE_UNSTABLE_API

#include <gst/gst.h>
#include <gst/webrtc/webrtc.h>
#include <gst/sdp/sdp.h>
#include <stdio.h>
#include <string.h>

// Dino's actual SDP offer
static const char *DINO_OFFER =
"v=0\r\n"
"o=- 0 0 IN IP4 0.0.0.0\r\n"
"s=-\r\n"
"t=0 0\r\n"
"a=msid-semantic: WMS *\r\n"
"m=audio 9 UDP/TLS/RTP/SAVPF 111 112 113 114 0 8\r\n"
"c=IN IP4 0.0.0.0\r\n"
"a=rtcp:9 IN IP4 0.0.0.0\r\n"
"a=ice-ufrag:GfcS\r\n"
"a=ice-pwd:CwLU/6xPFrw3rnxtrMLQ6N\r\n"
"a=ice-options:trickle\r\n"
"a=fingerprint:sha-256 48:76:4D:FD:20:67:6B:66:B3:22:C7:EA:E4:8C:7A:E6:6E:EA:12:03:E2:5D:17:13:B3:34:EA:AD:E7:72:3B:2B\r\n"
"a=setup:actpass\r\n"
"a=mid:audio\r\n"
"a=sendrecv\r\n"
"a=rtcp-mux\r\n"
"a=rtpmap:111 opus/48000/2\r\n"
"a=rtpmap:112 speex/32000\r\n"
"a=rtpmap:113 speex/16000\r\n"
"a=rtpmap:114 speex/8000\r\n"
"a=rtpmap:0 PCMU/8000\r\n"
"a=rtpmap:8 PCMA/8000\r\n"
"a=fmtp:111 useinbandfec=1\r\n";

static GMainLoop *loop;
static GstElement *pipeline;
static GstElement *webrtc;

// Track if we've connected the sender pipeline
static gboolean sender_connected = FALSE;

// Forward declarations
static void print_transceiver_info(GstElement *webrtcbin, const char *label);
static void connect_sender_pipeline(void);
static guint count_transceivers(GstElement *webrtcbin, const char *label);
static GstCaps* parse_audio_codec_from_offer(GstSDPMessage *offer);

static void
on_negotiation_needed(GstElement *webrtc, gpointer user_data)
{
    printf("Signal: negotiation-needed\n");
}

static void
on_pad_added(GstElement *webrtc, GstPad *new_pad, gpointer user_data)
{
    printf("Signal: pad-added (direction: %s)\n",
           gst_pad_get_direction(new_pad) == GST_PAD_SRC ? "SRC" : "SINK");

    // We only care about src pads (receiver) for now
    // Sink pads are for sending, which we'll connect manually
}

static void
connect_sender_pipeline(void)
{
    if (sender_connected) {
        printf("Sender pipeline already connected\n");
        return;
    }

    printf("Connecting sender pipeline to webrtcbin...\n");
    printf("CRITICAL: Must use existing sink_0 pad (NOT request new one!)\n");

    guint count_before = count_transceivers(webrtc, "Before connecting audio");

    // Create audio source chain
    GstElement *audiotestsrc = gst_element_factory_make("audiotestsrc", NULL);
    GstElement *queue = gst_element_factory_make("queue", NULL);
    GstElement *opusenc = gst_element_factory_make("opusenc", NULL);
    GstElement *rtpopuspay = gst_element_factory_make("rtpopuspay", NULL);

    g_object_set(audiotestsrc, "is-live", TRUE, NULL);
    g_object_set(opusenc, "bitrate", 32000, "frame-size", 20, NULL);

    // Add to pipeline
    gst_bin_add_many(GST_BIN(pipeline), audiotestsrc, queue, opusenc, rtpopuspay, NULL);

    // Link audio chain
    if (!gst_element_link_many(audiotestsrc, queue, opusenc, rtpopuspay, NULL)) {
        printf("ERROR: Failed to link audio chain\n");
        return;
    }

    // Get EXISTING sink_0 pad (don't request new one!)
    GstPad *webrtc_sink = gst_element_get_static_pad(webrtc, "sink_0");
    if (!webrtc_sink) {
        printf("ERROR: sink_0 pad doesn't exist! Did transceiver get created?\n");
        return;
    }

    printf("✓ Got existing sink_0 pad\n");

    // Link rtpopuspay to webrtcbin
    GstPad *pay_src = gst_element_get_static_pad(rtpopuspay, "src");
    if (gst_pad_link(pay_src, webrtc_sink) != GST_PAD_LINK_OK) {
        printf("ERROR: Failed to link rtpopuspay to webrtcbin sink_0\n");
        return;
    }
    gst_object_unref(pay_src);
    gst_object_unref(webrtc_sink);

    printf("✓ Linked rtpopuspay to sink_0\n");

    // Sync state with pipeline
    gst_element_sync_state_with_parent(audiotestsrc);
    gst_element_sync_state_with_parent(queue);
    gst_element_sync_state_with_parent(opusenc);
    gst_element_sync_state_with_parent(rtpopuspay);

    guint count_after = count_transceivers(webrtc, "After connecting audio");

    if (count_after != count_before) {
        printf("❌ ERROR: Transceiver count changed! %u -> %u (should stay same!)\n",
               count_before, count_after);
    } else {
        printf("✅ Transceiver count unchanged: %u (correct!)\n", count_after);
    }

    sender_connected = TRUE;
    printf("✓ Sender pipeline connected\n");
}

static void
on_answer_created(GstPromise *promise, gpointer user_data)
{
    GstWebRTCSessionDescription *answer = NULL;
    const GstStructure *reply;

    reply = gst_promise_get_reply(promise);
    gst_structure_get(reply, "answer", GST_TYPE_WEBRTC_SESSION_DESCRIPTION, &answer, NULL);

    count_transceivers(webrtc, "After answer created");

    if (answer) {
        gchar *sdp_text = gst_sdp_message_as_text(answer->sdp);

        printf("\n========================================\n");
        printf("ANSWER SDP:\n");
        printf("========================================\n");
        printf("%s\n", sdp_text);
        printf("========================================\n");

        // Check if it has a=sendrecv or a=recvonly
        if (strstr(sdp_text, "a=sendrecv")) {
            printf("✅ SUCCESS: Answer has a=sendrecv\n");
        } else if (strstr(sdp_text, "a=recvonly")) {
            printf("❌ FAIL: Answer has a=recvonly (should be sendrecv)\n");
        } else {
            printf("⚠️  WARNING: No direction attribute found\n");
        }

        g_free(sdp_text);
        gst_webrtc_session_description_free(answer);

        // NEW: Connect audio source AFTER answer is created
        printf("\n========================================\n");
        printf("Now connecting audio source pipeline...\n");
        printf("========================================\n");
        connect_sender_pipeline();

        printf("\n========================================\n");
        printf("VERIFICATION: Transceiver details\n");
        printf("========================================\n");
        print_transceiver_info(webrtc, "After audio connected");

        // Check if mline got assigned (should be 0 for audio)
        GArray *transceivers = NULL;
        g_signal_emit_by_name(webrtc, "get-transceivers", &transceivers);
        if (transceivers && transceivers->len > 0) {
            GstWebRTCRTPTransceiver *trans = g_array_index(transceivers, GstWebRTCRTPTransceiver*, 0);
            guint mline;
            g_object_get(trans, "mlineindex", &mline, NULL);

            if (mline == 0) {
                printf("✅ Transceiver mline=0 (assigned correctly)\n");
            } else if (mline == G_MAXUINT) {
                printf("⚠️  WARNING: Transceiver still UNASSIGNED (mline=%u)\n", mline);
                printf("    This is OK - mline assigned during SDP negotiation, not after audio link\n");
            } else {
                printf("❌ Unexpected mline=%u\n", mline);
            }
            g_array_unref(transceivers);
        }
    } else {
        printf("❌ ERROR: Failed to get answer from promise\n");
    }

    gst_promise_unref(promise);
    g_main_loop_quit(loop);
}

static void
on_offer_set(GstPromise *promise, gpointer user_data)
{
    GstPromise *answer_promise;

    printf("Offer set successfully!\n");
    gst_promise_unref(promise);

    count_transceivers(webrtc, "After set-remote-description");
    print_transceiver_info(webrtc, "AFTER set-remote-description");

    printf("Creating answer (transceiver should match offer with our codec-preferences)...\n");

    // Create answer NOW (audio will be connected AFTER answer is created)
    answer_promise = gst_promise_new_with_change_func(on_answer_created, NULL, NULL);
    g_signal_emit_by_name(webrtc, "create-answer", NULL, answer_promise);
}

// Count transceivers with simple logging
static guint
count_transceivers(GstElement *webrtcbin, const char *label)
{
    GArray *transceivers = NULL;
    guint count = 0;

    g_signal_emit_by_name(webrtcbin, "get-transceivers", &transceivers);

    if (transceivers) {
        count = transceivers->len;
        g_array_unref(transceivers);
    }

    printf("[%s] Transceiver count: %u\n", label, count);
    return count;
}

static void
print_transceiver_info(GstElement *webrtcbin, const char *label)
{
    GArray *transceivers = NULL;

    printf("\n%s - Transceiver Info:\n", label);
    printf("----------------------------------------\n");

    g_signal_emit_by_name(webrtcbin, "get-transceivers", &transceivers);

    if (transceivers && transceivers->len > 0) {
        printf("Found %u transceiver(s):\n", transceivers->len);

        if (transceivers->len > 1) {
            printf("⚠️  WARNING: More than 1 transceiver! This may cause audio routing issues!\n");
        }

        for (guint i = 0; i < transceivers->len; i++) {
            GstWebRTCRTPTransceiver *trans = g_array_index(transceivers, GstWebRTCRTPTransceiver*, i);

            GstWebRTCRTPTransceiverDirection dir;
            guint mline;
            GstCaps *codec_prefs = NULL;
            GstWebRTCRTPSender *sender = NULL;

            g_object_get(trans,
                "direction", &dir,
                "mlineindex", &mline,
                "codec-preferences", &codec_prefs,
                "sender", &sender,
                NULL);

            const char *dir_str = "UNKNOWN";
            switch (dir) {
                case GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_NONE: dir_str = "NONE"; break;
                case GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_INACTIVE: dir_str = "INACTIVE"; break;
                case GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_SENDONLY: dir_str = "SENDONLY"; break;
                case GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_RECVONLY: dir_str = "RECVONLY"; break;
                case GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_SENDRECV: dir_str = "SENDRECV"; break;
            }

            printf("  Transceiver %u:\n", i);
            printf("    mline: %u %s\n", mline, (mline == G_MAXUINT) ? "(UNASSIGNED)" : "");
            printf("    direction: %s (%d)\n", dir_str, dir);
            printf("    has sender: %s\n", sender ? "YES" : "NO");

            if (codec_prefs) {
                gchar *caps_str = gst_caps_to_string(codec_prefs);
                printf("    codec-preferences: %s\n", caps_str);
                g_free(caps_str);
                gst_caps_unref(codec_prefs);
            } else {
                printf("    codec-preferences: (none)\n");
            }

            if (sender) {
                g_object_unref(sender);
            }
        }

        g_array_unref(transceivers);
    } else {
        printf("No transceivers found!\n");
    }
    printf("----------------------------------------\n\n");
}

// Parse the first audio codec from the SDP offer
static GstCaps*
parse_audio_codec_from_offer(GstSDPMessage *offer)
{
    const GstSDPMedia *media = NULL;
    const gchar *encoding_name = NULL;
    gint clock_rate = 0;
    gint payload = -1;
    gint encoding_params = 0;

    printf("\n========================================\n");
    printf("Parsing SDP Offer for Audio Codec\n");
    printf("========================================\n");

    // Find the first audio media
    for (guint i = 0; i < gst_sdp_message_medias_len(offer); i++) {
        media = gst_sdp_message_get_media(offer, i);
        if (g_strcmp0(gst_sdp_media_get_media(media), "audio") == 0) {
            printf("Found audio m-line at index %u\n", i);
            break;
        }
        media = NULL;
    }

    if (!media) {
        printf("ERROR: No audio m-line found in offer!\n");
        return NULL;
    }

    // Get the first payload type from the m-line
    if (gst_sdp_media_formats_len(media) > 0) {
        const gchar *payload_str = gst_sdp_media_get_format(media, 0);
        payload = atoi(payload_str);
        printf("First payload type: %d\n", payload);
    } else {
        printf("ERROR: No payload formats in audio m-line!\n");
        return NULL;
    }

    // Find the rtpmap for this payload
    for (guint i = 0; i < gst_sdp_media_attributes_len(media); i++) {
        const GstSDPAttribute *attr = gst_sdp_media_get_attribute(media, i);

        if (g_strcmp0(attr->key, "rtpmap") == 0) {
            // Format: "111 opus/48000/2"
            gchar **parts = g_strsplit(attr->value, " ", 2);
            if (parts[0] && parts[1]) {
                gint attr_payload = atoi(parts[0]);

                if (attr_payload == payload) {
                    // Parse encoding-name/clock-rate/encoding-params
                    gchar **codec_parts = g_strsplit(parts[1], "/", 3);

                    if (codec_parts[0]) {
                        // IMPORTANT: GStreamer uppercases encoding-name in caps!
                        encoding_name = g_ascii_strup(codec_parts[0], -1);
                    }
                    if (codec_parts[1]) {
                        clock_rate = atoi(codec_parts[1]);
                    }
                    if (codec_parts[2]) {
                        encoding_params = atoi(codec_parts[2]);
                    }

                    printf("  rtpmap: %s/%d", encoding_name, clock_rate);
                    if (encoding_params > 0) {
                        printf("/%d", encoding_params);
                    }
                    printf("\n");

                    g_strfreev(codec_parts);
                    g_strfreev(parts);
                    break;
                }
            }
            g_strfreev(parts);
        }
    }

    if (!encoding_name || clock_rate == 0) {
        printf("ERROR: Could not parse rtpmap for payload %d\n", payload);
        return NULL;
    }

    // Create caps WITHOUT fixed payload (flexible matching)
    printf("\nCreating flexible codec-preferences caps:\n");
    printf("  media: audio\n");
    printf("  encoding-name: %s\n", encoding_name);
    printf("  clock-rate: %d\n", clock_rate);
    if (encoding_params > 0) {
        printf("  encoding-params: %d (channels)\n", encoding_params);
    }
    printf("  payload: NOT FIXED (accepts any)\n");
    printf("========================================\n\n");

    GstCaps *caps = gst_caps_new_simple("application/x-rtp",
        "media", G_TYPE_STRING, "audio",
        "encoding-name", G_TYPE_STRING, encoding_name,
        "clock-rate", G_TYPE_INT, clock_rate,
        NULL);

    // Only add encoding-params if present (for stereo/multi-channel)
    if (encoding_params > 0) {
        gst_caps_set_simple(caps,
            "encoding-params", G_TYPE_STRING, g_strdup_printf("%d", encoding_params),
            NULL);
    }

    return caps;
}

int
main(int argc, char *argv[])
{
    GstSDPMessage *offer_sdp = NULL;
    GstWebRTCSessionDescription *offer = NULL;
    GstPromise *promise;

    gst_init(&argc, &argv);

    printf("========================================\n");
    printf("WebRTC Answer Test (Minimal Reproducer)\n");
    printf("========================================\n\n");

    // Create pipeline
    pipeline = gst_pipeline_new("test-pipeline");

    // Create webrtcbin
    webrtc = gst_element_factory_make("webrtcbin", "webrtc");
    g_object_set(webrtc, "bundle-policy", GST_WEBRTC_BUNDLE_POLICY_MAX_BUNDLE, NULL);

    // Add webrtcbin to pipeline
    gst_bin_add(GST_BIN(pipeline), webrtc);

    count_transceivers(webrtc, "Initial (should be 0)");

    // Parse offer SDP FIRST to extract codec info
    if (gst_sdp_message_new(&offer_sdp) != GST_SDP_OK) {
        printf("ERROR: Failed to create SDP message\n");
        return 1;
    }

    if (gst_sdp_message_parse_buffer((const guint8*)DINO_OFFER, strlen(DINO_OFFER), offer_sdp) != GST_SDP_OK) {
        printf("ERROR: Failed to parse offer SDP\n");
        return 1;
    }

    // Parse codec info from the offer
    GstCaps *codec_caps = parse_audio_codec_from_offer(offer_sdp);
    if (!codec_caps) {
        printf("ERROR: Failed to parse audio codec from offer!\n");
        return 1;
    }

    // KEY INSIGHT: Create transceiver with codec-preferences but DON'T link audio yet!
    // This way _find_codec_preferences() will use our preferences (no pad caps to override)

    printf("Creating transceiver with parsed codec caps...\n");

    // DON'T pass caps to request_pad - only use codec-preferences!
    // Passing caps to request_pad might set pad caps which override codec-preferences
    GstPadTemplate *templ = gst_element_get_pad_template(webrtc, "sink_%u");
    GstPad *webrtc_sink = gst_element_request_pad(webrtc, templ, NULL, NULL);  // NULL caps!

    if (!webrtc_sink) {
        printf("ERROR: Failed to request sink pad!\n");
        return 1;
    }

    count_transceivers(webrtc, "After request_pad");

    // Set codec-preferences on the transceiver (CRITICAL!)
    GArray *transceivers = NULL;
    g_signal_emit_by_name(webrtc, "get-transceivers", &transceivers);
    if (transceivers && transceivers->len > 0) {
        GstWebRTCRTPTransceiver *trans = g_array_index(transceivers, GstWebRTCRTPTransceiver*, 0);

        // Set direction to SENDRECV explicitly
        g_object_set(trans,
            "direction", GST_WEBRTC_RTP_TRANSCEIVER_DIRECTION_SENDRECV,
            "codec-preferences", codec_caps,
            NULL);

        printf("✓ Created transceiver with SENDRECV direction and codec-preferences\n");
        g_array_unref(transceivers);
    }

    gst_caps_unref(codec_caps);
    gst_object_unref(webrtc_sink);  // Will get it again later

    printf("Transceiver ready (audio will be connected AFTER offer is processed)\n");

    print_transceiver_info(webrtc, "BEFORE set-remote-description");

    // Start pipeline
    if (gst_element_set_state(pipeline, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
        printf("ERROR: Failed to set pipeline to PLAYING\n");
        return 1;
    }

    printf("Pipeline is PLAYING\n");

    // Create WebRTC session description from already-parsed SDP
    offer = gst_webrtc_session_description_new(GST_WEBRTC_SDP_TYPE_OFFER, offer_sdp);

    printf("\nSetting remote description (offer)...\n");
    count_transceivers(webrtc, "Before set-remote-description");

    // Set remote description
    promise = gst_promise_new_with_change_func(on_offer_set, NULL, NULL);
    g_signal_emit_by_name(webrtc, "set-remote-description", offer, promise);

    gst_webrtc_session_description_free(offer);

    // Run main loop to wait for answer (callbacks will handle the rest)
    loop = g_main_loop_new(NULL, FALSE);
    g_main_loop_run(loop);

    // Cleanup
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(pipeline);
    g_main_loop_unref(loop);

    return 0;
}
