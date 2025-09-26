# src/hl7_fhir_tool/__init__.py
"""
hl7_fhir_tool: HL7 v2 <-> FHIR transformation utilities.

This package provides:
- A CLI for converting HL7 v2 messages to FHIR resources.
- Parser modules for HL7 and FHIR.
- A transformation registry supporting specific event types (e.g., ADT^A01).
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = [
    "__version__",
]
