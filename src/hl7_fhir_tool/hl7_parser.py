# src/hl7_fhir_tool/hl7_parser.py
"""
HL7 v2 parsing utilities.

Provides:
- parse_hl7_v2: strict/lenient parsing into an hl7apy Message
- to_pretty_segments: segment-per-line ER7 strings
- to_dict: map of segment name -> list of ER7 strings
"""

from __future__ import annotations

from typing import Any, Dict, List

from hl7apy.consts import VALIDATION_LEVEL
from hl7apy.core import Message
from hl7apy.exceptions import HL7apyException
from hl7apy.parser import parse_message

from .exceptions import ParseError


def parse_hl7_v2(raw: str, *, strict: bool = True) -> Message:
    """
    Parse an HL7 v2 message string into an hl7apy Message.

    Parameters
    ----------
    raw : str
        Raw HL7 v2 message in ER7 format (segments separated by CR/LF).
    strict : bool, default True
        If True, uses hl7apy STRICT validation. If False, uses TOLERANT validation.

    Returns
    -------
    Message
        Parsed HL7 message object.

    Raises
    ------
    TypeError
        If raw is not a string.
    ValueError
        If raw is an empty string.
    ParseError
        If the HL7 message cannot be parsed.
    """
    if not isinstance(raw, str):
        raise TypeError(f"raw must be str, got {type(raw).__name__}")
    if raw.strip() == "":
        raise ValueError("raw must be a non-empty HL7 v2 string")

    # Normalize line endings so \n or \r\n are accepted (HL7 expects \r)
    normalized = raw.replace("\r\n", "\r").replace("\n", "\r")

    # Use hl7apy enum constants (do not pass bare ints)
    vlevel = VALIDATION_LEVEL.STRICT if strict else VALIDATION_LEVEL.TOLERANT
    try:
        return parse_message(normalized, find_groups=False, validation_level=vlevel)
    except HL7apyException as e:
        raise ParseError(f"Failed to parse HL7 v2 message: {e}") from e


def to_pretty_segments(msg: Message) -> List[str]:
    """
    Return a list of ER7 strings, one per segment, in message order.

    Parameters
    ----------
    msg : Message
        Parsed hl7apy message.

    Returns
    -------
    List[str]
        Segment strings (e.g., "PID|...").

    Raises
    ------
    TypeError
        If msg is not an hl7apy.core.Message.
    """
    if not isinstance(msg, Message):
        raise TypeError(f"msg must be hl7apy.core.Message, got {type(msg).__name__}")

    return [seg.to_er7() for seg in msg.children]


def to_dict(msg: Message) -> Dict[str, Any]:
    """
    Return a dictionary mapping segment name to list of ER7 strings.

    Parameters
    ----------
    msg : Message
        Parsed hl7apy message.

    Returns
    -------
    Dict[str, Any]
        Example: {"MSH": ["MSH|^~\\&|..."], "PID": ["PID|...", "PID|..."], ...}

    Raises
    ------
    TypeError
        If msg is not an hl7apy.core.Message.
    """
    if not isinstance(msg, Message):
        raise TypeError(f"msg must be hl7apy.core.Message, got {type(msg).__name__}")

    out: Dict[str, Any] = {}
    for seg in msg.children:
        out.setdefault(seg.name, []).append(seg.to_er7())
    return out
