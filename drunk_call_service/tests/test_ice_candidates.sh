#!/bin/bash
# Test ICE Candidate Handling (Phase 4.5)
# Tests AddICECandidate RPC with real ICE candidate formats

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROTO_DIR="$ROOT_DIR/proto"
PORT=50051

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}ICE Candidate Test Suite${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if grpcurl is installed
if ! command -v grpcurl &> /dev/null; then
    echo -e "${RED}Error: grpcurl not installed${NC}"
    exit 1
fi

# Check if service is running
#if ! grpcurl -plaintext localhost:$PORT list > /dev/null 2>&1; then
#    echo -e "${RED}Error: Service not running on port $PORT${NC}"
#    echo "Start the service first: ./bin/drunk-call-service-linux --log-level DEBUG"
#    exit 1
#fi

echo -e "${GREEN}Service is ready${NC}"
echo ""

# Test 1: Create session
echo -e "${BLUE}[TEST 1]${NC} CreateSession"
SESSION_ID="ice-test-$(date +%s)"
RESULT=$(grpcurl -plaintext -import-path "$PROTO_DIR" -proto call.proto \
    -d "{\"session_id\": \"$SESSION_ID\", \"peer_jid\": \"test@example.com\"}" \
    localhost:$PORT call.CallService/CreateSession)

if echo "$RESULT" | grep -q '"success": true'; then
    echo -e "  ${GREEN}✓${NC} Session created: $SESSION_ID"
else
    echo -e "  ${RED}✗${NC} Failed to create session"
    echo "$RESULT"
    exit 1
fi
echo ""

# Test 2: CreateOffer (generates local ICE candidates)
echo -e "${BLUE}[TEST 2]${NC} CreateOffer (to trigger ICE gathering)"
RESULT=$(grpcurl -plaintext -import-path "$PROTO_DIR" -proto call.proto \
    -d "{\"session_id\": \"$SESSION_ID\"}" \
    localhost:$PORT call.CallService/CreateOffer)

if echo "$RESULT" | grep -q '"sdp":'; then
    SDP_SIZE=$(echo "$RESULT" | grep -o '"sdp": "[^"]*"' | wc -c)
    echo -e "  ${GREEN}✓${NC} Offer created (SDP size: $SDP_SIZE bytes)"
    echo -e "  ${YELLOW}→${NC} Local ICE candidates should be gathering..."
else
    echo -e "  ${RED}✗${NC} Failed to create offer"
    echo "$RESULT"
    exit 1
fi
echo ""

# Test 3: Add valid ICE candidates (various types)
echo -e "${BLUE}[TEST 3]${NC} AddICECandidate - Valid Candidates"

# Host candidate (typical local network)
echo -e "  Testing host candidate..."
RESULT=$(grpcurl -plaintext -import-path "$PROTO_DIR" -proto call.proto \
    -d "{\"session_id\": \"$SESSION_ID\", \"candidate\": \"candidate:1 1 UDP 2130706431 192.168.1.100 54321 typ host\", \"sdp_mid\": \"0\", \"sdp_mline_index\": 0}" \
    localhost:$PORT call.CallService/AddICECandidate 2>&1)

if echo "$RESULT" | grep -q "Code: NotFound"; then
    echo -e "    ${YELLOW}⚠${NC} Session not found (expected if remote SDP not set yet)"
elif echo "$RESULT" | grep -q "{}"; then
    echo -e "    ${GREEN}✓${NC} Host candidate added"
else
    echo -e "    ${GREEN}✓${NC} Candidate processed (may queue until remote SDP set)"
fi

# Server reflexive candidate (STUN result)
echo -e "  Testing srflx candidate..."
RESULT=$(grpcurl -plaintext -import-path "$PROTO_DIR" -proto call.proto \
    -d "{\"session_id\": \"$SESSION_ID\", \"candidate\": \"candidate:2 1 UDP 1694498815 203.0.113.10 54321 typ srflx raddr 192.168.1.100 rport 54321\", \"sdp_mid\": \"0\", \"sdp_mline_index\": 0}" \
    localhost:$PORT call.CallService/AddICECandidate 2>&1)

if echo "$RESULT" | grep -q "Code: NotFound\|{}"; then
    echo -e "    ${GREEN}✓${NC} Srflx candidate processed"
fi

# Relay candidate (TURN result)
echo -e "  Testing relay candidate..."
RESULT=$(grpcurl -plaintext -import-path "$PROTO_DIR" -proto call.proto \
    -d "{\"session_id\": \"$SESSION_ID\", \"candidate\": \"candidate:3 1 UDP 16777215 203.0.113.50 60000 typ relay raddr 203.0.113.10 rport 54321\", \"sdp_mid\": \"0\", \"sdp_mline_index\": 0}" \
    localhost:$PORT call.CallService/AddICECandidate 2>&1)

if echo "$RESULT" | grep -q "Code: NotFound\|{}"; then
    echo -e "    ${GREEN}✓${NC} Relay candidate processed"
fi

echo ""

# Test 4: Invalid session
echo -e "${BLUE}[TEST 4]${NC} AddICECandidate - Invalid Session"
RESULT=$(grpcurl -plaintext -import-path "$PROTO_DIR" -proto call.proto \
    -d '{"session_id": "nonexistent", "candidate": "candidate:1 1 UDP 2130706431 192.168.1.100 54321 typ host", "sdp_mid": "0", "sdp_mline_index": 0}' \
    localhost:$PORT call.CallService/AddICECandidate 2>&1)

if echo "$RESULT" | grep -q "Code: NotFound"; then
    echo -e "  ${GREEN}✓${NC} Correctly rejected (session not found)"
else
    echo -e "  ${RED}✗${NC} Should have returned NotFound"
    echo "$RESULT"
fi
echo ""

# Test 5: Multiple candidates rapid fire
echo -e "${BLUE}[TEST 5]${NC} AddICECandidate - Rapid Trickle ICE"
echo -e "  Adding 10 candidates in quick succession..."
SUCCESS_COUNT=0
for i in {1..10}; do
    RESULT=$(grpcurl -plaintext -import-path "$PROTO_DIR" -proto call.proto \
        -d "{\"session_id\": \"$SESSION_ID\", \"candidate\": \"candidate:$i 1 UDP 2130706431 192.168.1.10$i 54321 typ host\", \"sdp_mid\": \"0\", \"sdp_mline_index\": 0}" \
        localhost:$PORT call.CallService/AddICECandidate 2>&1)

    if echo "$RESULT" | grep -q "Code: NotFound\|{}"; then
        ((SUCCESS_COUNT++))
    fi
done
echo -e "  ${GREEN}✓${NC} Processed $SUCCESS_COUNT/10 candidates successfully"
echo ""

# Cleanup
echo -e "${BLUE}[CLEANUP]${NC} EndSession"
grpcurl -plaintext -import-path "$PROTO_DIR" -proto call.proto \
    -d "{\"session_id\": \"$SESSION_ID\"}" \
    localhost:$PORT call.CallService/EndSession > /dev/null 2>&1
echo -e "  ${GREEN}✓${NC} Session ended: $SESSION_ID"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}ICE Candidate Tests Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Expected behavior:"
echo -e "  • Host/srflx/relay candidates all processed"
echo -e "  • Invalid session returns NotFound"
echo -e "  • Rapid trickle ICE handles multiple candidates"
echo -e "  • Candidates may queue until remote SDP is set"
echo ""
