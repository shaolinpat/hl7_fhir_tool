#!/usr/bin/env python3
"""
Generate a bulk set of HL7 v2.5.1 messages for testing/demo.

Supported (registered) HL7 v2 -> FHIR events:
    ADT^A01
    ADT^A03
    ADT^A08
    ORM^O01
    ORU^R01

Features:
- Produces messages with MSH, EVN (for ADT), PID, PV1 and appropriate
  order/observation segments where applicable (ORC/OBR/OBX)
- ADT messages (A01, A03, A08) include a DG1 segment with a randomly selected
  ICD-10 code from a small built-in pool
- mixed_registered mode guarantees a cohort of diabetic patients: each cohort
  patient gets one ADT^A01 (E11.9) and one ORU^R01 (LOINC 4548-4, HbA1c > 8.0)
  sharing the same MRN, enabling the cohort SPARQL query to return results
- Rotates or fixes line endings: CR, LF, CRLF (HL7 expects CR)
- Deterministic output with --seed
- No external dependencies

Examples:
    # Legacy style: 1000 ADT^A01 messages into per-file bulk directory
    python scripts/generate_hl7_adt_a01_bulk.py \\
        --count 1000 \\
        --out tests/data/adt_a01_bulk

    # Generate 200 mixed registered messages plus a single stream file
    python scripts/generate_hl7_adt_a01_bulk.py \\
        --count 200 \\
        --out tests/data/hl7_bulk \\
        --message-type mixed_registered \\
        --stream-file tests/data/hl7_stream/registered_stream.hl7 \\
        --line-endings mix \\
        --seed 22
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 22

# Number of diabetic patients pre-generated for cohort linking in mixed mode.
# Each produces one ADT^A01 (E11.9) and one ORU^R01 (HbA1c > 8.0) with the
# same MRN, guaranteeing the cohort SPARQL query returns results.
_DIABETIC_COHORT_SIZE = 10

NAMES_GIVEN = [
    "John",
    "Jane",
    "Alex",
    "Sam",
    "Chris",
    "Taylor",
    "Jordan",
    "Morgan",
    "Patrick",
    "Casey Joan",
    "Avery",
    "Riley",
    "Quinn",
    "Bailey",
    "Cameron",
    "Drew",
    "Elliot",
    "Harper",
    "Jamie",
    "Kai",
]

NAMES_FAMILY = [
    "Doe",
    "Smith",
    "Johnson",
    "Lee",
    "Brown",
    "Davis",
    "Miller-Thompson",
    "Wilson",
    "Moore",
    "Taylor",
    "Anderson",
    "Thomas",
    "Jackson",
    "White",
    "Harris",
    "Martin",
    "Thompson",
    "Garcia",
    "Martinez",
    "Tran",
]

STREETS = [
    "Main St",
    "Oak St",
    "Pine Ave",
    "Maple Rd",
    "Cedar Blvd",
    "Elm St",
    "Birch Ln",
    "White Feather Ct",
]

CITIES = [
    "Cincinnati",
    "Boston",
    "Denver",
    "Austin",
    "Seattle",
    "Portland",
    "Chicago",
    "Phoenix",
    "Atlanta",
    "Raleigh",
]

STATES = ["OH", "MA", "CO", "TX", "WA", "OR", "IL", "AZ", "GA", "NC"]

SEX_CODES = ["M", "F", "O", "U"]  # Male/Female/Other/Unknown

# Small ICD-10 pool for synthetic DG1 segments.
# Format: (code, description, coding_system)
_ICD10_POOL = [
    ("E11.9", "Type 2 diabetes mellitus without complications", "I10"),
    ("I10", "Essential (primary) hypertension", "I10"),
    ("J44.1", "COPD with acute exacerbation", "I10"),
    ("N18.3", "Chronic kidney disease stage 3", "I10"),
    ("F32.1", "Major depressive disorder single episode moderate", "I10"),
    ("Z87.891", "Personal history of nicotine dependence", "I10"),
    ("M54.5", "Low back pain", "I10"),
    (
        "I25.10",
        "Atherosclerotic heart disease of native coronary artery without angina",
        "I10",
    ),
]


def _rand_phone(rng: random.Random) -> str:
    """
    Naive NANP-ish 10-digit phone number.
    """
    return (
        f"{rng.randint(200, 999)}"
        f"{rng.randint(200, 999):03d}"
        f"{rng.randint(0, 9999):04d}"
    )


def _rand_dob(rng: random.Random, start_year: int = 1930, end_year: int = 2020) -> str:
    """
    Random date of birth between start_year-01-01 and end_year-12-31 (YYYYMMDD).
    """
    y = rng.randint(start_year, end_year)
    m = rng.randint(1, 12)
    d = rng.randint(1, 28)
    return f"{y:04d}{m:02d}{d:02d}"


def _ts(dt: datetime) -> str:
    """
    HL7 TS format: YYYYMMDDHHMMSS.
    """
    return dt.strftime("%Y%m%d%H%M%S")


def _base_demographics(rng: random.Random) -> dict:
    """
    Generate a bundle of basic demographic fields shared across message types.
    """
    family = rng.choice(NAMES_FAMILY)
    given = rng.choice(NAMES_GIVEN)
    sex = rng.choice(SEX_CODES)
    dob = _rand_dob(rng)
    mrn = f"{rng.randint(10_000, 999_999)}"

    street = f"{rng.randint(1, 9999)} {rng.choice(STREETS)}"
    city = rng.choice(CITIES)
    state = rng.choice(STATES)
    zipc = f"{rng.randint(10000, 99999)}"
    phone = _rand_phone(rng)

    return {
        "family": family,
        "given": given,
        "sex": sex,
        "dob": dob,
        "mrn": mrn,
        "street": street,
        "city": city,
        "state": state,
        "zipc": zipc,
        "phone": phone,
    }


def _make_common_segments(
    msg_ts: str,
    msg_cntrl: str,
    ver: str,
    evn_code: str,
    demo: dict,
) -> tuple[str, str, str, str]:
    """
    Build MSH, EVN, PID, PV1 segments common to ADT-style messages.
    """
    family = demo["family"]
    given = demo["given"]
    sex = demo["sex"]
    dob = demo["dob"]
    mrn = demo["mrn"]
    street = demo["street"]
    city = demo["city"]
    state = demo["state"]
    zipc = demo["zipc"]
    phone = demo["phone"]

    # MSH-9 is left to specific message builders (ADT^A01, etc.)
    msh_prefix = f"MSH|^~\\&|HIS|RIH|EKG|EKG|{msg_ts}||"

    # EVN with event code and timestamp
    evn = f"EVN|{evn_code}|{msg_ts}"
    pid = (
        "PID|1||"
        + f"{mrn}^^^MRN"
        + "||"
        + f"{family}^{given}^^^^^L"
        + "||"
        + f"{dob}"
        + "|"
        + f"{sex}"
        + "|||"
        + f"{street}^^{city}^{state}^{zipc}"
        + "||"
        + f"{phone}"
    )
    pv1 = "PV1|1|I|2000^2012^01||||1234^Physician^Primary"

    return msh_prefix, evn, pid, pv1


def _make_pid_segment(demo: dict) -> str:
    """
    Build a standalone PID segment from a demographics dict.

    Used by non-ADT message builders (ORM, ORU) that do not use
    _make_common_segments.

    Parameters
    ----------
    demo : dict
        Demographics dict as produced by _base_demographics.

    Returns
    -------
    str
        PID segment string.
    """
    return (
        "PID|1||"
        + f"{demo['mrn']}^^^MRN"
        + "||"
        + f"{demo['family']}^{demo['given']}^^^^^L"
        + "||"
        + f"{demo['dob']}"
        + "|"
        + f"{demo['sex']}"
        + "|||"
        + f"{demo['street']}^^{demo['city']}^{demo['state']}^{demo['zipc']}"
        + "||"
        + f"{demo['phone']}"
    )


def _make_adt_a01_message(rng: random.Random, idx: int, base_dt: datetime) -> str:
    """
    Construct a synthetic ADT^A01 admit message with a DG1 segment.
    """
    dt = base_dt + timedelta(minutes=idx)
    msg_ts = _ts(dt)
    msg_cntrl = f"MSG{idx:06d}"
    ver = "2.5.1"

    demo = _base_demographics(rng)
    msh_prefix, evn, pid, pv1 = _make_common_segments(
        msg_ts=msg_ts,
        msg_cntrl=msg_cntrl,
        ver=ver,
        evn_code="A01",
        demo=demo,
    )
    msh = f"{msh_prefix}ADT^A01|{msg_cntrl}|P|{ver}"
    code, desc, sys = rng.choice(_ICD10_POOL)
    dg1 = f"DG1|1||{code}^{desc}^{sys}"
    return "\n".join([msh, evn, pid, pv1, dg1])


def _make_adt_a01_e119_message(
    rng: random.Random, idx: int, base_dt: datetime, demo: dict
) -> str:
    """
    Construct an ADT^A01 admit message for a known diabetic patient.

    Forces DG1 to E11.9 (Type 2 diabetes mellitus without complications) and
    uses the provided demo dict so that the MRN matches a paired ORU^R01
    HbA1c result message, enabling the cohort SPARQL query to return results.

    Parameters
    ----------
    rng : random.Random
        Not used for demographics; included for interface consistency.
    idx : int
        Message index for timestamp offset and control number.
    base_dt : datetime
        Base datetime for message timestamps.
    demo : dict
        Pre-generated demographics dict shared with a paired ORU^R01 message.

    Returns
    -------
    str
        HL7 message text with LF line endings.
    """
    dt = base_dt + timedelta(minutes=idx)
    msg_ts = _ts(dt)
    msg_cntrl = f"MSG{idx:06d}"
    ver = "2.5.1"

    msh_prefix, evn, pid, pv1 = _make_common_segments(
        msg_ts=msg_ts,
        msg_cntrl=msg_cntrl,
        ver=ver,
        evn_code="A01",
        demo=demo,
    )
    msh = f"{msh_prefix}ADT^A01|{msg_cntrl}|P|{ver}"
    dg1 = "DG1|1||E11.9^Type 2 diabetes mellitus without complications^I10"
    return "\n".join([msh, evn, pid, pv1, dg1])


def _make_adt_a03_message(rng: random.Random, idx: int, base_dt: datetime) -> str:
    """
    Construct a synthetic ADT^A03 discharge message with a DG1 segment.
    """
    dt = base_dt + timedelta(minutes=idx)
    msg_ts = _ts(dt)
    msg_cntrl = f"MSG{idx:06d}"
    ver = "2.5.1"

    demo = _base_demographics(rng)
    msh_prefix, evn, pid, pv1 = _make_common_segments(
        msg_ts=msg_ts,
        msg_cntrl=msg_cntrl,
        ver=ver,
        evn_code="A03",
        demo=demo,
    )
    msh = f"{msh_prefix}ADT^A03|{msg_cntrl}|P|{ver}"
    code, desc, sys = rng.choice(_ICD10_POOL)
    dg1 = f"DG1|1||{code}^{desc}^{sys}"
    return "\n".join([msh, evn, pid, pv1, dg1])


def _make_adt_a08_message(rng: random.Random, idx: int, base_dt: datetime) -> str:
    """
    Construct a synthetic ADT^A08 update-patient-information message with a DG1
    segment.
    """
    dt = base_dt + timedelta(minutes=idx)
    msg_ts = _ts(dt)
    msg_cntrl = f"MSG{idx:06d}"
    ver = "2.5.1"

    demo = _base_demographics(rng)
    msh_prefix, evn, pid, pv1 = _make_common_segments(
        msg_ts=msg_ts,
        msg_cntrl=msg_cntrl,
        ver=ver,
        evn_code="A08",
        demo=demo,
    )
    msh = f"{msh_prefix}ADT^A08|{msg_cntrl}|P|{ver}"
    code, desc, sys = rng.choice(_ICD10_POOL)
    dg1 = f"DG1|1||{code}^{desc}^{sys}"
    return "\n".join([msh, evn, pid, pv1, dg1])


def _make_orm_o01_message(rng: random.Random, idx: int, base_dt: datetime) -> str:
    """
    Construct a synthetic ORM^O01 order message.

    Includes:
        MSH, PID, PV1, ORC, OBR
    """
    dt = base_dt + timedelta(minutes=idx)
    msg_ts = _ts(dt)
    msg_cntrl = f"MSG{idx:06d}"
    ver = "2.5.1"

    demo = _base_demographics(rng)
    pid = _make_pid_segment(demo)
    pv1 = "PV1|1|O|OPD^01^01||||1234^Physician^Ordering"

    msh = f"MSH|^~\\&|HIS|RIH|LIS|LIS|{msg_ts}||ORM^O01|{msg_cntrl}|P|{ver}"

    order_id = f"ORD{rng.randint(10000, 99999)}"
    filler_id = f"FILL{rng.randint(10000, 99999)}"

    # Simple ORC: new order
    orc = f"ORC|NW|{order_id}||{filler_id}|||^^^|{msg_ts}||||1234^Physician^Ordering"

    # Simple OBR: basic chemistry panel (example LOINC)
    loinc_code = "24321-2"
    loinc_text = "Basic metabolic 2000 panel"
    obr = (
        "OBR|1|"
        + f"{order_id}"
        + "|"
        + f"{filler_id}"
        + "|"
        + f"{loinc_code}^{loinc_text}^LN"
    )

    return "\n".join([msh, pid, pv1, orc, obr])


def _make_oru_r01_message(rng: random.Random, idx: int, base_dt: datetime) -> str:
    """
    Construct a synthetic ORU^R01 lab result message.

    Includes:
        MSH, PID, PV1, OBR, OBX
    """
    dt = base_dt + timedelta(minutes=idx)
    msg_ts = _ts(dt)
    msg_cntrl = f"MSG{idx:06d}"
    ver = "2.5.1"

    demo = _base_demographics(rng)
    pid = _make_pid_segment(demo)
    pv1 = "PV1|1|O|OPD^01^01||||1234^Physician^Ordering"

    msh = f"MSH|^~\\&|HIS|RIH|LIS|LIS|{msg_ts}||ORU^R01|{msg_cntrl}|P|{ver}"

    # Simple lab: serum sodium, LOINC 2951-2, units mmol/L
    loinc_code = "2951-2"
    loinc_text = "Sodium [Moles/volume] in Serum or Plasma"
    value = rng.uniform(120.0, 150.0)
    units = "mmol/L"

    placer_order_num = f"ORD{rng.randint(10000, 99999)}"
    filler_order_num = f"LAB{rng.randint(10000, 99999)}"

    obr = (
        "OBR|1|"
        + f"{placer_order_num}"
        + "|"
        + f"{filler_order_num}"
        + "|"
        + f"{loinc_code}^{loinc_text}^LN"
    )
    obx = (
        "OBX|1|NM|"
        + f"{loinc_code}^{loinc_text}^LN"
        + "|"
        + "|"
        + f"{value:.2f}"
        + "|"
        + f"{units}"
    )

    return "\n".join([msh, pid, pv1, obr, obx])


def _make_oru_r01_hba1c_message(
    rng: random.Random, idx: int, base_dt: datetime, demo: dict
) -> str:
    """
    Construct an ORU^R01 HbA1c result message for a known diabetic patient.

    Uses LOINC 4548-4 (Hemoglobin A1c/Hemoglobin.total in Blood) with a value
    in the range 8.1-12.0, guaranteeing the result exceeds the 8.0 threshold
    used by the cohort SPARQL query. Uses the provided demo dict so that the
    MRN matches a paired ADT^A01 E11.9 admission message.

    Parameters
    ----------
    rng : random.Random
        Random number generator for value and order numbers.
    idx : int
        Message index for timestamp offset and control number.
    base_dt : datetime
        Base datetime for message timestamps.
    demo : dict
        Pre-generated demographics dict shared with a paired ADT^A01 message.

    Returns
    -------
    str
        HL7 message text with LF line endings.
    """
    dt = base_dt + timedelta(minutes=idx)
    msg_ts = _ts(dt)
    msg_cntrl = f"MSG{idx:06d}"
    ver = "2.5.1"

    pid = _make_pid_segment(demo)
    pv1 = "PV1|1|O|OPD^01^01||||1234^Physician^Ordering"

    msh = f"MSH|^~\\&|HIS|RIH|LIS|LIS|{msg_ts}||ORU^R01|{msg_cntrl}|P|{ver}"

    loinc_code = "4548-4"
    loinc_text = "Hemoglobin A1c/Hemoglobin.total in Blood"
    # Value guaranteed > 8.0 to satisfy the cohort query FILTER.
    value = rng.uniform(8.1, 12.0)
    units = "%"

    placer_order_num = f"ORD{rng.randint(10000, 99999)}"
    filler_order_num = f"LAB{rng.randint(10000, 99999)}"

    obr = (
        "OBR|1|"
        + f"{placer_order_num}"
        + "|"
        + f"{filler_order_num}"
        + "|"
        + f"{loinc_code}^{loinc_text}^LN"
    )
    obx = (
        "OBX|1|NM|"
        + f"{loinc_code}^{loinc_text}^LN"
        + "|"
        + "|"
        + f"{value:.1f}"
        + "|"
        + f"{units}"
    )

    return "\n".join([msh, pid, pv1, obr, obx])


def _apply_line_endings(text: str, mode: str, idx: int) -> bytes:
    """
    HL7 expects \\r (CR). Provide flexibility:
        - 'cr'   => \\r
        - 'lf'   => \\n
        - 'crlf' => \\r\\n
        - 'mix'  => cycles [CR, LF, CRLF] by index
    """
    mode = mode.lower()
    if mode == "mix":
        choices = ["cr", "lf", "crlf"]
        mode = choices[idx % 3]
    if mode == "cr":
        sep = "\r"
    elif mode == "lf":
        sep = "\n"
    elif mode == "crlf":
        sep = "\r\n"
    else:
        raise ValueError("line endings must be one of: cr|lf|crlf|mix")
    return (sep.join(text.splitlines()) + sep).encode("utf-8")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Generate bulk HL7 v2.5.1 messages.")
    ap.add_argument(
        "--count",
        type=int,
        default=1000,
        help="How many messages to generate (default 1000).",
    )
    ap.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Destination directory for per-message files.",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help="Random seed for reproducible output (default 22).",
    )
    ap.add_argument(
        "--line-endings",
        choices=["cr", "lf", "crlf", "mix"],
        default="mix",
        help="Segment delimiters. HL7 expects CR; 'mix' cycles CR, LF, CRLF (default).",
    )
    ap.add_argument(
        "--message-type",
        choices=[
            "adt_a01",
            "adt_a03",
            "adt_a08",
            "orm_o01",
            "oru_r01",
            "mixed_registered",
        ],
        default="adt_a01",
        help=(
            "Type of messages to generate. "
            "'mixed_registered' randomly mixes all registered types and "
            "guarantees a diabetic cohort (E11.9 + HbA1c > 8.0) for SPARQL "
            "cohort query testing. Default: adt_a01."
        ),
    )
    ap.add_argument(
        "--stream-file",
        type=Path,
        default=None,
        help=(
            "Optional path to a single HL7 stream file. "
            "If provided, all generated messages are also appended "
            "to this file in order."
        ),
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    rng = random.Random(args.seed)
    outdir: Path = args.out
    outdir.mkdir(parents=True, exist_ok=True)

    base_dt = datetime(2025, 1, 1, 12, 0, 0)

    # Pre-generate diabetic patient demographics for cohort linking in
    # mixed_registered mode. Each patient gets one ADT^A01 (E11.9) and one
    # ORU^R01 (HbA1c > 8.0) sharing the same MRN, guaranteeing cohort query
    # results regardless of total message count.
    diabetic_demos = [_base_demographics(rng) for _ in range(_DIABETIC_COHORT_SIZE)]

    def gen_message(i: int) -> str:
        """
        Generate a single message for index i.

        In mixed_registered mode, the first 2 * _DIABETIC_COHORT_SIZE slots
        are reserved for the diabetic cohort: odd slots (1, 3, 5...) produce
        ADT^A01 (E11.9) messages, even slots (2, 4, 6...) produce ORU^R01
        (HbA1c) messages, both using the same pre-generated demographics.
        Remaining slots produce randomly mixed messages.

        Parameters
        ----------
        i : int
            1-based message index.

        Returns
        -------
        str
            HL7 message text with LF line endings.
        """
        if args.message_type == "adt_a01":
            return _make_adt_a01_message(rng, i, base_dt)
        if args.message_type == "adt_a03":
            return _make_adt_a03_message(rng, i, base_dt)
        if args.message_type == "adt_a08":
            return _make_adt_a08_message(rng, i, base_dt)
        if args.message_type == "orm_o01":
            return _make_orm_o01_message(rng, i, base_dt)
        if args.message_type == "oru_r01":
            return _make_oru_r01_message(rng, i, base_dt)

        # mixed_registered: first 2 * _DIABETIC_COHORT_SIZE slots are cohort pairs.
        cohort_slots = 2 * _DIABETIC_COHORT_SIZE
        if i <= cohort_slots:
            cohort_idx = (i - 1) // 2
            demo = diabetic_demos[cohort_idx]
            if i % 2 == 1:
                # Odd slot: ADT^A01 with E11.9
                return _make_adt_a01_e119_message(rng, i, base_dt, demo)
            else:
                # Even slot: ORU^R01 with HbA1c > 8.0
                return _make_oru_r01_hba1c_message(rng, i, base_dt, demo)

        # Remaining slots: random mix of all registered types
        choice = rng.choice(["adt_a01", "adt_a03", "adt_a08", "orm_o01", "oru_r01"])
        if choice == "adt_a01":
            return _make_adt_a01_message(rng, i, base_dt)
        if choice == "adt_a03":
            return _make_adt_a03_message(rng, i, base_dt)
        if choice == "adt_a08":
            return _make_adt_a08_message(rng, i, base_dt)
        if choice == "orm_o01":
            return _make_orm_o01_message(rng, i, base_dt)
        return _make_oru_r01_message(rng, i, base_dt)

    stream_fp = None
    if args.stream_file is not None:
        args.stream_file.parent.mkdir(parents=True, exist_ok=True)
        # Open once in binary mode; reuse _apply_line_endings output directly.
        stream_fp = args.stream_file.open("wb")

    try:
        for i in range(1, args.count + 1):
            msg = gen_message(i)
            payload = _apply_line_endings(msg, args.line_endings, i)

            # Per-message bulk files with stable, sortable names
            p = outdir / f"msg_{i:04d}.hl7"
            p.write_bytes(payload)

            # Optional stream file: append this message, then an extra separator
            if stream_fp is not None:
                stream_fp.write(payload)
                # Add an extra newline as a message separator for convenience
                stream_fp.write(b"\n")
    finally:
        if stream_fp is not None:
            stream_fp.close()

    print(f"Generated {args.count} messages in {outdir}")
    if args.stream_file is not None:
        print(f"Also wrote stream file: {args.stream_file}")


if __name__ == "__main__":
    main()
