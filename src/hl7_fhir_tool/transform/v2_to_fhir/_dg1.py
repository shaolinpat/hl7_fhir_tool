# src/hl7_fhir_tool/transform/v2_to_fhir/_dg1.py
"""
DG1 segment parsing -> FHIR Condition resources.

Shared by ADT^A01, ADT^A03, and ADT^A08 transformers. Each transformer calls
build_conditions(msg, patient_id) and appends the result to its resource list.
A Condition is produced only when a diagnosis code is present in DG1-3; messages
without DG1 segments return an empty list.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.condition import Condition
from fhir.resources.reference import Reference

LOG = logging.getLogger(__name__)

# Map HL7 DG1-3.3 coding system identifiers to FHIR system URIs.
_SYSTEM_MAP: dict[str, str] = {
    "I10": "http://hl7.org/fhir/sid/icd-10",
    "ICD10": "http://hl7.org/fhir/sid/icd-10",
    "ICD-10": "http://hl7.org/fhir/sid/icd-10",
    "I9": "http://hl7.org/fhir/sid/icd-9-cm",
    "ICD9": "http://hl7.org/fhir/sid/icd-9-cm",
}
_DEFAULT_SYSTEM = "http://hl7.org/fhir/sid/icd-10"


# ------------------------------------------------------------------------------
# ER7 helpers
# ------------------------------------------------------------------------------


def _er7(x: object | None) -> str:
    """
    Coerce a value to a stripped ER7 string.

    Parameters
    ----------
    x : object or None
        An hl7apy element (with to_er7) or a generic value.

    Returns
    -------
    str
        A stripped ER7 string, or an empty string if conversion fails.
    """
    if x is None:
        return ""
    try:
        s = x.to_er7() if hasattr(x, "to_er7") else str(x)
        return (s or "").strip()
    except Exception:
        return ""


def _field_comp_from_er7(
    er7_line: Optional[str], field_index: int, comp_index: int
) -> Optional[str]:
    """
    Extract a specific component from a raw ER7 segment line.

    Parameters
    ----------
    er7_line : str or None
        Full segment line (e.g., "DG1|1||E11.9^Type 2 diabetes^I10").
    field_index : int
        1-based field index (e.g., 3 for DG1-3).
    comp_index : int
        1-based component index within the field.

    Returns
    -------
    str or None
        The component value, or None if unavailable.
    """
    if not er7_line:
        return None
    parts = er7_line.strip().split("|")
    if field_index < 1 or len(parts) <= field_index:
        return None
    field = parts[field_index]
    comps = field.split("^") if field else []
    if comp_index < 1 or len(comps) < comp_index:
        return None
    val = comps[comp_index - 1].strip()
    return val or None


# ------------------------------------------------------------------------------
# DG1 segment discovery
# ------------------------------------------------------------------------------


def _dg1_er7_lines(msg: object) -> list[str]:
    """
    Extract all raw DG1 ER7 lines from the message.

    Parameters
    ----------
    msg : object
        HL7 message with a to_er7() method.

    Returns
    -------
    list of str
        One entry per DG1 segment line found, in message order.
    """
    try:
        raw = msg.to_er7() if hasattr(msg, "to_er7") else ""
        return [
            line
            for line in raw.replace("\n", "\r").split("\r")
            if line.startswith("DG1")
        ]
    except Exception:
        return []


def _find_dg1_segments(msg: object) -> list:
    """
    Return all DG1 segment objects from the message.

    Tries direct attribute access first, then iterates children.

    Parameters
    ----------
    msg : object
        HL7 message or group node.

    Returns
    -------
    list
        DG1 segment objects; empty if none found.
    """
    try:
        segs = getattr(msg, "DG1", None)
        if segs is not None:
            if isinstance(segs, list):
                return [s for s in segs if s is not None]
            return [segs]
    except Exception:
        pass

    try:
        result = []
        for child in getattr(msg, "children", None) or []:
            try:
                if getattr(child, "name", None) == "DG1":
                    result.append(child)
            except Exception:
                pass
        if result:
            return result
    except Exception:
        pass

    return []


# ------------------------------------------------------------------------------
# system uri resolver
# ------------------------------------------------------------------------------


def _resolve_system(raw_system: Optional[str]) -> str:
    """
    Map a raw HL7 coding system string to a FHIR system URI.

    Parameters
    ----------
    raw_system : str or None
        Value from DG1-3.3 (e.g., "I10"). None or unrecognized values fall back
        to the ICD-10 default.

    Returns
    -------
    str
        FHIR system URI.
    """
    if not raw_system:
        return _DEFAULT_SYSTEM
    return _SYSTEM_MAP.get(raw_system.upper().strip(), _DEFAULT_SYSTEM)


# ------------------------------------------------------------------------------
# condition builder
# ------------------------------------------------------------------------------


def _build_condition_from_dg1(
    dg1_seg: object | None,
    dg1_line: Optional[str],
    patient_id: str,
    ordinal: int,
) -> Optional[Condition]:
    """
    Build a FHIR Condition from a single DG1 segment.

    Uses the ER7 line as primary source for DG1-3 components, falling back to
    structured hl7apy attribute access when the line is absent. Returns None if
    no diagnosis code can be extracted.

    Parameters
    ----------
    dg1_seg : object or None
        hl7apy DG1 segment node, or None.
    dg1_line : str or None
        Raw ER7 line for the DG1 segment.
    patient_id : str
        Patient id used for Condition.subject and Condition.id.
    ordinal : int
        1-based position among DG1 segments in this message.

    Returns
    -------
    Condition or None
        FHIR Condition resource, or None if no code was found.
    """
    # DG1-3.1: diagnosis code
    code_val = _field_comp_from_er7(dg1_line, field_index=3, comp_index=1)
    if not code_val and dg1_seg is not None:
        try:
            dg1_3 = getattr(dg1_seg, "dg1_3", None)
            if isinstance(dg1_3, (list, tuple)):
                dg1_3 = dg1_3[0] if dg1_3 else None
            if dg1_3 is not None:
                c1 = (
                    getattr(dg1_3, "identifier", None)
                    or getattr(dg1_3, "ce_1", None)
                    or getattr(dg1_3, "cwe_1", None)
                )
                code_val = _er7(c1) if c1 is not None else None
        except Exception:
            LOG.debug("DG1-3.1 structured access failed", exc_info=True)

    if not code_val:
        return None

    # DG1-3.2: description text
    text_val = _field_comp_from_er7(dg1_line, field_index=3, comp_index=2)
    if not text_val and dg1_seg is not None:
        try:
            dg1_3 = getattr(dg1_seg, "dg1_3", None)
            if isinstance(dg1_3, (list, tuple)):
                dg1_3 = dg1_3[0] if dg1_3 else None
            if dg1_3 is not None:
                c2 = (
                    getattr(dg1_3, "text", None)
                    or getattr(dg1_3, "ce_2", None)
                    or getattr(dg1_3, "cwe_2", None)
                )
                text_val = _er7(c2) if c2 is not None else None
        except Exception:
            LOG.debug("DG1-3.2 structured access failed", exc_info=True)

    # DG1-3.3: coding system
    system_raw = _field_comp_from_er7(dg1_line, field_index=3, comp_index=3)
    if not system_raw and dg1_seg is not None:
        try:
            dg1_3 = getattr(dg1_seg, "dg1_3", None)
            if isinstance(dg1_3, (list, tuple)):
                dg1_3 = dg1_3[0] if dg1_3 else None
            if dg1_3 is not None:
                c3 = (
                    getattr(dg1_3, "name_of_coding_system", None)
                    or getattr(dg1_3, "ce_3", None)
                    or getattr(dg1_3, "cwe_3", None)
                )
                system_raw = _er7(c3) if c3 is not None else None
        except Exception:
            LOG.debug("DG1-3.3 structured access failed", exc_info=True)

    system = _resolve_system(system_raw)
    coding = Coding(code=code_val, system=system)
    code_cc = CodeableConcept(coding=[coding], text=text_val or None)

    try:
        cond = Condition.model_construct()
    except AttributeError:
        cond = Condition.construct()

    cond.id = f"cond-{patient_id}-{ordinal}"
    cond.code = code_cc
    cond.subject = Reference(reference=f"Patient/{patient_id}")

    return cond


# ------------------------------------------------------------------------------
# public api
# ------------------------------------------------------------------------------


def build_conditions(msg: object, patient_id: str) -> List[Condition]:
    """
    Extract all DG1 segments from a message and return FHIR Condition resources.

    Returns an empty list when no DG1 segments are present or when no diagnosis
    code can be extracted from any DG1.

    Parameters
    ----------
    msg : object
        HL7 message with optional DG1 segment(s).
    patient_id : str
        Patient id used for Condition.subject and Condition.id.

    Returns
    -------
    list of Condition
        One Condition per DG1 segment that contains a diagnosis code.
    """
    dg1_segs = _find_dg1_segments(msg)
    dg1_lines = _dg1_er7_lines(msg)

    count = max(len(dg1_segs), len(dg1_lines))
    if count == 0:
        return []

    conditions: List[Condition] = []
    for i in range(count):
        seg = dg1_segs[i] if i < len(dg1_segs) else None
        line = dg1_lines[i] if i < len(dg1_lines) else None
        cond = _build_condition_from_dg1(seg, line, patient_id, ordinal=i + 1)
        if cond is not None:
            conditions.append(cond)

    return conditions
