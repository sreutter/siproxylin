#!/bin/bash
# Build minimal WebRTC answer test

echo "Building test_webrtc_answer..."

gcc test_webrtc_answer.c -o test_webrtc_answer \
    $(pkg-config --cflags --libs gstreamer-1.0 gstreamer-webrtc-1.0 gstreamer-sdp-1.0) \
    -Wall

if [ $? -eq 0 ]; then
    echo "✅ Build successful!"
    echo ""
    echo "Run with:"
    echo "  ./test_webrtc_answer"
    echo ""
    echo "Run with detailed GStreamer logging:"
    echo "  GST_DEBUG=webrtcbin:7 ./test_webrtc_answer 2>&1 | tee test_output.log"
else
    echo "❌ Build failed"
    exit 1
fi
