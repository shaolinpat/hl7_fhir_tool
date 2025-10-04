# tests/test_adt_a08.py
from __future__ import annotations

from types import SimpleNamespace

from fhir.resources.patient import Patient
from hl7apy.parser import parse_message

from hl7_fhir_tool.transform.v2_to_fhir.adt_a08 import (
    ADTA08Transformer,
    _parse_hl7_yyyymmdd,
)


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _msh(mshtype: str) -> str:
    return (
        "MSH|^~\\&|SRC_APP|SRC_FAC|DST_APP|DST_FAC|20250101123000||"
        + mshtype
        + "|MSG123|P|2.5"
    )


def _pid(mrn: str, family: str, given: str, dob_yyyymmdd: str, sex: str) -> str:
    return f"PID|1||{mrn}^^^HOSP^MR||{family}^{given}||{dob_yyyymmdd}|{sex}|"


def _pv1_with(fields: dict) -> str:
    """
    Build a PV1 with realistic field count, filling selected fields.

    Keys you can pass:
        2: class (I, O, E)
        19: visit number
        44: admit date YYYYMMDD
        45: discharge date YYYYMMDD
    """
    total = 45
    arr = [""] * (total + 1)  # 1-based indexing
    for idx, val in fields.items():
        if 1 <= idx <= total:
            arr[idx] = val
    if not arr[1]:
        arr[1] = "1"  # PV1-1 set id
    body = "|".join(arr[1:])
    return "PV1|" + body


def _mk_msg(mshtype: str, pid: str = "", pv1: str = ""):
    parts = [_msh(mshtype)]
    if pid:
        parts.append(pid)
    if pv1:
        parts.append(pv1)
    return parse_message("\r".join(parts))


# ------------------------------------------------------------------------------
# applies
# ------------------------------------------------------------------------------


def test_applies_true_and_false():
    xf = ADTA08Transformer()
    assert xf.applies(_mk_msg("ADT^A08")) is True
    assert xf.applies(_mk_msg("ADT^A03")) is False

    # Valid message, then clear MSH-9 to simulate missing trigger
    msg = _mk_msg("ADT^A08")
    cleared = False
    try:
        msg.MSH.msh_9 = ""
        cleared = True
    except Exception:
        pass
    if not cleared:
        try:
            delattr(msg.MSH, "msh_9")
            cleared = True
        except Exception:
            pass
    if not cleared:
        try:
            setattr(msg.MSH, "msh_9", None)
            cleared = True
        except Exception:
            pass
    assert xf.applies(msg) is False


def test_applies_logs_on_exception():
    class BrokenMSH:
        def __getattr__(self, name):
            if name == "msh_9":
                raise AttributeError("boom")
            return None

    msg = SimpleNamespace(MSH=BrokenMSH())
    xf = ADTA08Transformer()
    assert xf.applies(msg) is False


# ------------------------------------------------------------------------------
# transform
# ------------------------------------------------------------------------------


def test_transform_minimal():
    xf = ADTA08Transformer()
    pid = _pid("12345", "Doe", "Jane", "19800101", "F")
    pv1 = _pv1_with({2: "I"})
    msg = _mk_msg("ADT^A08", pid=pid, pv1=pv1)

    patient, encounter = xf.transform(msg)

    assert getattr(patient, "id", None) == "12345"
    assert patient.name and patient.name[0].family == "Doe"
    assert patient.name[0].given == ["Jane"]
    assert str(patient.birthDate) == "1980-01-01"
    assert patient.gender == "female"
    assert encounter.status == "in-progress"
    assert encounter.class_fhir.coding and encounter.class_fhir.coding[0].code == "I"
    assert encounter.id == "enc-12345"
    assert getattr(encounter, "period", None) is None


def test_transform_with_visit_and_period():
    xf = ADTA08Transformer()
    pid = _pid("77777", "Alpha", "Test", "19900101", "M")
    pv1 = _pv1_with({2: "O", 19: "V999", 44: "20250101", 45: "20250102"})
    msg = _mk_msg("ADT^A08", pid=pid, pv1=pv1)

    patient, encounter = xf.transform(msg)

    assert getattr(patient, "id", None) == "77777"
    assert str(patient.birthDate) == "1990-01-01"
    assert patient.gender == "male"
    assert encounter.id == "V999"
    assert encounter.status == "in-progress"
    assert encounter.class_fhir.coding[0].code == "O"
    assert encounter.period.start == "2025-01-01"
    assert encounter.period.end == "2025-01-02"


def test_transform_missing_pid_is_tolerant():
    xf = ADTA08Transformer()
    pv1 = _pv1_with({2: "E"})
    msg = _mk_msg("ADT^A08", pid="", pv1=pv1)

    patient, encounter = xf.transform(msg)

    assert getattr(patient, "id", None) is None
    assert encounter.id == "enc-unknown"
    assert encounter.status == "in-progress"
    assert encounter.class_fhir.coding and encounter.class_fhir.coding[0].code == "E"


def test_transform_gender_unknown_mapping():
    xf = ADTA08Transformer()
    pid = _pid("99999", "Smith", "Alex", "19751231", "U")
    pv1 = _pv1_with({2: "I"})
    msg = _mk_msg("ADT^A08", pid=pid, pv1=pv1)

    patient, encounter = xf.transform(msg)

    assert patient.gender == "unknown"
    assert encounter.status == "in-progress"


def test_transform_bad_birthdate_not_set():
    xf = ADTA08Transformer()
    pid = _pid("44444", "Dob", "Bad", "1990", "U")
    msg = _mk_msg("ADT^A08", pid=pid, pv1=_pv1_with({2: "E"}))

    patient, _ = xf.transform(msg)

    assert getattr(patient, "birthDate", None) in (None, "")


def test_transform_pid3_present_but_empty_id_keeps_patient_id_none():
    xf = ADTA08Transformer()
    pid = "PID|1||^HOSP^MR||Doe^OnlyFam||19700101|M|"
    msg = _mk_msg("ADT^A08", pid=pid, pv1=_pv1_with({2: "I"}))

    patient, encounter = xf.transform(msg)

    assert getattr(patient, "id", None) is None
    assert encounter.id == "enc-unknown"


def test_transform_pid3_cx1_is_none_skips_block():
    class PID:
        pid_3 = [SimpleNamespace(cx_1=None)]
        pid_5 = []
        pid_7 = None
        pid_8 = None

    xf = ADTA08Transformer()
    p = xf._build_patient(PID())

    assert isinstance(p, Patient)


def test_transform_pid5_name_and_pid7_birthdate_to_er7_paths():
    class NameComp:
        def __init__(self, fam, giv):
            self.family_name = fam
            self.given_name = giv

    class Fam:
        def to_er7(self):
            return "Family"

    class Giv:
        def to_er7(self):
            return "Given"

    class PID7:
        def to_er7(self):
            return "19850706"

    class PID:
        pid_3 = []
        pid_5 = [NameComp(Fam(), Giv())]
        pid_7 = PID7()
        pid_8 = None

    xf = ADTA08Transformer()
    p = xf._build_patient(PID())

    assert p.name and p.name[0].family == "Family"
    assert p.name[0].given == ["Given"]
    assert str(p.birthDate) == "1985-07-06"


def test_transform_pid3_sets_id_via_str_not_to_er7():
    class CX1NoToEr7:
        def __str__(self):
            return "STR123"

    class PID:
        pid_3 = [SimpleNamespace(cx_1=CX1NoToEr7())]
        pid_5 = []
        pid_7 = None
        pid_8 = None

    xf = ADTA08Transformer()
    p = xf._build_patient(PID())

    assert getattr(p, "id", None) == "STR123"


def test_transform_pv1_class_and_id_via_plain_strings_not_to_er7():
    class PV1Plain:
        pv1_2 = "O"
        pv1_19 = "VPLAIN"
        pv1_44 = None
        pv1_45 = None

    xf = ADTA08Transformer()
    patient = Patient()
    patient.id = "X9"
    enc = xf._build_encounter(PV1Plain(), patient)

    assert enc.class_fhir.coding and enc.class_fhir.coding[0].code == "O"
    assert enc.id == "VPLAIN"


def test_transform_pv1_fields_present_but_empty_strings():
    class PV1Empty:
        pv1_2 = ""
        pv1_19 = ""
        pv1_44 = None
        pv1_45 = None

    xf = ADTA08Transformer()
    patient = Patient()
    patient.id = "E1"
    enc = xf._build_encounter(PV1Empty(), patient)

    assert enc.class_fhir.coding == []
    assert enc.id == "enc-E1"


def test_transform_no_pv1_sets_empty_class_and_fallback_id():
    xf = ADTA08Transformer()
    pid = _pid("55555", "NoPv1", "Case", "19700101", "M")
    msg = _mk_msg("ADT^A08", pid=pid, pv1="")

    _, encounter = xf.transform(msg)

    assert encounter.id == "enc-55555"
    assert encounter.class_fhir.coding == []


def test_transform_pid_parsing_error_path_logs_and_recovers():
    class ExplodeOnGetattr:
        def __getattr__(self, name):
            raise RuntimeError("pid boom")

    xf = ADTA08Transformer()
    p = xf._build_patient(ExplodeOnGetattr())

    assert isinstance(p, Patient)
    assert getattr(p, "id", None) is None


def test_transform_pv1_parsing_error_path_logs_and_recovers():
    class ExplodeOnToEr7:
        def __getattr__(self, name):
            class X:
                def to_er7(self_inner):
                    raise ValueError("pv1 boom")

            return X()

    xf = ADTA08Transformer()
    patient = Patient()
    patient.id = "ZZZ"
    enc = xf._build_encounter(ExplodeOnToEr7(), patient)

    assert enc.id == "enc-ZZZ"
    assert enc.class_fhir is not None


def test_transform_pid8_gender_block_raises_then_recovers():
    class PIDFake:
        pid_3 = []

        class NameComp:
            def __init__(self):
                self.family_name = None
                self.given_name = None

        pid_5 = [NameComp()]
        pid_7 = None

        class Boom:
            def to_er7(self):
                raise RuntimeError("gender to_er7 blew up")

        pid_8 = Boom()

    xf = ADTA08Transformer()
    p = xf._build_patient(PIDFake())

    assert isinstance(p, Patient)
    assert p.gender == "unknown"


def test_transform_pid3_to_er7_raises_is_caught_and_id_not_set():
    class CX1Boom:
        def to_er7(self):
            raise RuntimeError("kapow")

    class PID:
        pid_3 = [SimpleNamespace(cx_1=CX1Boom())]
        pid_5 = []
        pid_7 = None
        pid_8 = None

    xf = ADTA08Transformer()
    p = xf._build_patient(PID())

    assert getattr(p, "id", None) in (None, "")


def test_transform_pid3_setting_id_raises_and_is_caught_invalid_fhir_id():
    class CX1BadId:
        def to_er7(self):
            return "BAD_ID_UNDERSCORE"  # underscore invalid per FHIR id pattern

    class PID:
        pid_3 = [SimpleNamespace(cx_1=CX1BadId())]
        pid_5 = []
        pid_7 = None
        pid_8 = None

    xf = ADTA08Transformer()
    p = xf._build_patient(PID())

    assert getattr(p, "id", None) in (None, "")


def test_transform_pid5_only_family_sets_family_not_given():
    raw = (
        "MSH|^~\\&|SRC_APP|SRC_FAC|DST_APP|DST_FAC|20250101123000||ADT^A08|MSGFAM1|P|2.5\r"
        "PID|1||FAM001^^^HOSP^MR||SoloFam^||19850706|F|\r"
        "PV1|1|O|||||||||||||||||||||||||||||||||||||||||\r"
    )
    msg = parse_message(raw)
    xf = ADTA08Transformer()
    patient, _ = xf.transform(msg)

    assert patient.name and patient.name[0].family == "SoloFam"
    assert patient.name[0].given in (None, [], [""])


def test_transform_pid5_only_given_sets_given_not_family():
    raw = (
        "MSH|^~\\&|SRC_APP|SRC_FAC|DST_APP|DST_FAC|20250101123000||ADT^A08|MSGGIV1|P|2.5\r"
        "PID|1||GIV001^^^HOSP^MR||^OnlyGiven||19990101|M|\r"
        "PV1|1|I|||||||||||||||||||||||||||||||||||||||||\r"
    )
    msg = parse_message(raw)
    xf = ADTA08Transformer()
    patient, _ = xf.transform(msg)

    assert patient.name and patient.name[0].family in (None, "")
    assert patient.name[0].given == ["OnlyGiven"]


def test_transform_pid5_family_and_given_fall_back_to_str_paths():
    class FamNoTo:
        def __str__(self):  # no to_er7()
            return "StrFamily"

    class GivNoTo:
        def __str__(self):  # no to_er7()
            return "StrGiven"

    class NameComp:
        def __init__(self):
            self.family_name = FamNoTo()
            self.given_name = GivNoTo()

    class PID:
        pid_3 = []
        pid_5 = [NameComp()]  # triggers the name parsing block
        pid_7 = None
        pid_8 = None

    xf = ADTA08Transformer()
    p = xf._build_patient(PID())

    assert p.name and p.name[0].family == "StrFamily"
    assert p.name[0].given == ["StrGiven"]


# ------------------------------------------------------------------------------
# _parse_hl7_yyyymmdd
# ------------------------------------------------------------------------------


def test_parse_hl7_yyyymmdd_exception_path():
    class Boom:
        def to_er7(self):
            raise ValueError("boom")

    assert _parse_hl7_yyyymmdd(Boom()) is None
