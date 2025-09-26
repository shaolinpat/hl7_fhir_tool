# src/hl7_fhir_tool/exceptions.py
"""
Custom exceptions for hl7_fhir_tool.

All exceptions inherit from HL7FHIRToolError so that callers can catch
tool-specific errors without grabbing unrelated built-in exceptions.
"""


class HL7FHIRToolError(Exception):
    """Base class for all hl7_fhir_tool exceptions."""

    pass


class ParseError(HL7FHIRToolError):
    """Raised when an HL7 or FHIR message cannot be parsed correctly."""

    pass


class TransformError(HL7FHIRToolError):
    """Raised when a message transformation fails."""

    pass
