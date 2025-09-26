#!/usr/bin/env python3
"""
Generate a bulk set of HL7 v2.5.1 ADT^A01 messages for testing/demo.

- Produces ADT^A01 with MSH, EVN, PID, PV1 (minimal but realistic)
- Rotates or fixes line endings: CR, LF, CRLF (HL7 expects CR)
- Deterministic outpout with --seed
- No external dependencies

Usage:
    python scripts/generate_hl7_adt_a01_bulk.py --count 1000 --out tests/data/adt_a01_bulk --line-endings mix
"""


from __future__ import annotations
import argparse
import random
from pathlib import Path
from datetime import datetime, timedelta

SEED = 22

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


def _rand_phone(rng: random.Random) -> str:
    rng.seed(SEED)

    # naive NANP-ish 10-digit
    return (
        f"{rng.randint(200,999)}{rng.randint(200,999):03d}{rng.randint(0000,9999):04d}"
    )


def _rand_dob(rng: random.Random, start_year=1930, end_year=2020) -> str:
    rng.seed(SEED)
    y = rng.randint(start_year, end_year)
    m = rng.randint(1, 12)
    # keep it simple on days
    d = rng.randint(1, 28)
    return f"{y:04d}{m:02d}{d:02d}"


def _ts(dt: datetime) -> str:
    # HL7 TS: YYYYMMDDHHMMSS
    return dt.strftime("%Y%m%d%H%M%S")


def _make_msg(rng: random.Random, idx: int, base_dt: datetime) -> str:
    rng.seed(SEED)
    dt = base_dt + timedelta(minutes=idx)
    msg_ts = _ts(dt)
    msg_cntrl = f"MSG{idx:06d}"
    ver = "2.5.1"

    family = rng.choice(NAMES_FAMILY)
    given = rng.choice(NAMES_GIVEN)
    sex = rng.choice(SEX_CODES)
    dob = _rand_dob(rng)
    mrn = f"{rng.randint(10_000, 999_999)}"

    street = f"{rng.randint(1,9999)} {rng.choice(STREETS)}"
    city = rng.choice(CITIES)
    state = rng.choice(STATES)
    zipc = f"{rng.randint(10000, 99999)}"
    phone = _rand_phone(rng)

    # Very small PV1 with basic fields; status defaults in your transformer anyway
    # Field separators: | ^ ~ \ &
    # PID-5 uses extended person name, family^given^^^^^L (legal)
    msh = f"MSH|^~\\&|HIS|RIH|EKG|EKG|{msg_ts}||ADT^A01|{msg_cntrl}|P|{ver}"
    evn = f"EVN|A01|{msg_ts}"
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

    return "\n".join([msh, evn, pid, pv1])


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
    return sep.join(text.splitlines()).encode("utf-8")


def main():
    ap = argparse.ArgumentParser(
        description="Generate bulk HL7 v2.5.1 ADT^A01 messages."
    )
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
        help="Destination directory (e.g., tests/data/adt_a01_bulk).",
    )
    ap.add_argument(
        "--seed", type=int, default=22, help="Random seed for reproducible output."
    )
    ap.add_argument(
        "--line-endings",
        choices=["cr", "lf", "crlf", "mix"],
        default="mix",
        help="Segment delimiters. HL7 expects CR; 'mix' cycles CR, LF, CRLF (default).",
    )
    args = ap.parse_args()

    rng = random.Random(args.seed)
    outdir: Path = args.out
    outdir.mkdir(parents=True, exist_ok=True)

    base_dt = datetime(2025, 1, 1, 12, 0, 0)

    for i in range(1, args.count + 1):
        msg = _make_msg(rng, i, base_dt)
        payload = _apply_line_endings(msg, args.line_endings, i)
        # Stable, sortable names
        p = outdir / f"adt_a01_{i:04d}.hl7"
        p.write_bytes(payload)

    print(f"Generated {args.count} messages in {outdir}")


if __name__ == "__main__":
    main()
