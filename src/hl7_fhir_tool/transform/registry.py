# src/hl7_fhir_tool/transform/registry.py
"""
Registry for HL7 v2 to FHIR transformers.

Provides:
- a @register(event) decorator to bind HL7 event strings to transformer classes,
- lookup by event or by HL7 message (via MSH-9),
- listing of available events.
"""

from __future__ import annotations

from typing import Dict, List, Type
from hl7apy.core import Message

from .base import Transformer

# Map HL7 event string (e.g., "ADT^A01") to a transformer class.
_REGISTRY: Dict[str, Type[Transformer]] = {}


def register(event: str):
    """
    Decorator to register a Transformer class for a specific HL7 event.

    Parameters
    ----------
    event : str
        HL7 trigger event string, e.g., "ADT^A01".

    Raises
    ------
    ValueError
        If the event is already registered.

    Returns
    -------
    callable
        A class decorator that registers the transformer.
    """

    def _wrap(cls: Type[Transformer]) -> Type[Transformer]:
        if event in _REGISTRY:
            raise ValueError(f"Transformer already registered for event {event!r}")
        if not isinstance(cls, type):
            raise TypeError(
                f"Only classes can be registered as transformers, got {type(cls)}"
            )
        # Basic runtime check that the class implements the required methods.
        if not callable(getattr(cls, "applies", None)) or not callable(
            getattr(cls, "transform", None)
        ):
            raise TypeError(
                f"Class {cls.__name__} does not implement Transformer protocol"
            )

        _REGISTRY[event] = cls
        return cls

    return _wrap


def available_events() -> List[str]:
    """
    List all registered HL7 event strings.

    Returns
    -------
    List[str]
        Sorted list of event identifiers (e.g., ["ADT^A01", "ADT^A04"]).
    """
    return sorted(_REGISTRY.keys())


def get_transformer(msg: Message) -> Transformer | None:
    """
    Look up and instantiate a transformer for the given HL7 message.

    Parameters
    ----------
    msg : Message
        Parsed HL7 v2 message. The MSH-9 field is expected to contain
        the message type (e.g., "ADT^A01").

    Returns
    -------
    Transformer or None
        An instance of the corresponding transformer class, or None if
        no transformer is registered for the message type.
    """
    try:
        msh9 = getattr(msg.MSH, "msh_9")
    except Exception:
        return None

    # Get a raw text value out of msh_9 in a few tolerant ways.
    try:
        to_er7 = getattr(msh9, "to_er7", None)
        if callable(to_er7):
            raw = to_er7()
        else:
            raw = getattr(msh9, "value", msh9)
    except Exception:
        return None

    if raw is None:
        return None

    # Normalize to a clean string: handle bytes, strip whitespace.
    if isinstance(raw, bytes):
        msg_type = raw.decode("ascii", "ignore").strip()
    else:
        msg_type = str(raw).strip()

    # hl7 MSH-9 can be composite; accept the common "ADT^A01[^...]" form
    # and take only the first two components if present.
    if "^" in msg_type:
        parts = msg_type.split("^")
        msg_type = f"{parts[0]}^{parts[1]}"

    cls = _REGISTRY.get(msg_type)
    return cls() if cls else None
