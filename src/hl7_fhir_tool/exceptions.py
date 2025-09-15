# src/hl7_fhir_tool/exceptions.py
class HL7FHIRToolError(Exception):
    pass


class ParseError(HL7FHIRToolError):
    pass


class TransformError(HL7FHIRToolError):
    pass
