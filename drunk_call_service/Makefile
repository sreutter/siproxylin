# Makefile wrapper for CMake-based build

BUILD_DIR := build
BIN_DIR := bin

.PHONY: all clean debug release test install help

all: release

# Release build
release:
	@mkdir -p $(BUILD_DIR)
	@cd $(BUILD_DIR) && cmake -DCMAKE_BUILD_TYPE=Release .. && $(MAKE)
	@cmake --install $(BUILD_DIR)

# Debug build (with sanitizers)
debug:
	@mkdir -p $(BUILD_DIR)
	@cd $(BUILD_DIR) && cmake -DCMAKE_BUILD_TYPE=Debug .. && $(MAKE)
	@cmake --install $(BUILD_DIR)

# Run tests
test: release
	@cd $(BUILD_DIR) && ctest --output-on-failure

# Install to bin/
install: release
	@echo "Binary installed to $(BIN_DIR)/"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	@if [ -d "$(BUILD_DIR)" ]; then \
		echo "Removing build directory: $(BUILD_DIR)/"; \
		find $(BUILD_DIR) -type f | wc -l | xargs -I {} echo "  {} files in build/"; \
		du -sh $(BUILD_DIR) | awk '{print "  Size: " $$1}'; \
		rm -rf $(BUILD_DIR); \
		echo "  ✓ $(BUILD_DIR)/ removed"; \
	else \
		echo "  $(BUILD_DIR)/ does not exist (already clean)"; \
	fi
	@if [ -d "$(BIN_DIR)" ]; then \
		echo "Removing binaries: $(BIN_DIR)/"; \
		ls -lh $(BIN_DIR)/ 2>/dev/null | grep -v "^total" | awk '{print "  " $$9 " (" $$5 ")"}' || true; \
		rm -rf $(BIN_DIR); \
		echo "  ✓ $(BIN_DIR)/ removed"; \
	else \
		echo "  $(BIN_DIR)/ does not exist (already clean)"; \
	fi
	@echo "Clean complete"

# Download LibWebRTC prebuilt binaries (placeholder - manual step for now)
deps:
	@echo "Downloading LibWebRTC prebuilt binaries..."
	@echo "TODO: Implement automatic download from https://github.com/webrtc-sdk/libwebrtc/releases"
	@echo "For now, manually download and extract to third_party/libwebrtc/"

# Check dependencies
check-deps:
	@echo "Checking build dependencies..."
	@command -v cmake >/dev/null 2>&1 || { echo "ERROR: cmake not found"; exit 1; }
	@command -v protoc >/dev/null 2>&1 || { echo "ERROR: protoc not found"; exit 1; }
	@command -v grpc_cpp_plugin >/dev/null 2>&1 || { echo "ERROR: grpc_cpp_plugin not found"; exit 1; }
	@pkg-config --exists grpc++ || { echo "ERROR: libgrpc++-dev not found"; exit 1; }
	@pkg-config --exists protobuf || { echo "ERROR: libprotobuf-dev not found"; exit 1; }
	@echo "All dependencies found!"

# Help
help:
	@echo "Drunk Call Service C++ Build System"
	@echo ""
	@echo "Targets:"
	@echo "  make           - Build release version"
	@echo "  make release   - Build optimized release binary"
	@echo "  make debug     - Build with debug symbols and sanitizers"
	@echo "  make test      - Run unit tests"
	@echo "  make clean     - Remove build artifacts"
	@echo "  make deps      - Download LibWebRTC prebuilt binaries"
	@echo "  make check-deps - Verify all build dependencies"
	@echo "  make install   - Install binary to bin/"
	@echo ""
	@echo "Build outputs:"
	@echo "  Binary: bin/drunk-call-service-{linux|windows|darwin}"
	@echo "  Build dir: build/"
