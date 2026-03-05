#!/bin/bash
# WebRTC Test Runner - Uses netcat for bidirectional communication
set -e

cd "$(dirname "$0")"

echo "=== WebRTC Standalone Test Runner ==="
echo ""

# Clean up old logs
rm -f test_caller.log test_answerer.log

# Cleanup function
cleanup() {
    echo ""
    echo "Cleaning up..."
    pkill -P $$ 2>/dev/null || true
    sleep 1
}
trap cleanup EXIT INT TERM

PORT=15555

echo "Starting answerer with netcat relay on port $PORT..."
# Answerer listens, pipes through nc bidirectionally
(nc -l $PORT | ./test_webrtc_answerer 2>&1 | tee answerer_stdout.txt | nc -l $((PORT+1))) &
ANSWERER_PID=$!

# Give answerer time to start listening
sleep 2

echo "Starting caller with netcat connection..."
# Caller connects to answerer's ports
(./test_webrtc_caller 2>&1 | tee caller_stdout.txt | nc localhost $PORT) | nc localhost $((PORT+1)) &
CALLER_PID=$!

echo ""
echo "Both processes started!"
echo "  Answerer: nc -l $PORT | answerer | nc -l $((PORT+1))"
echo "  Caller: caller | nc $PORT | nc $((PORT+1))"
echo ""
echo "Monitoring logs (Ctrl+C to stop)..."
echo ""

# Monitor logs in real-time
tail -f test_caller.log test_answerer.log 2>/dev/null &
TAIL_PID=$!

# Wait for completion
sleep 35

echo ""
echo "=== Test Complete ==="
echo ""

# Show final summaries
if [ -f test_caller.log ]; then
    echo "=== CALLER SUMMARY ==="
    grep "TEST SUMMARY" -A 10 test_caller.log || tail -20 test_caller.log
    echo ""
fi

if [ -f test_answerer.log ]; then
    echo "=== ANSWERER SUMMARY ==="
    grep "TEST SUMMARY" -A 10 test_answerer.log || tail -20 test_answerer.log
fi
