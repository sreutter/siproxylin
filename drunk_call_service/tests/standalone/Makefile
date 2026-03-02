# Standalone GStreamer WebRTC Tests
# Based on official GStreamer examples

CXX = g++
CXXFLAGS = -std=c++17 -Wall -g
PKG_CONFIG = pkg-config

# GStreamer packages
GST_PACKAGES = gstreamer-1.0 gstreamer-webrtc-1.0 gstreamer-sdp-1.0
GST_CFLAGS = $(shell $(PKG_CONFIG) --cflags $(GST_PACKAGES))
GST_LIBS = $(shell $(PKG_CONFIG) --libs $(GST_PACKAGES))

# Targets
TESTS = test_audio_loopback test_pipeline test_sdp_local test_webrtc_session

all: $(TESTS)

test_audio_loopback: test_audio_loopback.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS)

test_pipeline: test_pipeline.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS)

test_sdp_local: test_sdp_local.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS)

test_webrtc_session: test_webrtc_session.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS) -pthread

clean:
	rm -f $(TESTS)

# Run all tests
test: all
	@echo "=== Running standalone tests ==="
	@echo ""
	@echo "Test 1: Pipeline creation"
	./test_pipeline
	@echo ""
	@echo "Test 2: SDP local negotiation"
	./test_sdp_local
	@echo ""
	@echo "Test 3: Audio loopback (manual - Ctrl+C to stop)"
	@echo "Note: This test requires audio devices and user interaction"
	# ./test_audio_loopback

.PHONY: all clean test
