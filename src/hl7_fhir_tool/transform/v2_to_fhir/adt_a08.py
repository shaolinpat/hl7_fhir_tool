# src/hl7_fhir_tool/transform/v2_to_fhir/adt_a08.py
from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

from hl7apy.core import Message

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.encounter import Encounter
from fhir.resources.humanname import HumanName
from fhir.resources.patient import Patient
from fhir.resources.period import Period
from fhir.resources.resource import Resource

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
        # keep silent and let caller decide
        pass
    return None


# ------------------------------------------------------------------------------
# classes
# ------------------------------------------------------------------------------


class EncounterWithPeriod(Encounter):
    """
    Encounter with an explicit period attribute for static typing parity.

    Notes
    -----
    This mirrors the pattern used in the ADT^A03 transformer so that type
    checkers recognize that Encounter.period may be set.
    """

    period: Optional[Period] = None


@register("ADT^A08")
class ADTA08Transformer:
    """
    Transformer for ADT^A08 messages (Update Patient Information).

    Converts an HL7 v2 ADT^A08 message into a minimal set of FHIR resources:
    an updated Patient resource and an Encounter resource in progress.

    Attributes
    ----------
    event : str
        HL7 event code handled by this transformer.
    """

    event: str = "ADT^A08"

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
            True if the message is an ADT^A08 event, False otherwise.
        """
        try:
            return str(msg.MSH.msh_9.to_er7()) == self.event
        except Exception as e:
            LOG.debug("Failed to read MSH.9: %s", e)
            return False

    def transform(self, msg: Message) -> List[Resource]:
        """
        Transform an HL7 ADT^A08 message into FHIR resources.

        Parameters
        ----------
        msg : Message
            HL7 v2 message to transform.

        Returns
        -------
        list of Resource
            A list containing:
            - Patient (demographics updated)
            - Encounter (status set to in-progress)
        """
        patient = self._build_patient(getattr(msg, "PID", None))
        encounter = self._build_encounter(getattr(msg, "PV1", None), patient)
        return [patient, encounter]

    @staticmethod
    def _build_patient(pid: object | None) -> Patient:
        """
        Construct a FHIR Patient resource from the PID segment.

        Parameters
        ----------
        pid : object or None
            HL7 PID segment, or None if missing.

        Returns
        -------
        Patient
            Patient resource with id, name, birthDate, and gender populated
            when available.
        """
        p = Patient()
        if not pid:
            return p

        try:
            # ------------------------------------------------------------------
            # PID-3: identifier -> id
            # ------------------------------------------------------------------
            pid_3 = getattr(pid, "pid_3", None)
            if pid_3 and len(pid_3) > 0:
                cx_1 = getattr(pid_3[0], "cx_1", None)
                if cx_1 is not None:
                    has_to = hasattr(cx_1, "to_er7")
                    val = None
                    if has_to:
                        try:
                            val = cx_1.to_er7()
                        except Exception:
                            val = None
                    else:
                        val = str(cx_1)
                    if val:
                        try:
                            p.id = val
                        except Exception as e:
                            LOG.debug("A08 PID-3: setting Patient.id raised:", repr(e))

            # ------------------------------------------------------------------
            # PID-5: name -> HumanName on patient
            # ------------------------------------------------------------------
            pid_5 = getattr(pid, "pid_5", None)
            fam = None
            giv = None
            if pid_5 and len(pid_5) > 0:
                fam_raw = getattr(pid_5[0], "family_name", None)
                giv_raw = getattr(pid_5[0], "given_name", None)

                if fam_raw is not None:
                    if hasattr(fam_raw, "to_er7"):
                        fam = fam_raw.to_er7()
                    else:
                        fam = str(fam_raw)

                if giv_raw is not None:
                    if hasattr(giv_raw, "to_er7"):
                        giv = giv_raw.to_er7()
                    else:
                        giv = str(giv_raw)

                if fam or giv:
                    # explicit branch, no inline ternary, so coverage attributes lines
                    hn = HumanName()
                    if fam:
                        hn.family = fam
                    if giv:
                        hn.given = [giv]
                    p.name = [hn]

            # ------------------------------------------------------------------
            # PID-7: birth date -> ISO
            # ------------------------------------------------------------------
            pid_7 = getattr(pid, "pid_7", None)
            bd = None
            if pid_7 is not None:
                bd = _parse_hl7_yyyymmdd(pid_7)
            if bd:
                p.birthDate = date.fromisoformat(bd)

            # ------------------------------------------------------------------
            # PID-8: gender -> enum
            # ------------------------------------------------------------------
            pid_8 = getattr(pid, "pid_8", None)
            if pid_8 is not None:
                try:
                    raw = pid_8.to_er7() if hasattr(pid_8, "to_er7") else str(pid_8)
                except Exception as e:
                    LOG.error("PID-8 to_er7 failed: %s", e)
                    raw = ""
                v = (raw or "").strip().upper()
                # explicit mapping so coverage marks these lines
                if v == "M":
                    p.gender = "male"
                elif v == "F":
                    p.gender = "female"
                else:
                    p.gender = "unknown"

        except Exception as e:
            LOG.error("Error parsing PID: %s", e)

        return p

    @staticmethod
    def _build_encounter(pv1: object | None, patient: Patient) -> Encounter:
        """
        Construct a FHIR Encounter resource from the PV1 segment.

        Parameters
        ----------
        pv1 : object or None
            HL7 PV1 segment, or None if missing.
        patient : Patient
            Patient resource used for fallback encounter id if PV1-19 is absent.

        Returns
        -------
        Encounter
            Encounter resource with status in-progress and optional class, id,
            and period populated.
        """
        enc_class: Optional[CodeableConcept] = None
        encounter_id: Optional[str] = None
        start = None
        end = None

        try:
            if pv1:
                # --------------------------------------------------------------
                # PV1-2: class
                # --------------------------------------------------------------
                pv1_2 = getattr(pv1, "pv1_2", None)
                if pv1_2:
                    if hasattr(pv1_2, "to_er7"):
                        code = pv1_2.to_er7()
                    else:
                        code = str(pv1_2)
                    enc_class = CodeableConcept.model_construct(
                        coding=[Coding(code=code)]
                    )

                # --------------------------------------------------------------
                # PV1-19: encounter id
                # --------------------------------------------------------------
                pv1_19 = getattr(pv1, "pv1_19", None)
                if pv1_19:
                    if hasattr(pv1_19, "to_er7"):
                        encounter_id = pv1_19.to_er7()
                    else:
                        encounter_id = str(pv1_19)

                # --------------------------------------------------------------
                # PV1-44/45: admit and discharge dates if present
                # --------------------------------------------------------------
                pv1_44 = getattr(pv1, "pv1_44", None)
                pv1_45 = getattr(pv1, "pv1_45", None)
                if pv1_44:
                    start = _parse_hl7_yyyymmdd(pv1_44)
                if pv1_45:
                    end = _parse_hl7_yyyymmdd(pv1_45)
        except Exception as e:
            LOG.error("Error parsing PV1: %s", e)

        if not encounter_id:
            encounter_id = f"enc-{(getattr(patient, 'id', None) or 'unknown')}"

        if enc_class is None:
            enc_class = CodeableConcept.model_construct(coding=[])

        return EncounterWithPeriod.model_construct(
            status="in-progress",
            class_fhir=enc_class,
            id=encounter_id,
            period=(
                Period.model_construct(start=start, end=end) if start or end else None
            ),
        )
