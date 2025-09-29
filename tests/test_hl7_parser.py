# tests/test_hl7_parser.py
"""
Tests for hl7_fhir_tool.hl7_parser.
"""

import pytest
from hl7apy.core import Message

from hl7_fhir_tool.hl7_parser import parse_hl7_v2, to_pretty_segments, to_dict
from hl7_fhir_tool.exceptions import ParseError


# Minimal valid HL7 v2 ADT^A01 (ER7) with CR separators.
VALID_ADT_A01 = (
    "MSH|^~\\&|SEND|SENDER|RECV|RECEIVER|202001011200||ADT^A01|MSG00001|P|2.5\r"
    "PID|1||12345^^^HOSP^MR||Doe^John\r"
    "PV1|1|I\r"
)

# Deliberately odd/invalid message type to trigger strict validation failure,
# but still parseable when strict=False (lenient mode).
MALFORMED_MSGTYPE = (
    "MSH|^~\\&|SEND|SENDER|RECV|RECEIVER|202001011200||BAD^EVT|MSG00002|P|2.5\r"
    "ZXY|freeform\r"
)


# ------------------------------------------------------------------------------
# parse_hl7_v2
# ------------------------------------------------------------------------------


def test_parse_hl7_v2_rejects_non_string():
    with pytest.raises(TypeError, match=r"^raw must be str"):
        parse_hl7_v2(123)


def test_parse_hl7_v2_rejects_empty_string():
    with pytest.raises(ValueError, match=r"^raw must be a non-empty HL7 v2 str"):
        parse_hl7_v2("")


def test_parse_hl7_v2_parses_valid_message_strict():
    msg = parse_hl7_v2(VALID_ADT_A01, strict=True)
    assert isinstance(msg, Message)
    # MSH-9 should be ADT^A01
    msh9 = msg.MSH.msh_9.to_er7()
    assert str(msh9) == "ADT^A01"


def test_parse_hl7_v2_lenient_allows_malformed_message():
    # In lenient mode, odd message types should still parse to a Message
    msg = parse_hl7_v2(MALFORMED_MSGTYPE, strict=False)
    assert isinstance(msg, Message)


def test_parse_hl7_v2_strict_raises_on_malformed_message():
    # In strict mode, malformed message type should raise a ParseError
    with pytest.raises(ParseError, match=r"^Failed to parse HL7 v2 message"):
        parse_hl7_v2(MALFORMED_MSGTYPE, strict=True)


# ------------------------------------------------------------------------------
# to_pretty_segments
# ------------------------------------------------------------------------------


def test_to_pretty_segments_rejects_non_message():
    with pytest.raises(TypeError, match=r"^msg must be hl7apy.core.Message"):
        to_pretty_segments("not a message")


def test_to_pretty_segements_returns_segments_list():
    msg = parse_hl7_v2(VALID_ADT_A01, strict=True)
    segments = to_pretty_segments(msg)
    assert isinstance(segments, list)
    assert segments[0].startswith("MSH|")
    assert any(s.startswith("PID|") for s in segments)
    assert any(s.startswith("PV1|") for s in segments)


# ------------------------------------------------------------------------------
# to_dict
# ------------------------------------------------------------------------------


def test_to_dict_rejects_non_message():
    with pytest.raises(TypeError, match=r"^msg must be hl7apy.core.Message"):
        to_dict(22)


def test_to_dict_groups_segments_by_name():
    msg = parse_hl7_v2(VALID_ADT_A01, strict=True)
    d = to_dict(msg)
    # Expect keys for the segment names present
    assert "MSH" in d and isinstance(d["MSH"], list) and len(d["MSH"]) >= 1
    assert "PID" in d and isinstance(d["PID"], list) and len(d["PID"]) >= 1
    assert "PV1" in d and isinstance(d["PV1"], list) and len(d["PV1"]) >= 1
    # Values are ER7 strings beginning with the segment name
    assert d["MSH"][0].startswith("MSH|")
    assert d["PID"][0].startswith("PID|")
    assert d["PV1"][0].startswith("PV1|")
