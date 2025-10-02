# src/hl7_fhir_tool/transform/v2_to_fhir/adt_a01.py
"""
ADT^A01 (admit/visit notification) -> minimal FHIR resources.

Notes
-----
- Conservative v2 parsing: we only read a few common PID/PV1 fields.
- We use lenient construction (no full FHIR validation beyond model checks).
- Birthdate is normalized to FHIR date strings when possible:
    YYYYMMDD -> YYYY-MM-DD, YYYYMM -> YYYY-MM, YYYY -> YYYY.
- Invalid timestamp-like values (e.g., YYYYMMDDhhmm) are ignored (unset).
- Gender maps v2 M/F/O/U to FHIR male/female/other/unknown.
- Extend safely: prefer small helpers and targeted parsing per field.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple, cast

from hl7apy.core import Message
from fhir.resources.patient import Patient
from fhir.resources.encounter import Encounter
from fhir.resources.resource import Resource

from ..registry import register
from ..base import Transformer

# Ensure resource_type visible on instances under Pydantic v2
try:
    setattr(Patient, "resource_type", "Patient")
except Exception:
    pass
try:
    setattr(Encounter, "resource_typ", "Encounter")
except Exception:
    pass


# ------------------------------------------------------------------------------
# globals
# ------------------------------------------------------------------------------

EVENT_CODE = "ADT^A01"


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _get_trigger(msh_9: Any) -> Optional[str]:
    """
    Return the trigger (e.g., 'ADT^A01') from MSH-9.
    Separated to allow clean testing of failure cases.
    """
    if msh_9 is None:
        return None
    try:
        return str(msh_9.to_er7()) if hasattr(msh_9, "to_er7") else str(msh_9)
    except Exception:
        return None


def _seq_len_safe(seq: Any) -> int:
    """
    Return len(seq) but isolate so tests can inject objects whose __len__ explodes.
    """
    return len(seq)


@register(EVENT_CODE)
class ADTA01Transformer(Transformer):
    """
    Minimal transformer for ADT^A01 messages.
    """

    event = EVENT_CODE

    def applies(self, msg: Message) -> bool:
        """
        Return True if the message is ADT^A01.

        We avoid raising if MSH or MSH-9 are missing or oddly structured.
        """
        try:
            msh_9 = msg.MSH.msh_9
        except Exception:
            return False

        trigger = _get_trigger(msh_9)
        return trigger == self.event

    def transform(self, msg: Message) -> List[Resource]:
        """
        Produce a minimal Patient and Encounter from PID and PV1.
        """
        # Accept either uppercase (segment objects) or lowercase (hl7apy proxies)
        patient = self._build_patient(getattr(msg, "PID", getattr(msg, "pid", None)))
        encounter = self._build_encounter(
            getattr(msg, "PV1", getattr(msg, "pv1", None))
        )
        return [patient, encounter]

    # --------------------------------------------------------------------------
    # internal helpers
    # --------------------------------------------------------------------------

    @staticmethod
    def _build_patient(pid: Any) -> Patient:
        """
        Create a lenient Patient from PID.
        """
        # Pydantic v2 first, fallback to v1
        try:
            p = Patient.model_construct()
        except AttributeError:
            p = Patient.construct()

        if pid is None:
            return p

        # Identifier: PID-3[0].1 (ID number)
        ident_val = _pid_identifier(pid)
        if ident_val:
            # fhir.resources converts dicts to Identifier models
            p.identifier = [{"value": ident_val}]

        # Name: PID-5[0] family/given (simple)
        family, given = _pid_name(pid)
        if family or given:
            entry: dict[str, Any] = {}
            if family:
                entry["family"] = family
            if given:
                entry["given"] = given  # list[str]
            p.name = [entry]

        # Birth date: PID-7 -> FHIR date when possible
        birth = _pid_birthdate(pid)
        if birth:
            p.birthDate = cast(Any, birth)  # allow FHIR 'date' string

        # Gender: PID-8 -> FHIR enum
        gender = _pid_gender(pid)
        if gender:
            p.gender = gender

        return p

    @staticmethod
    def _build_encounter(pv1: Any) -> Encounter:
        """
        Create a lenient Encounter from PV1.
        """
        # Pydantic v2 first, fallback to v1
        try:
            enc = Encounter.model_construct()
        except AttributeError:
            enc = Encounter.construct()

        if pv1 is None:
            return enc

        # Minimal status policy: if PV1 exists, mark as in-progress.
        try:
            enc.status = "in-progress"
        except Exception:
            # Stay silent; keep encounter skeleton
            pass

        return enc


# ------------------------------------------------------------------------------
# PID field helpers
# ------------------------------------------------------------------------------


def _pid_identifier(pid: Any) -> Optional[str]:
    """
    PID-3[0].1 (ID number) -> "value"
    """
    try:
        pid3 = getattr(pid, "pid_3", None)
        if pid3 and _seq_len_safe(pid3) > 0:
            comp = pid3[0]
            if hasattr(comp, "id_number") and comp.id_number:
                return _safe_str(comp.id_number)
    except Exception:
        pass
    return None


def _pid_name(pid: Any) -> Tuple[Optional[str], List[str]]:
    """
    PID-5[0] family/given -> (family, [given...])
    Only uses the first repetition; extend if needed.
    """
    family: Optional[str] = None
    given_list: List[str] = []
    try:
        pid5 = getattr(pid, "pid_5", None)
        if pid5 and _seq_len_safe(pid5) > 0:
            xpn = pid5[0]
            # Family
            if hasattr(xpn, "family_name") and xpn.family_name:
                family = _safe_str(xpn.family_name)
            # Given (many v2 feeds put a single given_name)
            if hasattr(xpn, "given_name") and xpn.given_name:
                given_list.append(_safe_str(xpn.given_name))
    except Exception:
        pass
    return family, given_list


def _pid_birthdate(pid: Any) -> Optional[str]:
    """
    PID-7 (TS/DTM) -> FHIR date string.
    Accept:
        - YYYYMMDD  -> YYYY-MM-DD
        - YYYYMM    -> YYYY-MM
        - YYYY      -> YYYY
    Reject anything else (return None) to avoid Pydantic date validation errors.
    """
    try:
        if getattr(pid, "pid_7", None):
            raw = _safe_str(pid.pid_7).strip()
            if raw.isdigit():
                if len(raw) == 8:  # YYYYMMDD
                    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
                if len(raw) == 6:  # YYYYMM
                    return f"{raw[0:4]}-{raw[4:6]}"
                if len(raw) == 4:  # YYYY
                    return raw
            # Non-numeric or timestamp-like -> ignore
            return None
    except Exception:
        pass
    return None


def _pid_gender(pid: Any) -> Optional[str]:
    """
    PID-8 v2 to FHIR gender:
        M -> male, F -> female, O -> other, U -> unknown
    """
    try:
        val = _safe_str(getattr(pid, "pid_8", "")).strip().upper()
        if not val:
            return None
        if val.startswith("M"):
            return "male"
        if val.startswith("F"):
            return "female"
        if val.startswith("O"):
            return "other"
        if val.startswith("U"):
            return "unknown"
        # Fallback: unknown for anything else
        return "unknown"
    except Exception:
        return None


# ------------------------------------------------------------------------------
# generic utilities
# ------------------------------------------------------------------------------


def _safe_str(value: Any) -> str:
    """
    Best-effort stringification for hl7apy components/fields.
    Uses to_er7() if available; else str(value).
    """
    try:
        if hasattr(value, "to_er7"):
            return str(value.to_er7())
        return str(value)
    except Exception:
        return ""
