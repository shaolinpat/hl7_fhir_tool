# src/hl7_fhir_tool/transform/v2_to_fhir/adt_a03.py
from __future__ import annotations

from datetime import datetime
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

logger = logging.getLogger(__name__)


def _parse_hl7_ts(ts: str) -> Optional[str]:
    """Return YYYY-MM-DD string for FHIR period fields."""
    try:
        if len(ts) >= 8:
            dt = datetime.strptime(ts[:8], "%Y%m%d")
            return dt.date().isoformat()
    except Exception:
        pass
    return None


class EncounterWithPeriod(Encounter):
    """
    Subclass of Encounter that explicitly declares 'period' for static typing.
    """

    period: Optional[Period] = None


@register("ADT^A03")
class ADTA03Transformer:
    """
    Transformer for ADT^A03 messages (Discharge / End Encounter).

    Converts an HL7 v2 ADT^A03 message into a minimal set of FHIR resources:
    Patient and Encounter. Primarily intended as a conservative starting point;
    extend with robust PID/PV1 parsing as needed.

    Attributes
    ----------
    event : str
        HL7 event code handled by this transformer.
    """

    event: str = "ADT^A03"

    def applies(self, msg: Message) -> bool:
        """
        Determine whether this transformer applies to a given HL7 message.

        Parameters
        ----------
        msg : Message
            HL7 v2 message.

        Returns
        -------
        bool
            True if the message is an ADT^A03 event, False otherwise.

        Notes
        -----
        Safe against missing MSH.9; logs a warning if the message is malformed.
        """
        try:
            return str(msg.MSH.msh_9.to_er7()) == self.event
        except AttributeError as e:
            logger.warning("Failed to read MSH.9 from message: %s", e)
            return False

    def transform(self, msg: Message) -> List[Resource]:
        """
        Transform an HL7 ADT^A03 message into FHIR Patient and Encounter
        resources.

        Parameters
        ----------
        msg : Message
            HL7 v2 message to transform.

        Returns
        -------
        List[Resource]
            A list containing:
            - Patient resource (with minimal demographic info)
            - Encounter resource (status set to 'finished')

        Notes
        -----
        - Currently only maps patient name and optional patient ID from PID.
        - Encounter.status is set to 'finished' to reflect discharge.
        - Encounter.class, period.start/end, and encounter.id are populated if available.
        - Errors in parsing are logged but do not halt processing.
        """
        # Parse patient
        patient = Patient()
        pid = getattr(msg, "PID", None)
        if pid:
            try:
                # PID-5: Patient Name
                pid_name = getattr(pid, "pid_5", None)
                if pid_name and len(pid_name) > 0:
                    family_raw = getattr(pid_name[0], "family_name", None)
                    given_raw = getattr(pid_name[0], "given_name", None)

                    if family_raw is not None and hasattr(family_raw, "to_er7"):
                        family = family_raw.to_er7()
                    elif family_raw is not None:
                        family = str(family_raw)
                    else:
                        family = ""

                    if given_raw is not None and hasattr(given_raw, "to_er7"):
                        given = given_raw.to_er7()
                    elif given_raw is not None:
                        given = str(given_raw)
                    else:
                        given = ""

                    if family or given:
                        patient.name = [
                            HumanName(
                                family=family or None,
                                given=[given] if given else None,
                            )
                        ]

                # PID-3: Patient Identifier
                pid_id = getattr(pid, "pid_3", None)
                if pid_id and len(pid_id) > 0:
                    cx_1 = getattr(pid_id[0], "cx_1", None)
                    pid_val = None
                    if cx_1 and hasattr(cx_1, "to_er7"):
                        pid_val = cx_1.to_er7()
                    elif cx_1 is not None:
                        pid_val = str(cx_1)
                    if pid_val:
                        patient.id = pid_val
            except Exception as e:
                logger.error("Error parsing PID segment: %s", e)

        # Parse encounter
        enc_class: Optional[CodeableConcept] = None
        encounter_id = None
        start = None
        end = None
        pv1 = getattr(msg, "PV1", None)
        if pv1:
            try:
                # PV1-2: Encounter class
                pv1_2 = getattr(pv1, "pv1_2", None)
                if pv1_2:
                    code = pv1_2.to_er7() if hasattr(pv1_2, "to_er7") else str(pv1_2)
                    enc_class = CodeableConcept.model_construct(
                        coding=[Coding(code=code)]
                    )

                # PV1-19: Encounter ID
                pv1_19 = getattr(pv1, "pv1_19", None)
                if pv1_19:
                    encounter_id = (
                        pv1_19.to_er7() if hasattr(pv1_19, "to_er7") else str(pv1_19)
                    )

                # PV1-44/45: Admit / Discharge dates
                admit_ts = getattr(pv1, "pv1_44", None)
                discharge_ts = getattr(pv1, "pv1_45", None)
                if admit_ts:
                    val = (
                        admit_ts.to_er7()
                        if hasattr(admit_ts, "to_er7")
                        else str(admit_ts)
                    )
                    start = _parse_hl7_ts(val)
                if discharge_ts:
                    val = (
                        discharge_ts.to_er7()
                        if hasattr(discharge_ts, "to_er7")
                        else str(discharge_ts)
                    )
                    end = _parse_hl7_ts(val)
            except Exception as e:
                logger.error("Error parsing PV1 segment: %s", e)

        # Fallback for encounter ID
        if not encounter_id:
            encounter_id = f"enc-{getattr(patient, 'id', 'unknown')}"

        # Construct EncounterWithPeriod
        if enc_class is None:
            enc_class = CodeableConcept.model_construct(coding=[])

        encounter = EncounterWithPeriod.model_construct(
            status="finished",
            class_fhir=enc_class,
            id=encounter_id,
            period=(
                Period.model_construct(start=start, end=end) if start or end else None
            ),
        )

        return [patient, encounter]
