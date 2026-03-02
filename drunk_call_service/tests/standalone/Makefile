# Standalone GStreamer WebRTC Tests
# Based on official GStreamer examples

CXX = g++
CXXFLAGS = -std=c++17 -Wall -g
PKG_CONFIG = pkg-config

# GStreamer packages
GST_PACKAGES = gstreamer-1.0 gstreamer-webrtc-1.0 gstreamer-sdp-1.0
GST_CFLAGS = $(shell $(PKG_CONFIG) --cflags $(GST_PACKAGES))
GST_LIBS = $(shell $(PKG_CONFIG) --libs $(GST_PACKAGES))

# Targets (in order of complexity)
TESTS = test_step0_gstreamer_basic test_step1_pipeline test_step2_sdp_negotiation test_step3_ice_connectivity test_audio_loopback test_device_enumeration test_stats test_logger

all: $(TESTS)

# Step 0: Basic GStreamer verification
test_step0_gstreamer_basic: test_step0_gstreamer_basic.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS)

# Step 1: Pipeline creation with WebRTCSession class
test_step1_pipeline: test_step1_pipeline.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS) -pthread

# Step 2: SDP offer/answer negotiation
test_step2_sdp_negotiation: test_step2_sdp_negotiation.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS) -pthread

# Step 3: ICE candidate exchange and connectivity
test_step3_ice_connectivity: test_step3_ice_connectivity.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS) -pthread

# Audio loopback (based on GStreamer examples, for reference)
test_audio_loopback: test_audio_loopback.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS)

# Device enumeration test
test_device_enumeration: test_device_enumeration.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS) -pthread

# Stats test
test_stats: test_stats.cpp
	$(CXX) $(CXXFLAGS) $< -o $@ $(GST_CFLAGS) $(GST_LIBS) -pthread

# Logger test
test_logger: test_logger.cpp ../../src/logger.cpp
	$(CXX) $(CXXFLAGS) $^ -o $@ $(shell $(PKG_CONFIG) --cflags --libs spdlog)

clean:
	rm -f $(TESTS)

# Run all tests
test: all
	@echo "=== Running standalone tests ==="
	@echo ""
	@echo "Step 0: GStreamer basic verification"
	./test_step0_gstreamer_basic
	@echo ""
	@echo "Step 1: Pipeline creation and WebRTCSession class"
	./test_step1_pipeline
	@echo ""
	@echo "Step 2: SDP offer/answer negotiation"
	./test_step2_sdp_negotiation
	@echo ""
	@echo "Step 3: ICE candidate exchange and connectivity"
	./test_step3_ice_connectivity
	@echo ""
	@echo "Audio loopback test (manual - Ctrl+C to stop)"
	@echo "Note: This test requires audio devices and user interaction"
	# ./test_audio_loopback

.PHONY: all clean test
