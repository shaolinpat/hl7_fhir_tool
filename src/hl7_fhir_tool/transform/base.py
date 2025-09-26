# src/hl7_fhir_tool/transform/base.py
"""
Transform protocol for HL7 v2 -> FHIR conversions.
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable
from hl7apy.core import Message
from fhir.resources.resource import Resource

__all__ = ["Transformer", "TransformResult"]

# Alias for readability in implementations and type hints.
TransformResult = List[Resource]


@runtime_checkable
class Transformer(Protocol):
    """
    Interface for message transformers.

    Implementations declare the HL7 trigger event they handle (e.g., "ADT^A01"),
    decide if a given message applies to them, and produce one or more FHIR
    resources from that message.
    """

    event: str  # e.g., "ADT^A01"

    def applies(self, msg: Message) -> bool:
        """
        Return True if this transformer should handle the given HL7 message.

        Parameters
        ----------
        msg : Message
            Parsed HL7 v2 message.

        Returns
        -------
        bool
            True if the message matches this transformer's trigger/event.
        """
        ...

    def transform(self, msg: Message) -> TransformResult:
        """
        Transform the HL7 message into one or more FHIR resources.

        Parameters
        ----------
        msg : Message
            Parsed HL7 v2 message.

        Returns
        -------
        TransformResult
            A list of FHIR Resource instances produced from the message.
        """
        ...
