# tests/test_adt_a03.py
import pytest
from hl7apy.parser import parse_message as _pm
from fhir.resources.coding import Coding
from fhir.resources.period import Period
from fhir.resources.encounter import Encounter

from hl7_fhir_tool.transform.v2_to_fhir.adt_a03 import ADTA03Transformer, _parse_hl7_ts

# ------------------------------------------------------------------------------
# globals
# ------------------------------------------------------------------------------

# Minimal A03 message for patient/encounter tests
RAW_A03 = (
    "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00001|P|2.5\r"
    "PID|||12345^^^HOSP^MR||Doe^Jane||19800101|F\r"
    "PV1||I|" + "|".join([""] * 42)
)


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


@pytest.fixture
def transformer() -> ADTA03Transformer:
    return ADTA03Transformer()


# ------------------------------------------------------------------------------
# transform
# ------------------------------------------------------------------------------


def test_transform_minimal_sets_patient_and_encounter(transformer: ADTA03Transformer):
    msg = _pm(RAW_A03)
    patient, encounter = transformer.transform(msg)

    assert patient.id == "12345"
    assert patient.name and patient.name[0].family == "Doe"
    assert patient.name[0].given and patient.name[0].given[0] == "Jane"

    assert encounter.status == "finished"
    assert encounter.class_fhir is not None
    assert isinstance(encounter.class_fhir.coding[0], Coding)
    assert encounter.class_fhir.coding[0].code == "I"


def test_transform_sets_period_when_pv1_44_45_present(transformer: ADTA03Transformer):
    pv1_fields = [""]
    pv1_fields.append("I")
    pv1_fields.extend([""] * 16)
    pv1_fields.append("V123")
    pv1_fields.extend([""] * 24)
    pv1_fields.extend(["20250101", "20250102"])
    pv1_line = "|".join(pv1_fields)

    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00003|P|2.5\r"
        "PID|||77777^^^HOSP^MR||Alpha^Test||19900101|U\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)

    assert encounter.period is not None
    assert isinstance(encounter.period, Period)
    assert encounter.period.start == "2025-01-01"
    assert encounter.period.end == "2025-01-02"


def test_transform_partial_period(transformer: ADTA03Transformer):
    pv1_fields = [""]
    pv1_fields.append("I")
    pv1_fields.extend([""] * 16)
    pv1_fields.append("V999")
    pv1_fields.extend([""] * 24)
    pv1_fields.append("20250101")
    pv1_line = "|".join(pv1_fields)

    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00010|P|2.5\r"
        "PID|||88888^^^HOSP^MR||Beta^Case||19990101|M\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)

    assert encounter.period is not None
    assert encounter.period.start == "2025-01-01"
    assert encounter.period.end is None


def test_transform_fallback_encounter_id_when_no_visit_num(
    transformer: ADTA03Transformer,
):
    pv1_fields = [""] + ["I"] + [""] * 42
    pv1_line = "|".join(pv1_fields)
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00005|P|2.5\r"
        "PID|||99999^^^HOSP^MR||Gamma^Unit||19850101|F\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    patient, encounter = transformer.transform(msg)
    assert encounter.id == f"enc-{patient.id}"


def test_transform_handles_missing_pid(transformer: ADTA03Transformer):
    pv1_fields = [""] + ["I"] + [""] * 42
    pv1_line = "|".join(pv1_fields)
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00006|P|2.5\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)
    assert encounter.id.startswith("enc-")


def test_transform_handles_family_without_given(transformer: ADTA03Transformer):
    pv1_fields = [""] + ["I"] + [""] * 42
    pv1_line = "|".join(pv1_fields)
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00007|P|2.5\r"
        "PID|||12346^^^HOSP^MR||Solo^\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    patient, _ = transformer.transform(msg)
    assert patient.name is not None
    assert patient.name[0].family == "Solo"
    if patient.name[0].given:
        assert isinstance(patient.name[0].given[0], str)


def test_transform_missing_msh9(transformer: ADTA03Transformer):
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00020|P|2.5\r"
        "PID|||123^^^HOSP^MR||Test^User||20000101|M\r"
        "PV1||I|" + "|".join([""] * 42)
    )
    msg = _pm(raw)
    delattr(msg.MSH, "msh_9")
    assert transformer.applies(msg) is False


def test_transform_missing_pid_segment(transformer: ADTA03Transformer):
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00021|P|2.5\r"
        "PV1||I|" + "|".join([""] * 42)
    )
    msg = _pm(raw)
    patient, _ = transformer.transform(msg)
    assert patient.id is None
    assert patient.name is None


def test_transform_pid_missing_name(transformer: ADTA03Transformer):
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00022|P|2.5\r"
        "PID|||123^^^HOSP^MR\r"
        "PV1||I|" + "|".join([""] * 42)
    )
    msg = _pm(raw)
    patient, _ = transformer.transform(msg)
    assert patient.name is None
    assert patient.id == "123"


def test_transform_pid_missing_id(transformer: ADTA03Transformer):
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00023|P|2.5\r"
        "PID|||^^^HOSP^MR||Doe^John\r"
        "PV1||I|" + "|".join([""] * 42)
    )
    msg = _pm(raw)
    patient, _ = transformer.transform(msg)
    assert patient.id is None
    assert patient.name[0].family == "Doe"


def test_transform_pv1_missing(transformer: ADTA03Transformer):
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00024|P|2.5\r"
        "PID|||555^^^HOSP^MR||Missing^PV1\r"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)
    assert isinstance(encounter, Encounter)
    assert encounter.period is None
    assert encounter.class_fhir.coding == []


def test_transform_pv1_missing_class_and_visit(transformer: ADTA03Transformer):
    pv1_fields = [""] + [""] * 43
    pv1_line = "|".join(pv1_fields)
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00025|P|2.5\r"
        "PID|||999^^^HOSP^MR||Fallback^Test\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)
    assert encounter.id.startswith("enc-")
    assert encounter.class_fhir.coding == []


def test_transform_invalid_hl7_ts(transformer: ADTA03Transformer):
    pv1_fields = ["I"] + [""] * 42 + ["202501", "badts"]
    pv1_line = "|".join(pv1_fields)
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00026|P|2.5\r"
        "PID|||777^^^HOSP^MR||Invalid^TS\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)
    assert encounter.period is None


def test_transform_partial_pv1_period_missing_end(transformer: ADTA03Transformer):
    pv1_fields = ["I"] + [""] * 42 + ["20250101", ""]
    pv1_line = "|".join(pv1_fields)
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00052|P|2.5\r"
        "PID|||66666^^^HOSP^MR||Partial^Period||20010101|F\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)
    assert encounter.period.start == "2025-01-01"
    assert encounter.period.end is None


def test_transform_parse_hl7_ts_invalid_dates(transformer: ADTA03Transformer):
    pv1_fields = ["I"] + [""] * 42 + ["BADDATE", ""]
    pv1_line = "|".join(pv1_fields)
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00050|P|2.5\r"
        "PID|||55555^^^HOSP^MR||NoName||20000101|M\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)
    assert encounter.period is None
    assert encounter.class_fhir is not None
    if encounter.class_fhir.coding:
        assert encounter.class_fhir.coding[0].code == "I"


def test_transform_missing_pid3_and_pid5(transformer: ADTA03Transformer):
    pv1_fields = ["I"] + [""] * 42
    pv1_line = "|".join(pv1_fields)
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00051|P|2.5\r"
        "PID||||||\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    patient, encounter = transformer.transform(msg)
    assert patient.id is None
    assert patient.name is None
    assert encounter.class_fhir is not None
    if encounter.class_fhir.coding:
        assert encounter.class_fhir.coding[0].code == "I"


def test_transform_parse_hl7_ts_exception_branch(transformer: ADTA03Transformer):
    pv1_fields = ["I"] + [""] * 42 + ["BADDATE", "20250102"]
    pv1_line = "|".join(pv1_fields)
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00060|P|2.5\r"
        "PID|||123^^^HOSP^MR||Test^Patient||19900101|M\r"
        f"PV1|{pv1_line}"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)
    assert encounter.period is not None
    assert encounter.period.start is None
    assert encounter.period.end == "2025-01-02"


def test_transform_pid_name_missing(transformer: ADTA03Transformer):
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00061|P|2.5\r"
        "PID|||123^^^HOSP^MR||\r"
        "PV1||I|" + "|".join([""] * 42)
    )
    msg = _pm(raw)
    patient, _ = transformer.transform(msg)
    assert patient.name is None


def test_transform_pid_id_missing(transformer: ADTA03Transformer):
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00062|P|2.5\r"
        "PID||||||\r"
        "PV1||I|" + "|".join([""] * 42)
    )
    msg = _pm(raw)
    patient, _ = transformer.transform(msg)
    assert patient.id is None


def test_transform_applies_msh9_attribute_error(transformer: ADTA03Transformer):
    class FakeMSH:
        @property
        def msh_9(self):
            raise AttributeError("simulated missing msh_9")

    class FakeMsg:
        MSH = FakeMSH()

    msg = FakeMsg()
    assert transformer.applies(msg) is False


def test_transform_pid_name_fallback(transformer: ADTA03Transformer):
    class BadPIDName:
        family_name = None
        given_name = None

    class BadPIDId:
        cx_1 = None

    class FakePID:
        pid_5 = [BadPIDName()]
        pid_3 = [BadPIDId()]

    class FakeMsg:
        PID = FakePID()
        PV1 = None

    msg = FakeMsg()
    patient, encounter = transformer.transform(msg)
    assert patient.name is None
    assert patient.id is None
    assert encounter is not None


def test_transform_pid_id_str_fallback(transformer: ADTA03Transformer):
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00110|P|2.5\r"
        "PID|||123ABC^^^HOSP^MR||\r"
        "PV1||I|" + "|".join([""] * 42)
    )
    msg = _pm(raw)
    patient, _ = transformer.transform(msg)
    assert patient.id == "123ABC"


def test_transform_partial_pv1_exception(transformer: ADTA03Transformer):
    raw = (
        "MSH|^~\\&|EPIC|HOSP|REC|REC|202501010830||ADT^A03|00111|P|2.5\r"
        "PID|||999^^^HOSP^MR||Test^Patient||19900101|M\r"
        "PV1||I|" + "|".join([""] * 42) + "|BADDATE|ANOTHERBAD"
    )
    msg = _pm(raw)
    _, encounter = transformer.transform(msg)
    assert encounter.period is None


def test_transform_pv1_44_45_exception(transformer: ADTA03Transformer):
    class PV1WithRaise:
        pv1_2 = "I"
        pv1_19 = "V001"

        @property
        def pv1_44(self):
            raise ValueError("forced error")

        @property
        def pv1_45(self):
            raise ValueError("forced error")

        @property
        def children(self):
            return []

    class Msg:
        PID = None
        PV1 = PV1WithRaise()

    msg = Msg()
    _, encounter = transformer.transform(msg)
    assert encounter.period is None
    assert encounter.class_fhir is not None
    assert encounter.id == "V001"


def test_family_given_fallback_to_str(transformer: ADTA03Transformer):
    class FakeField:
        def __init__(self, value):
            self.value = value

        # no to_er7 method

        def __str__(self):
            return str(self.value)

    class FakePIDName:
        family_name = FakeField("FamilyStr")
        given_name = FakeField("GivenStr")

    class FakePID:
        pid_5 = [FakePIDName()]
        pid_3 = []  # irrelevant for this test

    class FakeMsg:
        PID = FakePID()
        PV1 = None

    msg = FakeMsg()
    patient, _ = transformer.transform(msg)

    assert patient.name is not None
    assert patient.name[0].family == "FamilyStr"
    assert patient.name[0].given[0] == "GivenStr"


# ------------------------------------------------------------------------------
# _parse_hl7_ts
# ------------------------------------------------------------------------------


def test_parse_hl7_ts_directly():
    assert _parse_hl7_ts("BAD") is None
    assert _parse_hl7_ts("") is None
    assert _parse_hl7_ts(None) is None
