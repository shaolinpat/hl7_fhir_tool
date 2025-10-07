# src/hl7_fhir_tool/transform/v2_to_fhir/orm_o01.py
from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional, cast

from hl7apy.core import Message

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.codeablereference import CodeableReference
from fhir.resources.coding import Coding
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.patient import Patient
from fhir.resources.reference import Reference
from fhir.resources.resource import Resource
from fhir.resources.servicerequest import ServiceRequest

from ..registry import register

import logging


# ------------------------------------------------------------------------------
# globals
# ------------------------------------------------------------------------------


LOG = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _parse_hl7_yyyymmdd(val: object) -> Optional[str]:
    """
    Normalize an HL7 date (YYYYMMDD) into ISO 8601 format (YYYY-MM-DD).

    Parameters
    ----------
    val : object
        HL7 value for a date field. If it has to_er7(), that is used;
        otherwise it is coerced with str().

    Returns
    -------
    str or None
        Normalized date string in YYYY-MM-DD format, or None if parsing fails.
    """
    try:
        s = val.to_er7() if hasattr(val, "to_er7") else str(val)
        s = (s or "").strip()
        if len(s) >= 8 and s[:8].isdigit():
            return datetime.strptime(s[:8], "%Y%m%d").date().isoformat()
    except Exception:
        pass
    return None


def _er7(x: object | None) -> str:
    """
    Best-effort ER7 string.

    Parameters
    ----------
    x : object or None
        hl7apy element or value.

    Returns
    -------
    str
        Stripped ER7 string or empty string.
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
    Extract a component from a raw ER7 line.

    Parameters
    ----------
    er7_line : str or None
        Complete segment line in ER7.
    field_index : int
        1-based field position (PID-3 => 3).
    comp_index : int
        1-based component position within the field.

    Returns
    -------
    str or None
        Component value or None if missing.
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


def _find_first(msg_or_group: object, seg_name: str) -> object | None:
    """
    Recursively find the first segment by name in a Message/Group tree.

    Parameters
    ----------
    msg_or_group : object
        hl7apy Message or Group.
    seg_name : str
        Segment name, e.g., 'PID', 'ORC', 'OBR'.

    Returns
    -------
    object or None
        The segment if found, else None.
    """
    try:
        cand = getattr(msg_or_group, seg_name, None)
        if cand is not None:
            LOG.debug(
                "Found %s via attribute on %s", seg_name, type(msg_or_group).__name__
            )
            return cast(object, cand)
    except Exception:
        pass

    try:
        children = getattr(msg_or_group, "children", [])
    except Exception:
        children = []

    for ch in children:
        try:
            if getattr(ch, "name", None) == seg_name:
                LOG.debug(
                    "Found %s directly in children of %s",
                    seg_name,
                    type(msg_or_group).__name__,
                )
                return cast(object, ch)
        except Exception:
            pass

    for ch in children:
        try:
            if getattr(ch, "children", None):
                found = _find_first(ch, seg_name)
                if found is not None:
                    return found
        except Exception:
            pass

    return None


def _first_segment_line(msg: Message, seg_name: str) -> Optional[str]:
    """
    Return the first raw ER7 line for a given segment name.

    Parameters
    ----------
    msg : Message
        hl7apy message.
    seg_name : str
        'PID', 'ORC', 'OBR', etc.

    Returns
    -------
    str or None
        Matching line or None if not present.
    """
    try:
        s_any = msg.to_er7()
        s: str = str(s_any)
    except Exception:
        s = ""
    if not s:
        return None
    for line in s.replace("\n", "\r").split("\r"):
        if line.startswith(seg_name + "|"):
            return line
    return None


# ------------------------------------------------------------------------------
# class ORMO01Transformer
# ------------------------------------------------------------------------------


@register("ORM^O01")
class ORMO01Transformer:
    """
    Transformer for ORM^O01 messages (Order).

    Converts an HL7 v2 ORM^O01 message into a minimal set of FHIR resources:
    Patient and ServiceRequest.

    Attributes
    ----------
    event : str
        HL7 event code handled by this transformer.
    """

    event: str = "ORM^O01"

    def applies(self, msg: Message) -> bool:
        """
        Check whether this transformer applies to the given HL7 message.

        Parameters
        ----------
        msg : Message
            HL7 v2 message to inspect.

        Returns
        -------
        bool
            True if the message is an ORM^O01 event, False otherwise.
        """
        try:
            return str(msg.MSH.msh_9.to_er7()) == self.event
        except Exception as e:
            LOG.debug("Failed to read MSH.9: %s", e)
            return False

    def transform(self, msg: Message) -> List[Resource]:
        """
        Transform an HL7 ORM^O01 message into FHIR resources.

        Parameters
        ----------
        msg : Message
            HL7 v2 message to transform.

        Returns
        -------
        list of Resource
            A list containing:
            - Patient (demographics when available)
            - ServiceRequest (intent=order, status mapped when possible)
        """
        pid_seg = _find_first(msg, "PID")
        orc_seg = _find_first(msg, "ORC")
        obr_seg = _find_first(msg, "OBR")

        pid_line = _first_segment_line(msg, "PID")
        orc_line = _first_segment_line(msg, "ORC")
        obr_line = _first_segment_line(msg, "OBR")

        patient = self._build_patient(pid_seg, pid_line)

        sr = self._build_service_request(
            orc=orc_seg,
            obr=obr_seg,
            patient=patient,
            orc_line=orc_line,
            obr_line=obr_line,
        )

        # one PHI-safe summary at DEBUG (quiet unless enabled)
        LOG.debug(
            "Built ServiceRequest.id=%s intent=%s status=%s code_is_set=%s",
            getattr(sr, "id", None),
            getattr(sr, "intent", None),
            getattr(sr, "status", None),
            getattr(sr, "code", None) is not None,
        )

        return [patient, sr]

    @staticmethod
    def _build_patient(pid: object | None, pid_line: Optional[str]) -> Patient:
        """
        Construct a FHIR Patient from PID.

        Parameters
        ----------
        pid : object or None
            HL7 PID segment.
        pid_line : str or None
            Raw ER7 PID line (fallback).

        Returns
        -------
        Patient
            Patient with id, name, birthDate, gender when available.
        """
        p = Patient()
        if pid is None and not pid_line:
            return p

        try:
            # PID-3 -> Patient.id (simple CX.1)
            val = None
            if pid is not None:
                pid_3 = getattr(pid, "pid_3", None)
                if pid_3 is not None:
                    try:
                        reps = (
                            pid_3
                            if hasattr(pid_3, "__len__") and len(pid_3) > 0
                            else [pid_3]
                        )
                    except Exception:
                        reps = [pid_3]
                    rep0 = reps[0] if reps else None
                    if rep0 is not None:
                        cx_1 = getattr(rep0, "cx_1", None) or getattr(
                            rep0, "id_number", None
                        )
                        if cx_1 is not None:
                            val = _er7(cx_1)
            if not val:
                val = _field_comp_from_er7(pid_line, field_index=3, comp_index=1)
            if val:
                try:
                    p.id = val
                except Exception:
                    LOG.debug("PID-3 value rejected by Patient.id setter")

            # PID-5 -> Patient.name[0]
            fam = giv = None
            if pid is not None:
                pid_5 = getattr(pid, "pid_5", None)
                if pid_5 is not None and hasattr(pid_5, "__len__") and len(pid_5) > 0:
                    fam_raw = getattr(pid_5[0], "family_name", None)
                    giv_raw = getattr(pid_5[0], "given_name", None)
                    if fam_raw is not None:
                        fam = _er7(fam_raw)
                    if giv_raw is not None:
                        giv = _er7(giv_raw)
            if not (fam or giv):
                fam = _field_comp_from_er7(pid_line, field_index=5, comp_index=1) or fam
                giv = _field_comp_from_er7(pid_line, field_index=5, comp_index=2) or giv
            if fam or giv:
                hn = HumanName()
                if fam:
                    hn.family = fam
                if giv:
                    hn.given = [giv]
                p.name = [hn]

            # PID-7 -> birthDate
            bd = None
            if pid is not None:
                pid_7 = getattr(pid, "pid_7", None)
                if pid_7 is not None:
                    bd = _parse_hl7_yyyymmdd(pid_7)
            if not bd:
                raw_bd = _field_comp_from_er7(pid_line, field_index=7, comp_index=1)
                if raw_bd and len(raw_bd) >= 8 and raw_bd[:8].isdigit():
                    bd = datetime.strptime(raw_bd[:8], "%Y%m%d").date().isoformat()
            if bd:
                p.birthDate = date.fromisoformat(bd)

            # PID-8 -> gender
            v = None
            if pid is not None:
                pid_8 = getattr(pid, "pid_8", None)
                if pid_8 is not None:
                    v = _er7(pid_8)
            if not v:
                v = _field_comp_from_er7(pid_line, field_index=8, comp_index=1)
            v = (v or "").upper()
            if v:
                p.gender = {"M": "male", "F": "female"}.get(v, "unknown")

        except Exception:
            LOG.error("Error parsing PID", exc_info=True)

        return p

    @staticmethod
    def _build_service_request(
        orc: object | None,
        obr: object | None,
        patient: Patient,
        orc_line: Optional[str],
        obr_line: Optional[str],
    ) -> ServiceRequest:
        """
        Construct a FHIR ServiceRequest from ORC/OBR.

        Parameters
        ----------
        orc : object or None
            HL7 ORC segment.
        obr : object or None
            HL7 OBR segment.
        patient : Patient
            For fallback id and subject linkage if desired.
        orc_line : str or None
            Raw ER7 ORC line (fallback).
        obr_line : str or None
            Raw ER7 OBR line (fallback).

        Returns
        -------
        ServiceRequest
            ServiceRequest with minimal fields populated.
        """
        intent = "order"

        # Identifiers from ORC-2 (placer) / ORC-3 (filler)
        identifiers: list[Identifier] = []
        sr_id: Optional[str] = None
        try:
            val2 = None
            if orc is not None:
                orc_2 = getattr(orc, "orc_2", None)
                if orc_2 is not None:
                    val2 = _er7(orc_2)
            if not val2:
                val2 = _field_comp_from_er7(orc_line, field_index=2, comp_index=1)
            if val2:
                identifiers.append(Identifier(value=val2))
                sr_id = val2

            val3 = None
            if orc is not None:
                orc_3 = getattr(orc, "orc_3", None)
                if orc_3 is not None:
                    val3 = _er7(orc_3)
            if not val3:
                val3 = _field_comp_from_er7(orc_line, field_index=3, comp_index=1)
            if val3 and not sr_id:
                identifiers.append(Identifier(value=val3))
                sr_id = val3
        except Exception:
            LOG.error("Error parsing ORC", exc_info=True)

        # Code from OBR-4 (Universal Service ID) -> CodeableConcept
        code_cc: Optional[CodeableConcept] = None
        try:
            code_val = _field_comp_from_er7(obr_line, field_index=4, comp_index=1)
            text_val = _field_comp_from_er7(obr_line, field_index=4, comp_index=2)
            if not (code_val or text_val) and obr is not None:
                obr_4 = getattr(obr, "obr_4", None)
                if obr_4 is not None:
                    comp1 = getattr(obr_4, "identifier", None) or getattr(
                        obr_4, "ce_1", None
                    )
                    comp2 = getattr(obr_4, "text", None) or getattr(obr_4, "ce_2", None)
                    code_val = _er7(comp1) if comp1 is not None else None
                    text_val = _er7(comp2) if comp2 is not None else None

            if code_val or text_val:
                coding = [Coding(code=code_val)] if code_val else []
                code_cc = CodeableConcept(coding=coding or None, text=text_val)
        except Exception:
            LOG.error("Error parsing OBR", exc_info=True)

        # Status from ORC-5 (Order status)
        status = "active"
        try:
            v = None
            if orc is not None:
                orc_5 = getattr(orc, "orc_5", None)
                if orc_5 is not None:
                    v = _er7(orc_5)
            if not v:
                v = _field_comp_from_er7(orc_line, field_index=5, comp_index=1)
            v_up = (v or "").upper()
            if v_up:
                status = {
                    "CM": "completed",
                    "IP": "active",
                    "SC": "active",
                    "NW": "active",
                }.get(v_up, "active")
        except Exception:
            LOG.error("Error mapping ORC-5", exc_info=True)

        # Subject is required
        subject_ref = Reference(
            reference=f"Patient/{(getattr(patient, 'id', None) or 'unknown')}"
        )

        # Build ServiceRequest (R5: code is CodeableReference to a CodeableConcept)
        try:
            sr = ServiceRequest(
                intent=intent,
                status=status,
                code=(
                    CodeableReference(concept=code_cc) if code_cc is not None else None
                ),
                identifier=(identifiers or None),
                subject=subject_ref,
            )
        except Exception:
            LOG.debug(
                "ServiceRequest init failed; retrying without code",
                exc_info=True,
            )
            sr = ServiceRequest(
                intent=intent,
                status=status,
                subject=subject_ref,
                identifier=(identifiers or None),
            )

        # Assign id
        if sr_id is not None:
            try:
                sr.id = sr_id
            except Exception:
                pass
        if getattr(sr, "id", None) is None:
            sr.id = f"sr-{getattr(patient, 'id', None)}"

        return sr
