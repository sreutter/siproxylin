#!/usr/bin/env python3
"""
Unit tests for SSRCHandler - SSRC parsing and filtering.

Tests the static methods of SSRCHandler independently from the converter.

Run with: /home/m/claude/xmpp-desktop/venv/bin/pytest tests/test_ssrc_handler.py -v
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import xml.etree.ElementTree as ET
from drunk_call_hook.protocol.features.ssrc import SSRCHandler


# ============================================================================
# Tests for parse_ssrc_from_sdp()
# ============================================================================

def test_parse_ssrc_single_param():
    """Test parsing single SSRC with single parameter."""
    sdp_lines = [
        'a=ssrc:2485877649 cname:pion-audio'
    ]

    result = SSRCHandler.parse_ssrc_from_sdp(sdp_lines)

    assert result == {
        '2485877649': {
            'cname': 'pion-audio'
        }
    }


def test_parse_ssrc_multiple_params():
    """Test parsing single SSRC with multiple parameters."""
    sdp_lines = [
        'a=ssrc:2485877649 cname:pion-audio',
        'a=ssrc:2485877649 msid:stream-id track-id',
        'a=ssrc:2485877649 mslabel:stream-label',
        'a=ssrc:2485877649 label:track-label'
    ]

    result = SSRCHandler.parse_ssrc_from_sdp(sdp_lines)

    assert result == {
        '2485877649': {
            'cname': 'pion-audio',
            'msid': 'stream-id track-id',
            'mslabel': 'stream-label',
            'label': 'track-label'
        }
    }


def test_parse_ssrc_multiple_sources():
    """Test parsing multiple SSRCs (e.g., audio + video)."""
    sdp_lines = [
        'a=ssrc:1111111111 cname:audio-source',
        'a=ssrc:1111111111 msid:audio-stream audio-track',
        'a=ssrc:2222222222 cname:video-source',
        'a=ssrc:2222222222 msid:video-stream video-track'
    ]

    result = SSRCHandler.parse_ssrc_from_sdp(sdp_lines)

    assert result == {
        '1111111111': {
            'cname': 'audio-source',
            'msid': 'audio-stream audio-track'
        },
        '2222222222': {
            'cname': 'video-source',
            'msid': 'video-stream video-track'
        }
    }


def test_parse_ssrc_empty_lines():
    """Test parsing with no SSRC lines."""
    sdp_lines = [
        'a=rtcp-mux',
        'm=audio 9 UDP/TLS/RTP/SAVPF 111'
    ]

    result = SSRCHandler.parse_ssrc_from_sdp(sdp_lines)

    assert result == {}


def test_parse_ssrc_malformed_lines():
    """Test parsing ignores malformed SSRC lines."""
    sdp_lines = [
        'a=ssrc:2485877649 cname:pion-audio',  # Valid
        'a=ssrc:bad-format',  # No space separator
        'a=ssrc:12345',  # No attribute
        'a=ssrc:67890 no-colon-in-attr',  # No colon in attribute
    ]

    result = SSRCHandler.parse_ssrc_from_sdp(sdp_lines)

    # Should only parse the valid line
    assert result == {
        '2485877649': {
            'cname': 'pion-audio'
        }
    }


# ============================================================================
# Tests for filter_ssrc_params()
# ============================================================================

def test_filter_ssrc_params_with_allowed():
    """Test filtering SSRC params to allowed list."""
    ssrc_attrs = {
        'cname': 'pion-audio',
        'msid': 'stream-id track-id',
        'mslabel': 'stream-label',
        'label': 'track-label'
    }
    allowed_params = ['cname', 'msid']

    result = SSRCHandler.filter_ssrc_params(ssrc_attrs, allowed_params)

    assert result == {
        'cname': 'pion-audio',
        'msid': 'stream-id track-id'
    }


def test_filter_ssrc_params_empty_allowed():
    """Test filtering with empty allowed list returns all."""
    ssrc_attrs = {
        'cname': 'pion-audio',
        'msid': 'stream-id track-id'
    }
    allowed_params = []

    result = SSRCHandler.filter_ssrc_params(ssrc_attrs, allowed_params)

    assert result == ssrc_attrs


def test_filter_ssrc_params_no_match():
    """Test filtering with no matching params returns empty."""
    ssrc_attrs = {
        'cname': 'pion-audio',
        'msid': 'stream-id track-id'
    }
    allowed_params = ['label', 'mslabel']

    result = SSRCHandler.filter_ssrc_params(ssrc_attrs, allowed_params)

    assert result == {}


# ============================================================================
# Tests for build_jingle_ssrc_elements()
# ============================================================================

def test_build_jingle_ssrc_elements_offer():
    """Test building Jingle SSRC elements for offer (all params)."""
    ssrc_info = {
        '2485877649': {
            'cname': 'pion-audio',
            'msid': 'stream-id track-id'
        }
    }
    parent = ET.Element('{urn:xmpp:jingle:apps:rtp:1}description')

    count = SSRCHandler.build_jingle_ssrc_elements(ssrc_info, parent, 'offer', None)

    assert count == 1

    # Check XML structure
    sources = parent.findall('{urn:xmpp:jingle:apps:rtp:ssma:0}source')
    assert len(sources) == 1
    assert sources[0].get('ssrc') == '2485877649'

    params = sources[0].findall('{urn:xmpp:jingle:apps:rtp:ssma:0}parameter')
    assert len(params) == 2

    # Check parameters
    param_dict = {p.get('name'): p.get('value') for p in params}
    assert param_dict == {
        'cname': 'pion-audio',
        'msid': 'stream-id track-id'
    }


def test_build_jingle_ssrc_elements_answer_filtered():
    """Test building Jingle SSRC elements for answer (filtered params)."""
    ssrc_info = {
        '2485877649': {
            'cname': 'pion-audio',
            'msid': 'stream-id track-id',
            'mslabel': 'stream-label',
            'label': 'track-label'
        }
    }
    parent = ET.Element('{urn:xmpp:jingle:apps:rtp:1}description')
    allowed_params = ['cname', 'msid']

    count = SSRCHandler.build_jingle_ssrc_elements(ssrc_info, parent, 'answer', allowed_params)

    assert count == 1

    # Check only allowed params are included
    sources = parent.findall('{urn:xmpp:jingle:apps:rtp:ssma:0}source')
    params = sources[0].findall('{urn:xmpp:jingle:apps:rtp:ssma:0}parameter')
    assert len(params) == 2

    param_dict = {p.get('name'): p.get('value') for p in params}
    assert param_dict == {
        'cname': 'pion-audio',
        'msid': 'stream-id track-id'
    }


def test_build_jingle_ssrc_elements_multiple_sources():
    """Test building Jingle SSRC elements for multiple sources."""
    ssrc_info = {
        '1111111111': {
            'cname': 'audio-source'
        },
        '2222222222': {
            'cname': 'video-source'
        }
    }
    parent = ET.Element('{urn:xmpp:jingle:apps:rtp:1}description')

    count = SSRCHandler.build_jingle_ssrc_elements(ssrc_info, parent, 'offer', None)

    assert count == 2

    sources = parent.findall('{urn:xmpp:jingle:apps:rtp:ssma:0}source')
    assert len(sources) == 2

    ssrcs = {s.get('ssrc') for s in sources}
    assert ssrcs == {'1111111111', '2222222222'}


def test_build_jingle_ssrc_elements_empty():
    """Test building with empty SSRC info."""
    ssrc_info = {}
    parent = ET.Element('{urn:xmpp:jingle:apps:rtp:1}description')

    count = SSRCHandler.build_jingle_ssrc_elements(ssrc_info, parent, 'offer', None)

    assert count == 0

    sources = parent.findall('{urn:xmpp:jingle:apps:rtp:ssma:0}source')
    assert len(sources) == 0


# ============================================================================
# Tests for extract_ssrc_params()
# ============================================================================

def test_extract_ssrc_params_single_source():
    """Test extracting SSRC param names from single source."""
    description = ET.fromstring('''
        <description xmlns="urn:xmpp:jingle:apps:rtp:1">
            <source xmlns="urn:xmpp:jingle:apps:rtp:ssma:0" ssrc="2485877649">
                <parameter name="cname" value="pion-audio"/>
                <parameter name="msid" value="stream-id track-id"/>
            </source>
        </description>
    ''')

    result = SSRCHandler.extract_ssrc_params(description)

    assert result == ['cname', 'msid']


def test_extract_ssrc_params_multiple_sources():
    """Test extracting SSRC param names from multiple sources (no duplicates)."""
    description = ET.fromstring('''
        <description xmlns="urn:xmpp:jingle:apps:rtp:1">
            <source xmlns="urn:xmpp:jingle:apps:rtp:ssma:0" ssrc="1111111111">
                <parameter name="cname" value="audio-source"/>
                <parameter name="msid" value="audio-stream audio-track"/>
            </source>
            <source xmlns="urn:xmpp:jingle:apps:rtp:ssma:0" ssrc="2222222222">
                <parameter name="cname" value="video-source"/>
                <parameter name="label" value="video-label"/>
            </source>
        </description>
    ''')

    result = SSRCHandler.extract_ssrc_params(description)

    # Should have all unique param names
    assert set(result) == {'cname', 'msid', 'label'}


def test_extract_ssrc_params_no_sources():
    """Test extracting from description with no sources."""
    description = ET.fromstring('''
        <description xmlns="urn:xmpp:jingle:apps:rtp:1">
            <payload-type id="111" name="opus"/>
        </description>
    ''')

    result = SSRCHandler.extract_ssrc_params(description)

    assert result == []


def test_extract_ssrc_params_empty_source():
    """Test extracting from source with no parameters."""
    description = ET.fromstring('''
        <description xmlns="urn:xmpp:jingle:apps:rtp:1">
            <source xmlns="urn:xmpp:jingle:apps:rtp:ssma:0" ssrc="2485877649">
            </source>
        </description>
    ''')

    result = SSRCHandler.extract_ssrc_params(description)

    assert result == []


# ============================================================================
# Integration Tests (Round-trip)
# ============================================================================

def test_roundtrip_parse_and_build():
    """Test round-trip: parse SDP → build Jingle → extract params."""
    # Parse from SDP
    sdp_lines = [
        'a=ssrc:2485877649 cname:pion-audio',
        'a=ssrc:2485877649 msid:stream-id track-id'
    ]
    ssrc_info = SSRCHandler.parse_ssrc_from_sdp(sdp_lines)

    # Build Jingle XML
    parent = ET.Element('{urn:xmpp:jingle:apps:rtp:1}description')
    SSRCHandler.build_jingle_ssrc_elements(ssrc_info, parent, 'offer', None)

    # Extract param names
    param_names = SSRCHandler.extract_ssrc_params(parent)

    # Should match original SDP params
    assert set(param_names) == {'cname', 'msid'}


def test_roundtrip_offer_answer_filtering():
    """Test offer-answer flow with parameter filtering."""
    # Offer: Conversations sends cname and msid
    offer_sdp = [
        'a=ssrc:1111111111 cname:conv-audio',
        'a=ssrc:1111111111 msid:conv-stream conv-track'
    ]
    offer_ssrc = SSRCHandler.parse_ssrc_from_sdp(offer_sdp)

    # Extract allowed params from offer
    offer_description = ET.Element('{urn:xmpp:jingle:apps:rtp:1}description')
    SSRCHandler.build_jingle_ssrc_elements(offer_ssrc, offer_description, 'offer', None)
    allowed_params = SSRCHandler.extract_ssrc_params(offer_description)

    assert set(allowed_params) == {'cname', 'msid'}

    # Answer: Pion generates additional params
    answer_sdp = [
        'a=ssrc:2222222222 cname:pion-audio',
        'a=ssrc:2222222222 msid:pion-stream pion-track',
        'a=ssrc:2222222222 mslabel:extra-label',  # Extra param not in offer
        'a=ssrc:2222222222 label:extra-label2'    # Extra param not in offer
    ]
    answer_ssrc = SSRCHandler.parse_ssrc_from_sdp(answer_sdp)

    # Build answer with filtering
    answer_description = ET.Element('{urn:xmpp:jingle:apps:rtp:1}description')
    SSRCHandler.build_jingle_ssrc_elements(answer_ssrc, answer_description, 'answer', allowed_params)

    # Check answer only has allowed params
    sources = answer_description.findall('{urn:xmpp:jingle:apps:rtp:ssma:0}source')
    params = sources[0].findall('{urn:xmpp:jingle:apps:rtp:ssma:0}parameter')

    param_names = {p.get('name') for p in params}
    assert param_names == {'cname', 'msid'}  # Only params from offer
