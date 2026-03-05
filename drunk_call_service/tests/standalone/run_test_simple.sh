#!/bin/bash
# Simple WebRTC Test Runner - Uses FIFOs with proper ordering
set -e

cd "$(dirname "$0")"

echo "=== WebRTC Standalone Test (Simple FIFO Method) ==="
echo ""

# Clean up
rm -f test_caller.log test_answerer.log
rm -f /tmp/pipe_c2a /tmp/pipe_a2c

# Create pipes
mkfifo /tmp/pipe_c2a /tmp/pipe_a2c

# Cleanup
cleanup() {
    echo ""
    echo "Cleaning up..."
    rm -f /tmp/pipe_c2a /tmp/pipe_a2c
    pkill -f test_webrtc 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting both processes..."
echo ""

# Start both simultaneously with pipes properly connected
./test_webrtc_answerer < /tmp/pipe_c2a > /tmp/pipe_a2c 2>&1 &
ANSWERER_PID=$!

./test_webrtc_caller > /tmp/pipe_c2a < /tmp/pipe_a2c 2>&1 &
CALLER_PID=$!

echo "Processes started (PID answerer=$ANSWERER_PID, caller=$CALLER_PID)"
echo "Waiting 35 seconds for test..."
echo ""

# Wait
for i in {1..35}; do
    echo -n "."
    sleep 1

    # Check if processes are still running
    if ! kill -0 $ANSWERER_PID 2>/dev/null && ! kill -0 $CALLER_PID 2>/dev/null; then
        echo ""
        echo "Both processes exited early"
        break
    fi
done
echo ""

# Kill if still running
kill $ANSWERER_PID $CALLER_PID 2>/dev/null || true
wait 2>/dev/null || true

echo ""
echo "=== RESULTS ==="
echo ""

if [ -f test_caller.log ]; then
    echo ">>> CALLER <<<"
    grep -E "(SUCCESS|bandwidth|bytes_sent|sendrecv|recvonly)" test_caller.log | tail -10
    echo ""
fi

if [ -f test_answerer.log ]; then
    echo ">>> ANSWERER <<<"
    grep -E "(SUCCESS|bandwidth|bytes_sent|sendrecv|recvonly)" test_answerer.log | tail -10
fi

echo ""
echo "Full logs: test_caller.log, test_answerer.log"
