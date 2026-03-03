#!/bin/bash
# Test script for gRPC service - exercises all RPC methods
# Usage: ./test_grpc_service.sh [--keep-running]

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN="$ROOT_DIR/bin/drunk-call-service-linux"
PROTO_DIR="$ROOT_DIR/proto"
LOG_DIR="$ROOT_DIR/app/logs"
LOG_FILE="$LOG_DIR/drunk-call-service.log"
PORT=50051
KEEP_RUNNING=false

# Parse arguments
if [ "$1" == "--keep-running" ]; then
    KEEP_RUNNING=true
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}gRPC Service Test Suite${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if binary exists
if [ ! -f "$BIN" ]; then
    echo -e "${RED}Error: Binary not found at $BIN${NC}"
    echo "Run 'make' first to build the service"
    exit 1
fi

# Check if grpcurl is installed
if ! command -v grpcurl &> /dev/null; then
    echo -e "${RED}Error: grpcurl not installed${NC}"
    echo "Install with: go install github.com/fullstorydev/grpcurl/cmd/grpcurl@latest"
    exit 1
fi

# Kill any existing service
# echo -e "${YELLOW}Cleaning up any existing service...${NC}"
# pkill -f drunk-call-service-linux || true
# sleep 1

# Clear old logs
# rm -f "$LOG_FILE"

# Start service in background
echo -e "${GREEN}Starting service on port $PORT...${NC}"
LSAN_OPTIONS=suppressions="$ROOT_DIR/lsan.supp" \
    "$BIN" --log-level DEBUG --port "$PORT" > /dev/null 2>&1 &
SERVICE_PID=$!

# Wait for service to start
echo -n "Waiting for service to be ready..."
for i in {1..30}; do
    if grpcurl -plaintext localhost:$PORT list > /dev/null 2>&1; then
        echo -e " ${GREEN}Ready!${NC}"
        break
    fi
    sleep 0.1
    echo -n "."
done
echo ""

# Give it a moment to finish initialization
sleep 0.5

# Function to run grpcurl command
grpc_call() {
    local method=$1
    local data=$2
    local name=$3

    echo -e "${BLUE}[TEST]${NC} $name"
    echo -e "  ${YELLOW}→${NC} $method"

    if [ -n "$data" ]; then
        grpcurl -plaintext \
            -import-path "$PROTO_DIR" \
            -proto call.proto \
            -d "$data" \
            localhost:$PORT "$method" 2>&1 | sed 's/^/  /'
    else
        grpcurl -plaintext \
            -import-path "$PROTO_DIR" \
            -proto call.proto \
            localhost:$PORT "$method" 2>&1 | sed 's/^/  /'
    fi

    echo ""
    sleep 0.1
}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Testing Implemented Methods${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Test Heartbeat (implemented)
grpc_call "call.CallService/Heartbeat" '{}' "Heartbeat (should succeed)"

# Test CreateSession (implemented)
grpc_call "call.CallService/CreateSession" \
    '{"session_id": "test-session-1", "peer_jid": "alice@example.com", "relay_only": true}' \
    "CreateSession (should succeed)"

# Test CreateSession duplicate (should warn)
grpc_call "call.CallService/CreateSession" \
    '{"session_id": "test-session-1", "peer_jid": "bob@example.com"}' \
    "CreateSession duplicate (should return error)"

# Create second session
grpc_call "call.CallService/CreateSession" \
    '{"session_id": "test-session-2", "peer_jid": "charlie@example.com"}' \
    "CreateSession #2 (should succeed)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Testing Unimplemented Methods (Phase 4.4+)${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Test unimplemented methods (should return UNIMPLEMENTED)
grpc_call "call.CallService/CreateOffer" \
    '{"session_id": "test-session-1"}' \
    "CreateOffer (Phase 4.4 - should show WARN)"

grpc_call "call.CallService/CreateAnswer" \
    '{"session_id": "test-session-1", "remote_sdp": "v=0..."}' \
    "CreateAnswer (Phase 4.4 - should show WARN)"

grpc_call "call.CallService/SetRemoteDescription" \
    '{"session_id": "test-session-1", "remote_sdp": "v=0...", "sdp_type": "offer"}' \
    "SetRemoteDescription (Phase 4.4 - should show WARN)"

grpc_call "call.CallService/AddICECandidate" \
    '{"session_id": "test-session-1", "candidate": "candidate:...", "sdp_mid": "audio", "sdp_mline_index": 0}' \
    "AddICECandidate (Phase 4.5 - should show WARN)"

grpc_call "call.CallService/ListAudioDevices" \
    '{}' \
    "ListAudioDevices (Phase 4.6 - should show WARN)"

grpc_call "call.CallService/SetMute" \
    '{"session_id": "test-session-1", "muted": true}' \
    "SetMute (Phase 4.6 - should show WARN)"

grpc_call "call.CallService/GetStats" \
    '{"session_id": "test-session-1"}' \
    "GetStats (Phase 4.6 - should show WARN)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Testing Session Lifecycle${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Test StreamEvents in background (will block waiting for events)
echo -e "${BLUE}[TEST]${NC} StreamEvents (non-blocking background)"
echo -e "  ${YELLOW}→${NC} call.CallService/StreamEvents (session: test-session-1)"
grpcurl -plaintext \
    -import-path "$PROTO_DIR" \
    -proto call.proto \
    -d '{"session_id": "test-session-1"}' \
    localhost:$PORT call.CallService/StreamEvents > /tmp/stream_events.log 2>&1 &
STREAM_PID=$!
echo -e "  ${GREEN}StreamEvents started in background (PID: $STREAM_PID)${NC}"
echo ""
sleep 0.5

# End first session (should unblock StreamEvents)
grpc_call "call.CallService/EndSession" \
    '{"session_id": "test-session-1"}' \
    "EndSession #1 (should unblock StreamEvents)"

# Wait for StreamEvents to finish
sleep 0.5
if kill -0 $STREAM_PID 2>/dev/null; then
    echo -e "${YELLOW}StreamEvents still running, killing...${NC}"
    kill $STREAM_PID 2>/dev/null || true
fi

# End second session
grpc_call "call.CallService/EndSession" \
    '{"session_id": "test-session-2"}' \
    "EndSession #2"

# Try to end non-existent session (should warn but not error)
grpc_call "call.CallService/EndSession" \
    '{"session_id": "non-existent"}' \
    "EndSession non-existent (should warn)"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Testing Graceful Shutdown${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ "$KEEP_RUNNING" = true ]; then
    echo -e "${GREEN}Service is running (PID: $SERVICE_PID)${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop, or run:${NC}"
    echo -e "  kill $SERVICE_PID"
    echo -e "  ${YELLOW}or${NC}"
    echo -e "  grpcurl -plaintext -import-path $PROTO_DIR -proto call.proto -d '{}' localhost:$PORT call.CallService/Shutdown"
    echo ""
    echo -e "${BLUE}Logs:${NC} $LOG_FILE"
    wait $SERVICE_PID
else
    # Test graceful shutdown via gRPC
    grpc_call "call.CallService/Shutdown" '{}' "Shutdown via gRPC"

    # Wait for service to exit
    sleep 1
    if kill -0 $SERVICE_PID 2>/dev/null; then
        echo -e "${RED}Service still running, killing forcefully...${NC}"
        kill -9 $SERVICE_PID
    else
        echo -e "${GREEN}Service exited cleanly${NC}"
    fi
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Service Logs (last 50 lines)${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

if [ -f "$LOG_FILE" ]; then
    tail -50 "$LOG_FILE" | grep --color=auto -E 'gRPC:|Phase 8|WARN|ERROR|$'
else
    echo -e "${YELLOW}No log file found at $LOG_FILE${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Test completed successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Full logs: ${BLUE}$LOG_FILE${NC}"
