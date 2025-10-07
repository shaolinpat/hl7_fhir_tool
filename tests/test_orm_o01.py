# tests/test_orm_o01.py
from __future__ import annotations

import pytest
from hl7apy.parser import parse_message

from hl7_fhir_tool.transform.v2_to_fhir.orm_o01 import (
    ORMO01Transformer,
    _parse_hl7_yyyymmdd,
    _er7,
    _field_comp_from_er7,
    _find_first,
    _first_segment_line,
)


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _raw_orm(mshtype: str, pid: str | None, orc: str | None, obr: str | None) -> str:
    parts = [f"MSH|^~\\&|EPIC|HOSP|LIS|LAB|202501011230||{mshtype}|MSG001|P|2.5"]
    if pid is not None:
        parts.append(pid)
    if orc is not None:
        parts.append(orc)
    if obr is not None:
        parts.append(obr)
    return "\r".join(parts)


def _code_text(sr):
    code = getattr(sr, "code", None)
    if code is None:
        return None
    concept = getattr(code, "concept", None)
    return (
        getattr(concept, "text", None)
        if concept is not None
        else getattr(code, "text", None)
    )


# ------------------------------------------------------------------------------
# applies()
# ------------------------------------------------------------------------------


def test_applies_true_and_false():
    xf = ORMO01Transformer()
    msg_yes = parse_message(
        _raw_orm("ORM^O01", "PID|1||X||A^B||19800101|M|", None, None)
    )
    msg_no = parse_message(
        _raw_orm("ADT^A01", "PID|1||X||A^B||19800101|M|", None, None)
    )

    assert xf.applies(msg_yes) is True
    assert xf.applies(msg_no) is False


def test_applies_handles_msh_exception_returns_false():

    class BadMSH:
        @property
        def msh_9(self):
            raise RuntimeError("nope")

    class Msg:
        MSH = BadMSH()

    xf = ORMO01Transformer()

    assert xf.applies(Msg()) is False


# ------------------------------------------------------------------------------
# transform()
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "orc_status,expected",
    [
        ("NW", "active"),
        ("IP", "active"),
        ("SC", "active"),
        ("CM", "completed"),
        ("XX", "active"),
        (None, "active"),
    ],
)
def test_transform_status_mapping(orc_status, expected):
    st = orc_status or ""
    xf = ORMO01Transformer()
    msg = parse_message(
        _raw_orm(
            "ORM^O01",
            "PID|1||2000^^^HOSP^MR||S^T||20000101|F|",
            f"ORC|{st}|PZ||FZ|{st}||||202501011230||||||||||",
            "OBR|1|PZ|FZ|NA^Sodium|||202501011200|||||||||||||||||||||||",
        )
    )
    _, sr = xf.transform(msg)

    assert sr.status == expected


def test_transform_happy():
    xf = ORMO01Transformer()
    msg = parse_message(
        _raw_orm(
            "ORM^O01",
            "PID|1||12345^^^HOSP^MR||Doe^John||19800101|M|",
            "ORC|NW|P123||F456|SC||||202501011230||||||||||",
            "OBR|1|P123|F456|HGB^Hemoglobin|||202501011200|||||||||||||||||||||||",
        )
    )
    patient, sr = xf.transform(msg)

    assert patient.id == "12345"
    assert (
        patient.name
        and patient.name[0].family == "Doe"
        and patient.name[0].given == ["John"]
    )
    assert str(patient.birthDate) == "1980-01-01"
    assert patient.gender == "male"
    assert sr.intent == "order"
    assert sr.status == "active"
    assert any(i.value == "P123" for i in (sr.identifier or []))
    assert _code_text(sr) == "Hemoglobin"
    assert sr.subject.reference == f"Patient/{patient.id}"


def test_transform_missing_orc_uses_sr_fallback_and_obr_raw_code():
    xf = ORMO01Transformer()
    msg = parse_message(
        _raw_orm(
            "ORM^O01",
            "PID|1||99999^^^HOSP^MR||Solo^Patient||19750704|F|",
            None,
            "OBR|1|||GLU^Glucose|||202501011200|||||||||||||||||||||||",
        )
    )
    patient, sr = xf.transform(msg)

    assert sr.id == f"sr-{patient.id}"
    assert _code_text(sr) == "Glucose"


# ------------------------------------------------------------------------------
# _parse_hl7_yyyymmdd()
# ------------------------------------------------------------------------------


def test_parse_hl7_yyyymmdd_happy_and_edge():

    class Boom:
        def to_er7(self):
            raise RuntimeError("nope")

    assert _parse_hl7_yyyymmdd("19800101") == "1980-01-01"
    assert _parse_hl7_yyyymmdd("19800101123456") == "1980-01-01"
    assert _parse_hl7_yyyymmdd("198001") is None
    assert _parse_hl7_yyyymmdd("1980") is None
    assert _parse_hl7_yyyymmdd("abc") is None
    assert _parse_hl7_yyyymmdd(Boom()) is None


# ------------------------------------------------------------------------------
# _field_comp_from_er7()
# ------------------------------------------------------------------------------


def test_field_comp_from_er7_and_to_er7():

    class Dummy:
        def to_er7(self):
            return " A^B "

    line = "PID|1||12345^^^HOSP^MR||Doe^John||19800101|M|"

    assert _er7(None) == ""
    assert _er7(Dummy()) == "A^B"
    assert _field_comp_from_er7(line, 3, 1) == "12345"
    assert _field_comp_from_er7(line, 5, 1) == "Doe"
    assert _field_comp_from_er7(line, 5, 2) == "John"
    assert _field_comp_from_er7(line, 7, 1) == "19800101"
    assert _field_comp_from_er7(line, 99, 1) is None
    assert _field_comp_from_er7(None, 3, 1) is None


# ------------------------------------------------------------------------------
# _first_segment_line()
# ------------------------------------------------------------------------------


def test_first_segment_line_and_find_first_paths():

    class DummyMsg:
        def to_er7(self):
            raise RuntimeError("boom")

    msg = parse_message(
        _raw_orm(
            "ORM^O01",
            "PID|1||ABC^^^HOSP^MR||FamName^GivName||20000101|F|",
            "ORC|NW|P1||F1|NW||||202501011230||||||||||",
            "OBR|1|P1|F1|GLU^Glucose|||202501011200|||||||||||||||||||||||",
        )
    )

    assert _first_segment_line(msg, "PID").startswith("PID|")
    assert _first_segment_line(msg, "ORC").startswith("ORC|")
    assert _first_segment_line(msg, "OBR").startswith("OBR|")
    assert _first_segment_line(msg, "ZZZ") is None
    assert _first_segment_line(DummyMsg(), "PID") is None
    assert _find_first(msg, "PID") is not None
    assert _find_first(msg, "ORC") is not None
    assert _find_first(msg, "OBR") is not None


def test_first_segment_line_codeable_reference_retry_without_code(monkeypatch):

    class BoomCR:
        def __init__(self, *_, **__):
            raise ValueError("boom")

    CodeableReference_orig = _first_segment_line.__globals__["CodeableReference"]
    _first_segment_line.__globals__["CodeableReference"] = BoomCR
    try:
        xf = ORMO01Transformer()
        msg = parse_message(
            "\r".join(
                [
                    "MSH|^~\\&|EPIC|HOSP|LIS|LAB|202501011230||ORM^O01|X|P|2.5",
                    "PID|1||900^^^HOSP^MR||X^Y||19700101|M|",
                    "ORC|NW|PLX||FLX|NW||||202501011230||||||||||",
                    "OBR|1|PLX|FLX|HGB^Hemoglobin|||202501011200|||||||||||||||||||||||",
                ]
            )
        )
        patient, sr = xf.transform(msg)

        assert sr.intent == "order" and sr.status == "active"
        assert getattr(sr, "code", None) is None
        assert sr.subject.reference == f"Patient/{patient.id}"
    finally:
        _first_segment_line.__globals__["CodeableReference"] = CodeableReference_orig


# ------------------------------------------------------------------------------
# _find_first()
# ------------------------------------------------------------------------------


def test_find_first_children_and_recursion_exception_paths():

    class ChildRaisesOnName:
        @property
        def name(self):
            raise RuntimeError("boom")

    class Leaf:
        name = "OBR"

    class Mid:
        name = "MID"
        children = [Leaf()]

    class Root:
        children = [ChildRaisesOnName(), Mid()]

    class RootEmpty:
        children = []

    assert _find_first(Root(), "OBR") is not None
    assert _find_first(RootEmpty(), "ZZZ") is None


def test_find_first_attr_get_raises_then_children_scan_continues():

    class BoomOnOBR:
        def __getattr__(self, name):
            if name == "OBR":
                raise RuntimeError("boom")
            raise AttributeError

        children = []

    assert _find_first(BoomOnOBR(), "OBR") is None


def test_find_first_children_get_raises_then_recursion_except_and_return_none():

    class NoChildrenProp:
        def __getattr__(self, name):
            if name == "children":
                raise RuntimeError("boom")
            raise AttributeError

    class ChildBad:
        def __getattr__(self, name):
            if name in ("children", "name"):
                raise RuntimeError("bad child")
            raise AttributeError

    root = type("Root", (), {"children": [ChildBad()]})()

    assert _find_first(NoChildrenProp(), "PID") is None
    assert _find_first(root, "ZZZ") is None


def test_find_first_recursion_miss_then_continue_loop():

    class LeafNoMatch:
        name = "ZZZ"
        children = []

    class ChildWithChildren:
        name = "MID"
        children = [LeafNoMatch()]

    class ChildNoChildren:
        name = "NOPE"
        children = []

    root = type("Root", (), {"children": [ChildWithChildren(), ChildNoChildren()]})()

    assert _find_first(root, "OBR") is None


def test_find_first_no_children_attr_and_wrong_name():

    class NoChildren:
        name = "PID"

    class Leaf:
        name = "ZZZ"

    class Root:
        children = [Leaf()]

    assert _find_first(NoChildren(), "OBR") is None
    assert _find_first(Root(), "OBR") is None


# ------------------------------------------------------------------------------
# _build_patient()
# ------------------------------------------------------------------------------


def test_build_patient_all_components():

    class _V:
        def __init__(self, s):
            self.s = s

        def to_er7(self):
            return self.s

    class PID:
        @property
        def pid_3(self):
            class Rep:
                cx_1 = _V("COMPID123")

            return [Rep()]

        @property
        def pid_5(self):
            class Name:
                family_name = _V("CompFamily")
                given_name = _V("CompGiven")

            return [Name()]

        @property
        def pid_7(self):
            return _V("19840229")

        @property
        def pid_8(self):
            return _V("F")

    p = ORMO01Transformer._build_patient(PID(), None)

    assert p.id == "COMPID123"
    assert p.name[0].family == "CompFamily" and p.name[0].given == ["CompGiven"]
    assert str(p.birthDate) == "1984-02-29"
    assert p.gender == "female"


@pytest.mark.parametrize(
    "pid_obj, raw_line, expected_id",
    [
        (
            type("PID", (), {"pid_3": None})(),
            "PID|||RF01^ASSIGN||A^B||19700203|M",
            "RF01",
        ),
        (type("PID", (), {"pid_3": []})(), "PID|||RF02||A^B||19840102|F", "RF02"),
        (
            type(
                "PID",
                (),
                {
                    "pid_3": type(
                        "X",
                        (),
                        {
                            "__len__": lambda self: (_ for _ in ()).throw(
                                RuntimeError("boom")
                            )
                        },
                    )()
                },
            )(),
            "PID|||RF03^ASSIGN||A^B||19650101|M",
            "RF03",
        ),
        (
            type(
                "PID",
                (),
                {
                    "pid_3": type(
                        "X",
                        (),
                        {"__len__": lambda self: 1, "__bool__": lambda self: False},
                    )()
                },
            )(),
            "PID|||RF04||A^B||19991231|U",
            "RF04",
        ),
        # rep exists but has neither cx_1 nor id_number
        (
            type("PID", (), {"pid_3": [type("Rep", (), {})()]})(),
            "PID|||RF05||A^B||19770101|F",
            "RF05",
        ),
    ],
)
def test_build_patient_pid3_to_raw_fallback_variants(pid_obj, raw_line, expected_id):
    p = ORMO01Transformer._build_patient(pid=pid_obj, pid_line=raw_line)

    assert p.id == expected_id


def test_build_patient_names_dates_gender_raw_fallbacks():

    class PidStub:
        @property
        def pid_3(self):
            class _Rep:
                pass

            return _Rep()

        @property
        def pid_5(self):
            return ()

    line = "PID|1||AB123^^^HOSP^MR||FamName^GivName||19851231|F|"
    p = ORMO01Transformer._build_patient(PidStub(), line)

    assert p.id == "AB123"
    assert p.name[0].family == "FamName" and p.name[0].given == ["GivName"]
    assert str(p.birthDate) == "1985-12-31"
    assert p.gender == "female"


def test_build_patient_family_only_and_unknown_gender_paths():
    msg = parse_message(
        "\r".join(
            [
                "MSH|^~\\&|EPIC|HOSP|LIS|LAB|202501011230||ORM^O01|X|P|2.5",
                "PID|1||999^^^HOSP^MR||OnlyFamily^||19991231|U|",
            ]
        )
    )
    pid = _find_first(msg, "PID")
    p = ORMO01Transformer._build_patient(pid, _first_segment_line(msg, "PID"))

    assert p.id == "999" and p.name[0].family == "OnlyFamily" and p.gender == "unknown"


def test_build_patient_component_then_raw_and_id_setter_raises(monkeypatch):

    class RaisingIdPatient:
        def __init__(self, *_, **__):
            pass

        def __setattr__(self, name, value):
            if name == "id":
                raise ValueError("reject id")
            object.__setattr__(self, name, value)

    class PidStub:
        @property
        def pid_3(self):
            class _Rep:
                pass

            return _Rep()

        @property
        def pid_5(self):
            return ()

    Patient_orig = _first_segment_line.__globals__["Patient"]
    _first_segment_line.__globals__["Patient"] = RaisingIdPatient
    try:
        raw = "PID|1||RAWID^^^HOSP^MR||FamName^GivName||19701231|M|"
        p = ORMO01Transformer._build_patient(PidStub(), raw)

        assert p.name[0].family == "FamName" and p.name[0].given == ["GivName"]
        assert str(p.birthDate) == "1970-12-31" and p.gender == "male"
    finally:
        _first_segment_line.__globals__["Patient"] = Patient_orig


def test_build_patient_pid3_falls_back_and_pid3_absent_logs_not_found():

    class PidUnusable:
        @property
        def pid_3(self):
            class _Rep:
                pass

            return _Rep()

    p1 = ORMO01Transformer._build_patient(
        PidUnusable(), "PID|1||AB12||X^Y||19900101|M|"
    )
    p2 = ORMO01Transformer._build_patient(PidUnusable(), "PID|1|||X^Y||19900101|M|")

    assert p1.id == "AB12"
    assert getattr(p2, "id", None) is None


def test_build_patient_pid5_structured_variants_and_raw_fallbacks():

    class PidFamOnly:
        @property
        def pid_5(self):
            class Nm:
                family_name = type("Pid5Value", (), {"to_er7": lambda self: "Fam"})()
                given_name = None

            return [Nm()]

    class PidGivenOnly:
        @property
        def pid_5(self):
            class Nm:
                family_name = None
                given_name = type("Pid5Value", (), {"to_er7": lambda self: "Giv"})()

            return [Nm()]

    p1 = ORMO01Transformer._build_patient(PidFamOnly(), None)
    p2 = ORMO01Transformer._build_patient(PidGivenOnly(), None)
    p3 = ORMO01Transformer._build_patient(
        type("PidNone", (), {"pid_5": None})(),
        "PID|1||X||FamilyRaw^GivenRaw||19800101|M|",
    )

    assert p1.name[0].family == "Fam" and p1.name[0].given is None
    assert p2.name[0].family is None and p2.name[0].given == ["Giv"]
    assert p3.name[0].family == "FamilyRaw" and p3.name[0].given == ["GivenRaw"]


def test_build_patient_pid7_birthdate_component_and_raw_and_invalid():

    class Pid7:
        @property
        def pid_7(self):
            return type("Pid7Value", (), {"to_er7": lambda self: "19751231"})()

    p1 = ORMO01Transformer._build_patient(Pid7(), None)
    p2 = ORMO01Transformer._build_patient(None, "PID|1||X||A^B||19840229|F|")
    p3 = ORMO01Transformer._build_patient(None, "PID|1||X||A^B||abc|M|")

    assert str(p1.birthDate) == "1975-12-31"
    assert str(p2.birthDate) == "1984-02-29"
    assert getattr(p3, "birthDate", None) is None


def test_build_patient_pid8_gender_paths_and_exception_guard():

    class Pid8M:
        @property
        def pid_8(self):
            return type("Pid8Value", (), {"to_er7": lambda self: "M"})()

    class BadPid:
        @property
        def pid_8(self):
            raise RuntimeError("boom")

    p1 = ORMO01Transformer._build_patient(Pid8M(), None)
    p2 = ORMO01Transformer._build_patient(None, "PID|1||X||A^B||19800101|F|")
    p3 = ORMO01Transformer._build_patient(None, "PID|1||X||A^B||19800101|U|")
    _ = ORMO01Transformer._build_patient(BadPid(), None)

    assert p1.gender == "male"
    assert p2.gender == "female"
    assert p3.gender == "unknown"


# ------------------------------------------------------------------------------
# _build_service_request()
# ------------------------------------------------------------------------------


def test_build_service_request_orc_component_ids_and_completed_status():

    class _V:
        def __init__(self, v):
            self.v = v

        def to_er7(self):
            return self.v

    class ORC:
        orc_2 = _V("PLACERX")
        orc_3 = _V("FILLERY")
        orc_5 = _V("CM")

    xf = ORMO01Transformer()
    p = xf._build_patient(None, None)
    sr = xf._build_service_request(
        orc=ORC(), obr=None, patient=p, orc_line=None, obr_line=None
    )

    assert sr.id == "PLACERX" and sr.status == "completed" and sr.intent == "order"


def test_build_service_request_orc_and_obr_component_paths_minimal():

    class Orc:
        class orc_2:
            def to_er7(self):
                return "PX"

        class orc_3:
            def to_er7(self):
                return "FX"

        class orc_5:
            def to_er7(self):
                return "NW"

    class Obr:
        class obr_4:
            def to_er7(self):
                return "GLU^Glucose"

    xf = ORMO01Transformer()
    p = xf._build_patient(None, None)
    sr = xf._build_service_request(
        orc=Orc(), obr=Obr(), patient=p, orc_line=None, obr_line=None
    )

    assert sr.intent == "order" and sr.status == "active" and getattr(sr, "id", None)


def test_build_service_request_sr_defaults_when_segments_missing():
    xf = ORMO01Transformer()
    p = xf._build_patient(None, None)
    sr = xf._build_service_request(
        orc=None, obr=None, patient=p, orc_line=None, obr_line=None
    )

    assert (
        sr.intent == "order"
        and sr.status == "active"
        and sr.subject.reference.startswith("Patient/")
    )


def test_build_service_request_sr_identifiers_from_orc_raw_and_component_and_except():

    class ORCComp:
        def __init__(self):
            self.orc_2 = type("Orc2Value", (), {"to_er7": lambda self: "PLX"})()
            self.orc_3 = type("Orc3Value", (), {"to_er7": lambda self: "FLY"})()

    xf = ORMO01Transformer()
    patient = xf._build_patient(None, "PID|1||PATID||A^B||19700101|M|")
    sr1 = xf._build_service_request(
        orc=None, obr=None, patient=patient, orc_line="ORC|NW|PL123||", obr_line=None
    )
    sr2 = xf._build_service_request(
        orc=None, obr=None, patient=patient, orc_line="ORC|NW||FL456", obr_line=None
    )
    sr3 = xf._build_service_request(
        orc=ORCComp(), obr=None, patient=patient, orc_line=None, obr_line=None
    )

    assert sr1.id == "PL123"
    assert any(i.value == "PL123" for i in (sr1.identifier or []))
    assert sr2.id == "FL456"
    assert any(i.value == "FL456" for i in (sr2.identifier or []))
    assert sr3.id in {"PLX", "FLY"}


def test_build_service_request_sr_obr_code_components_and_obr_exception():

    class OBRComp:
        def __init__(self):
            self.obr_4 = type(
                "OBR4Composite",
                (),
                {
                    "identifier": type(
                        "OBR4Identifier", (), {"to_er7": lambda self: "GLU"}
                    )(),
                    "text": type("OBR4Text", (), {"to_er7": lambda self: "Glucose"})(),
                },
            )()

    class OBRBad:
        @property
        def obr_4(self):
            raise RuntimeError("nope")

    xf = ORMO01Transformer()
    patient = xf._build_patient(None, "PID|1||X||A^B||19700101|M|")
    sr1 = xf._build_service_request(
        orc=None, obr=OBRComp(), patient=patient, orc_line=None, obr_line=None
    )
    sr2 = xf._build_service_request(
        orc=None, obr=OBRBad(), patient=patient, orc_line=None, obr_line=None
    )

    assert _code_text(sr1) == "Glucose"
    assert sr2.intent == "order" and sr2.status in {"active", "completed"}


def test_build_service_request_sr_status_from_orc5_component_and_exception():

    class ORC5:
        def __init__(self):
            self.orc_5 = type("ORC5Status", (), {"to_er7": lambda self: "CM"})()

    class ORCBad:
        @property
        def orc_5(self):
            raise RuntimeError("boom")

    xf = ORMO01Transformer()
    patient = xf._build_patient(None, None)
    sr = xf._build_service_request(
        orc=ORC5(), obr=None, patient=patient, orc_line=None, obr_line=None
    )

    assert sr.status == "completed"

    _ = xf._build_service_request(
        orc=ORCBad(), obr=None, patient=patient, orc_line=None, obr_line=None
    )


def test_build_service_request_sr_id_exception_fallback_branch_tracks_raise(
    monkeypatch,
):

    class _SRShim:
        def __init__(
            self, intent=None, status=None, code=None, identifier=None, subject=None
        ):
            self.intent = intent
            self.status = status
            self.code = code
            self.identifier = identifier
            self.subject = subject
            self._raised_once = False
            self.id = None

        def __setattr__(self, name, value):
            if (
                name == "id"
                and value == "IDX"
                and not getattr(self, "_raised_once", False)
            ):
                object.__setattr__(self, "_raised_once", True)
                raise ValueError("simulate invalid id on first set")
            return object.__setattr__(self, name, value)

    xf = ORMO01Transformer()
    patient = xf._build_patient(None, "PID|1||PID9||A^B||19700101|M|")
    fn = ORMO01Transformer._build_service_request
    SR_orig = fn.__globals__["ServiceRequest"]

    # Force the function to use our shim instead of the real ServiceRequest
    monkeypatch.setitem(fn.__globals__, "ServiceRequest", _SRShim)
    try:
        sr = xf._build_service_request(
            orc=None,
            obr=None,
            patient=patient,
            orc_line="ORC|NW|IDX||",
            obr_line=None,
        )
    finally:
        # restore
        monkeypatch.setitem(fn.__globals__, "ServiceRequest", SR_orig)

    assert sr.id == f"sr-{patient.id}"
    assert sr.status == "active"
    assert sr.intent == "order"


def test_build_service_request_sr_build_with_partial_obr(monkeypatch):

    class Obr:
        obr_4 = None
        obr_7 = None
        obr_16 = None
        obr_32 = None

    xf = ORMO01Transformer()
    p = xf._build_patient(None, None)
    sr = xf._build_service_request(
        orc=None, obr=Obr(), patient=p, orc_line=None, obr_line=None
    )

    assert sr.status == "active"
    assert sr.intent == "order"


def test_build_service_request_sr_orc_block_exception_is_caught_and_logged(monkeypatch):

    class BadORC:
        @property
        def orc_2(self):
            raise RuntimeError("boom ORC")

    class _LogSpy:
        def __init__(self):
            self.errors = []
            self.error_kwargs = []
            self.debugs = []

        def error(self, msg, *args, **kwargs):
            try:
                self.errors.append(msg % args if args else str(msg))
            except Exception:
                self.errors.append(str(msg))
            self.error_kwargs.append(kwargs)

        def debug(self, msg, *args, **kwargs):
            try:
                self.debugs.append(msg % args if args else str(msg))
            except Exception:
                self.debugs.append(str(msg))

    xf = ORMO01Transformer()
    patient = xf._build_patient(None, "PID|1||P1||X^Y||19700101|M|")
    fn = ORMO01Transformer._build_service_request
    spy = _LogSpy()
    monkeypatch.setitem(fn.__globals__, "LOG", spy)
    sr = xf._build_service_request(
        orc=BadORC(), obr=None, patient=patient, orc_line=None, obr_line=None
    )

    assert any(e.startswith("Error parsing ORC") for e in spy.errors)
    assert any(kw.get("exc_info") for kw in spy.error_kwargs)
    assert sr.intent == "order" and sr.status == "active"


def test_build_service_request_sr_id_fallback_when_first_set_raises(monkeypatch):

    class _DummyPatient:
        def __init__(self, pid: str = "ZZ999") -> None:
            self.id = pid

    class _SRShim:
        def __init__(
            self, intent=None, status=None, code=None, identifier=None, subject=None
        ):
            self.intent = intent
            self.status = status
            self.code = code
            self.identifier = identifier
            self.subject = subject
            self._first_raise_done = False

        def __setattr__(self, name, value):
            if name == "id":
                if not getattr(self, "_first_raise_done", False):
                    object.__setattr__(self, "_first_raise_done", True)
                    raise ValueError("simulate invalid id on first set")
                return object.__setattr__(self, name, value)
            return object.__setattr__(self, name, value)

    patient = _DummyPatient("ZZ999")
    orc_line = "ORC|NW|PLACER123||SC"
    fn = ORMO01Transformer._build_service_request
    monkeypatch.setitem(fn.__globals__, "ServiceRequest", _SRShim)
    sr = ORMO01Transformer._build_service_request(
        orc=None,
        obr=None,
        patient=patient,
        orc_line=orc_line,
        obr_line=None,
    )

    assert sr.id == "sr-ZZ999"


def test_build_service_request_sr_obr_components_path_builds_codeable_concept_text():

    class OBRComp:
        def __init__(self):
            self.obr_4 = type(
                "OBR4Composite",
                (),
                {
                    "identifier": type(
                        "OBR4Identifier", (), {"to_er7": lambda self: "GLU"}
                    )(),
                    "text": type("ORB4Text", (), {"to_er7": lambda self: "Glucose"})(),
                },
            )()

    xf = ORMO01Transformer()
    patient = xf._build_patient(None, "PID|1||Z9||A^B||19700101|M|")
    sr = xf._build_service_request(
        orc=None, obr=OBRComp(), patient=patient, orc_line=None, obr_line=None
    )

    assert _code_text(sr) == "Glucose"


def test_build_service_request_sr_id_assignment_exception_branch_minimal(monkeypatch):

    class _SRShim:
        def __init__(
            self, intent=None, status=None, code=None, identifier=None, subject=None
        ):
            self.intent = intent
            self.status = status
            self.code = code
            self.identifier = identifier
            self.subject = subject
            self._raised_once = False
            self.id = None

        def __setattr__(self, name, value):
            if (
                name == "id"
                and value == "IDX"
                and not getattr(self, "_raised_once", False)
            ):
                object.__setattr__(self, "_raised_once", True)
                raise ValueError("simulate invalid id on first set")
            return object.__setattr__(self, name, value)

    xf = ORMO01Transformer()
    patient = xf._build_patient(None, "PID|1||PID9||A^B||19700101|M|")
    fn = ORMO01Transformer._build_service_request
    SR_orig = fn.__globals__["ServiceRequest"]
    monkeypatch.setitem(fn.__globals__, "ServiceRequest", _SRShim)
    try:
        sr = ORMO01Transformer._build_service_request(
            orc=None,
            obr=None,
            patient=patient,
            orc_line="ORC|NW|IDX||",
            obr_line=None,
        )
    finally:
        monkeypatch.setitem(fn.__globals__, "ServiceRequest", SR_orig)

    assert sr.id == f"sr-{patient.id}"
    assert sr.identifier and sr.identifier[0].value == "IDX"
    assert sr.status == "active" and sr.intent == "order"
