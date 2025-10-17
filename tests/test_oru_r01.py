# tests/test_oru_r01.py
from __future__ import annotations

from hl7apy.parser import parse_message

from hl7_fhir_tool.transform.v2_to_fhir.oru_r01 import (
    ORUR01Transformer,
    _parse_hl7_yyyymmdd,
    _er7,
    _field_comp_from_er7,
    _find_first,
    _first_segment_line,
)


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _raw_oru(
    mshtype: str, pid: str | None, obr: str | None, obx_list: list[str]
) -> str:
    parts = [f"MSH|^~\\&|EPIC|HOSP|LIS|LAB|202501011230||{mshtype}|MSG900|P|2.5"]
    if pid is not None:
        parts.append(pid)
    if obr is not None:
        parts.append(obr)
    parts.extend(obx_list or [])
    return "\r".join(parts)


# ------------------------------------------------------------------------------
# applies()
# ------------------------------------------------------------------------------


def test_applies_true_and_false_oru_variants():
    xf = ORUR01Transformer()
    msg_yes = parse_message(_raw_oru("ORU^R01", "PID|1||X||A^B||19800101|M|", None, []))
    msg_yes_ext = parse_message(
        _raw_oru("ORU^R01^ORU_R01", "PID|1||X||A^B||19800101|M|", None, [])
    )
    msg_no = parse_message(_raw_oru("ADT^A01", "PID|1||X||A^B||19800101|M|", None, []))

    assert xf.applies(msg_yes) is True
    assert xf.applies(msg_yes_ext) is True
    assert xf.applies(msg_no) is False


def test_applies_handles_msh_exception_returns_false_oru():

    class BadMSH:
        @property
        def msh_9(self):
            raise RuntimeError("nope")

    class Msg:
        MSH = BadMSH()

    xf = ORUR01Transformer()

    assert xf.applies(Msg()) is False


def test_applies_empty_msh9_returns_false():

    class _MSH:
        msh_9 = ""

    class _Msg:
        pass

    msg = _Msg()
    msg.MSH = _MSH()
    xf = ORUR01Transformer()

    assert xf.applies(msg) is False


# ------------------------------------------------------------------------------
# _parse_hl7_yyyymmdd
# ------------------------------------------------------------------------------


def test_parse_hl7_yyyymmdd_object_to_er7_raises_returns_none():

    class Boom:
        def to_er7(self):
            raise RuntimeError("boom")

    assert _parse_hl7_yyyymmdd(Boom()) is None


# ------------------------------------------------------------------------------
# _er7()
# ------------------------------------------------------------------------------


def test_er7_exception_and_normalization_paths():

    class Boom:
        def to_er7(self):
            raise RuntimeError("nope")

    class Ok:
        def to_er7(self):
            return "  A^B  "

    assert _er7(Ok()) == "A^B"
    assert _er7(Boom()) == ""
    assert _er7(None) == ""


# ------------------------------------------------------------------------------
# _field_comp_from_er7()
# ------------------------------------------------------------------------------


def test_field_comp_from_er7_oru():

    class Dummy:
        def to_er7(self):
            return " A^B "

    line = "OBX|1|NM|GLU^Glucose|| 105  |mg/dL^milligrams per deciliter|||||F|||20250101114500|"

    assert _er7(None) == ""
    assert _er7(Dummy()) == "A^B"
    assert _field_comp_from_er7(line, 3, 1) == "GLU"
    assert _field_comp_from_er7(line, 3, 2) == "Glucose"
    assert _field_comp_from_er7(line, 5, 1) == "105"
    assert _field_comp_from_er7(line, 6, 2) == "milligrams per deciliter"
    assert _field_comp_from_er7("OBX|1|||||mg/dL", 6, 1) == "mg/dL"
    assert _field_comp_from_er7(line, 99, 1) is None
    assert _field_comp_from_er7(None, 3, 1) is None


# ------------------------------------------------------------------------------
# _first_segment_line()
# ------------------------------------------------------------------------------


def test_first_segment_line_oru():

    class DummyMsg:
        def to_er7(self):
            raise RuntimeError("boom")

    msg = parse_message(
        _raw_oru(
            "ORU^R01",
            "PID|1||ABC^^^HOSP^MR||FamName^GivName||20000101|F|",
            "OBR|1|P1|F1|GLU^Glucose|||202501011200|||||||||||||||||||||||",
            ["OBX|1|NM|GLU^Glucose||105|mg/dL|||||F|||20250101114500|"],
        )
    )

    assert _first_segment_line(msg, "PID").startswith("PID|")
    assert _first_segment_line(msg, "OBR").startswith("OBR|")
    assert _first_segment_line(msg, "OBX").startswith("OBX|")
    assert _first_segment_line(msg, "ZZZ") is None
    assert _first_segment_line(DummyMsg(), "PID") is None
    assert _find_first(msg, "PID") is not None
    assert _find_first(msg, "OBR") is not None
    assert not _find_first(msg, "ZZZ")


# ------------------------------------------------------------------------------
# _find_first()
# ------------------------------------------------------------------------------


def test_find_first_attribute_direct_child_recursive_and_missing():

    class Seg:
        def __init__(self, name):
            self.name = name
            self.children = []

    class Group:
        def __init__(self, name, children=None):
            self.name = name
            self.children = children or []

    class Root:
        def __init__(self):
            # attribute shortcut
            self.PID = Seg("PID")
            # children: direct OBR and nested OBX
            self.children = [
                Group("grp1", [Seg("ZZZ")]),
                Seg("OBR"),
                Group("grp2", [Group("nest", [Seg("OBX")])]),
            ]

    r = Root()
    got = _find_first(r, "OBX")

    assert _find_first(r, "PID") is r.PID
    assert getattr(_find_first(r, "OBR"), "name", "") == "OBR"
    assert got and getattr(got, "name", "") == "OBX"
    assert _find_first(r, "NOPE") is None


def test_find_first_treats_empty_and_len_raising_containers():

    class Seg:
        def __init__(self, name):
            self.name = name
            self.children = []

    class Group:
        def __init__(self, name, children=None):
            self.name = name
            self.children = children if children is not None else []

    class BadList(list):
        def __len__(self):
            raise RuntimeError("nope")

    class Root:
        def __init__(self):
            self.ZZZ = []
            self.children = [Seg("OBR"), Seg("PID")]
            nest = Seg("grp")
            nest.children = [Seg("OBX")]
            self.children.append(Group("wrapper", BadList([nest])))

    r = Root()

    assert _find_first(r, "ZZZ") is None
    assert getattr(_find_first(r, "PID"), "name", "") == "PID"
    assert _find_first(r, "OBX") is None


def test_find_first_attribute_children_and_child_name_exception_paths():

    class AttrBoom:
        def __getattr__(self, name):
            if name == "PID":
                raise RuntimeError("attr boom")
            return object()

        @property
        def children(self):
            return []

    class ChildrenBoom:
        PID = None

        @property
        def children(self):
            raise RuntimeError("children boom")

    class BadChild:
        @property
        def name(self):
            raise RuntimeError("name boom")

    class WithBadChild:
        def __init__(self):
            self.children = [BadChild()]

    class EmptyGroup:
        name = "grp"
        children = []

    class Root:
        def __init__(self):
            self.children = [EmptyGroup]

    assert _find_first(AttrBoom(), "PID") is None
    assert _find_first(ChildrenBoom(), "OBR") is None
    assert _find_first(WithBadChild(), "ZZZ") is None
    assert _find_first(Root(), "OBX") is None


def test_find_first_attribute_len_raises_triggers_truthy_container_path():

    class BadList(list):
        def __len__(self):
            raise RuntimeError("nope")

    class Root:
        def __init__(self):
            self.PID = BadList([object()])  # attribute shortcut path

    r = Root()

    assert _find_first(r, "PID") is r.PID


# ------------------------------------------------------------------------------
# transform()
# ------------------------------------------------------------------------------


def test_transform_obx_scan_try_except_via_monkeypatched_er7(monkeypatch):

    def _boom(_):
        raise RuntimeError("nope")

    xf = ORUR01Transformer()
    msg = parse_message(
        "MSH|^~\\&|a|b|c|d|20250101||ORU^R01|M|P|2.5\rPID|1||P0||A^B||19700101|M|"
    )
    fn = ORUR01Transformer.transform
    monkeypatch.setitem(fn.__globals__, "_er7", _boom)
    res = xf.transform(msg)

    assert len(res) == 1
    assert len(xf.transform(msg)) == 1


def test_transform_obx_scan_if_er7_returns_empty_string(monkeypatch):

    def _empty(_):
        return ""

    xf = ORUR01Transformer()
    msg = parse_message(
        "MSH|^~\\&|a|b|c|d|20250101||ORU^R01|M|P|2.5\rPID|1||E0||A^B||19700101|M|"
    )
    fn = ORUR01Transformer.transform
    real_er7 = fn.__globals__["_er7"]
    monkeypatch.setitem(fn.__globals__, "_er7", _empty)
    try:
        res = xf.transform(msg)

        assert len(res) == 1 and getattr(res[0], "id", None) == "E0"
    finally:
        monkeypatch.setitem(fn.__globals__, "_er7", real_er7)


def test_transform_children_attr_raises_then_fallback_to_obx_attribute(monkeypatch):

    class _Msg:
        def __init__(self):
            self.MSH = type("MSH", (), {"msh_9": "ORU^R01"})
            self.OBX = object()

        def to_er7(self):
            return (
                "MSH|^~\\&|A|B|C|D|20250101||ORU^R01|M|P|2.5\r"
                "PID|1||FOO||L^F||19700101|F|\r"
                "OBR|1|O|F|GLU^Glucose|||20250101101010|||||||||||||||||||||||\r"
                "OBX|1|NM|GLU^Glucose||7.5|mg/dL|||||F||||"
            )

        @property
        def children(self):
            raise RuntimeError("nope")

    xf = ORUR01Transformer()
    res = xf.transform(_Msg())

    assert len(res) == 2
    assert getattr(res[0], "id", None) == "FOO"
    assert (
        getattr(res[1], "valueQuantity", None)
        and float(res[1].valueQuantity.value) == 7.5
    )


def test_transform_child_iteration_inner_try_except_path_is_safe():

    class LeafGood:
        name = "OBX"
        children = []

    class GroupGood:
        name = "grp"
        children = [LeafGood()]

    class BadChild:
        @property
        def name(self):
            raise RuntimeError("bad-name")

        children = []

    class Msg:
        def __init__(self):
            self.MSH = type("MSH", (), {"msh_9": "ORU^R01"})
            self.children = [BadChild(), GroupGood()]

        def to_er7(self):
            return (
                "MSH|^~\\&|A|B|C|D|20250101||ORU^R01|M|P|2.5\r"
                "PID|1||OBXOK||L^F||19700101|F|\r"
                "OBR|1|O|F|GLU^Glucose|||20250101101010|||||||||||||||||||||||\r"
                "OBX|1|NM|GLU^Glucose||7.5|mg/dL|||||F||||"
            )

    xf = ORUR01Transformer()
    res = xf.transform(Msg())

    assert len(res) == 2 and getattr(res[0], "id", None) == "OBXOK"


def test_transform_children_enumeration_when_children_is_none_and_empty_lists(
    monkeypatch,
):

    class _MsgShim:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self._phase = 0
            self.MSH = wrapped.MSH
            self.PID = wrapped.PID
            self.OBR = wrapped.OBR

        def to_er7(self):
            return self._wrapped.to_er7()

        @property
        def children(self):
            # first access -> None; later -> []
            self._phase += 1
            return None if self._phase == 1 else []

    xf = ORUR01Transformer()
    msg = parse_message(
        "MSH|^~\\&|A|B|C|D|20250101||ORU^R01|M|P|2.5\r"
        "PID|1||CID||L^F||19700101|M|\r"
        "OBR|1|O|F|GLU^Glucose|||20250101111111|||||||||||||||||||||||\r"
        "OBX|1|NM|GLU^Glucose||1.0|mg/dL|||||F||||"
    )
    shim = _MsgShim(msg)
    res = xf.transform(shim)

    assert len(res) == 2
    assert res[1].code and res[1].code.text == "Glucose"


def test_transform_children_paths_multiple_levels_and_fallback_single_obx_attribute(
    monkeypatch,
):

    class Dummy:
        def __init__(self, name, children=None):
            self.name = name
            self.children = children or []

    class MsgShim:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self._phase = 0
            self.MSH = wrapped.MSH
            self.PID = wrapped.PID
            self.OBR = wrapped.OBR
            self.OBX = Dummy("OBX")

        def to_er7(self):
            return self._wrapped.to_er7()

        @property
        def children(self):
            if self._phase == 0:
                self._phase = 1
                direct = Dummy("OBX")
                deep_leaf = Dummy("OBX")
                nested = Dummy("grp", [Dummy("mid", [deep_leaf])])
                via_child = Dummy("grp", [Dummy("OBX")])
                return [Dummy("junk"), direct, via_child, nested]
            return []

    base = parse_message(
        "MSH|^~\\&|A|B|C|D|20250101||ORU^R01|M|P|2.5\r"
        "PID|1||C1||L^F||19700101|M|\r"
        "OBR|1|PO|FO|TST^Thing|||20250101123456|||||||||||||||||||||||\r"
        "OBX|1|NM|TST^Thing||7|u|||||F||||"
    )
    xf = ORUR01Transformer()
    shim = MsgShim(base)
    res = xf.transform(shim)

    assert len(res) == 2
    assert res[1].code and res[1].code.text == "Thing"


def test_transform_non_nm_but_numeric_yields_quantity_without_units():
    xf = ORUR01Transformer()
    msg = parse_message(
        "MSH|^~\\&|a|b|c|d|20250101||ORU^R01|M|P|2.5\r"
        "PID|1||QX||L^F||19800101|U|\r"
        "OBR|1|O2|F2|NOTE^Comment|||20250101111111|||||||||||||||||||||||\r"
        "OBX|1|ST|NOTE^Comment||42|||||F||||"
    )
    resources = xf.transform(msg)
    obs = resources[1]

    assert hasattr(obs, "valueQuantity")
    assert float(obs.valueQuantity.value) == 42.0
    assert getattr(obs.valueQuantity, "unit", None) in (None, "")


def test_transform_nested_obx_and_direct_obx_try_except_paths(monkeypatch):

    class _Msg:
        def __init__(self):
            self.MSH = type("MSH", (), {"msh_9": "ORU^R01"})
            self._first = True
            self._second = True
            self.children = []

        def __getattr__(self, name):
            if name == "PATIENT_RESULT" and self._first:
                self._first = False
                raise RuntimeError("boom PR")
            if name == "OBX" and self._second:
                self._second = False
                raise RuntimeError("boom OBX")
            return None

        def to_er7(self):
            return (
                "MSH|^~\\&|A|B|C|D|20250101121212||ORU^R01|MSG|P|2.5\r"
                "PID|1||Z1||L^F||19700101|M|\r"
                "OBR|1|O|F|GLU^Glucose|||20250101101010\r"
                "OBX|1|NM|GLU^Glucose||7.0|mg/dL|||||F||||"
            )

    xf = ORUR01Transformer()
    msg = _Msg()
    res = xf.transform(msg)

    assert isinstance(res, list) and len(res) >= 1
    assert any(getattr(r, "id", "").startswith("Z1") for r in res)


def test_transform_nested_obx_false_branches():

    class _Oo:
        def __init__(self, obx):
            self.OBX = obx

    class _Grp:
        def __init__(self, order_obs):
            self.ORDER_OBSERVATION = order_obs

    class _Msg:
        def __init__(self):
            self.MSH = type("MSH", (), {"msh_9": "ORU^R01"})
            self.children = []
            self.OBX = None
            self.PATIENT_RESULT = [_Grp(None), _Grp([_Oo([])])]

        def to_er7(self):
            return (
                "MSH|^~\\&|A|B|C|D|20250101131313||ORU^R01|MSG|P|2.5\r"
                "PID|1||Z4||L^F||19700101|M|\r"
                "OBR|1|O|F|GLU^Glucose|||20250101101010\r"
                "OBX|1|NM|GLU^Glucose||7.0|mg/dL|||||F||||"
            )

    xf = ORUR01Transformer()
    res = xf.transform(_Msg())

    assert isinstance(res, list)
    assert any(getattr(r, "id", "").startswith("Z4") for r in res)


def test_transform_nested_obx():

    class _Obx:
        pass

    class _Oo:
        def __init__(self):
            self.OBX = [_Obx()]

    class _Grp:
        def __init__(self):
            self.ORDER_OBSERVATION = [_Oo()]

    class _Msg:
        def __init__(self):
            self.MSH = type("MSH", (), {"msh_9": "ORU^R01"})
            self.children = []
            self.OBX = None
            self.PATIENT_RESULT = [_Grp()]

        def to_er7(self):
            return (
                "MSH|^~\\&|A|B|C|D|20250101141414||ORU^R01|MSG|P|2.5\r"
                "PID|1||Z5||L^F||19700101|M|\r"
                "OBR|1|O|F|GLU^Glucose|||20250101101010\r"
                "OBX|1|NM|GLU^Glucose||7.0|mg/dL|||||F||||"
            )

    xf = ORUR01Transformer()
    res = xf.transform(_Msg())

    assert isinstance(res, list) and len(res) >= 1
    assert any(getattr(r, "id", "").startswith("Z5") for r in res)


# ------------------------------------------------------------------------------
# _build_patient()
# ------------------------------------------------------------------------------


def test_build_patient_pid3_first_rep_none_triggers_pid_line_fallback():

    class Pid:
        pass

    pid = Pid()
    pid.pid_3 = [None]
    pid_line = "PID|1||FALLBACKID||Last^First||19700101|M|"
    p = ORUR01Transformer._build_patient(pid, pid_line)

    assert p.id == "FALLBACKID"


def test_build_patient_pid5_structured_missing_fam_and_giv():

    class Rep:
        family_name = None
        given_name = None

    class Pid:
        def __init__(self):
            self.pid_5 = [Rep()]

    pid_line = "PID|1||EDGE488||^||19700101|M|"
    p = ORUR01Transformer._build_patient(Pid(), pid_line)

    assert getattr(p, "id", None) == "EDGE488"
    assert not getattr(p, "name", None)


def test_build_patient_parity_subset_from_pid_and_raw():

    class _V:
        def __init__(self, s):
            self.s = s

        def to_er7(self):
            return self.s

    class Pid:
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

    p1 = ORUR01Transformer._build_patient(Pid(), None)
    raw = "PID|1||RAWID^^^HOSP^MR||Fam^Giv||19700101|M|"
    p2 = ORUR01Transformer._build_patient(None, raw)

    assert p1.id == "COMPID123"
    assert p1.name[0].family == "CompFamily" and p1.name[0].given == ["CompGiven"]
    assert str(p1.birthDate) == "1984-02-29" and p1.gender == "female"
    assert p2.id == "RAWID"
    assert p2.name[0].family == "Fam" and p2.name[0].given == ["Giv"]
    assert str(p2.birthDate) == "1970-01-01" and p2.gender == "male"


def test_build_patient_first_rep_len_raises_and_early_return_none_pid():

    class BadSeq(list):
        def __len__(self):
            raise RuntimeError("nope")

    class Pid:
        pass

    pid = Pid()
    pid.pid_3 = BadSeq([object()])
    p1 = ORUR01Transformer._build_patient(pid, None)
    p2 = ORUR01Transformer._build_patient(None, None)

    assert getattr(p1, "id", None) in (None, "")
    assert p2 is not None


def test_build_patient_name_only_family_name_only_given_name_gender_unknown_and_birthdate_raw():
    p1 = ORUR01Transformer._build_patient(None, "PID|1||X||FamOnly^||19800101|X|")
    p2 = ORUR01Transformer._build_patient(None, "PID|1||X||^GivenOnly||19800101|U|")

    assert p1.name and p1.name[0].family == "FamOnly"
    assert getattr(p1, "gender", None) == "unknown"
    assert str(p1.birthDate) == "1980-01-01"
    assert p2.name and p2.name[0].given and p2.name[0].given[0] == "GivenOnly"


def test_build_patient_id_setter_exception_path(monkeypatch):

    class _PatientShim:
        def __init__(self, *a, **k):
            self._id = None
            self.name = None
            self.birthDate = None
            self.gender = None

        @property
        def id(self):
            return self._id

        @id.setter
        def id(self, v):
            raise ValueError("reject id")

    fn = ORUR01Transformer._build_patient
    Patient_orig = fn.__globals__["Patient"]
    try:
        monkeypatch.setitem(fn.__globals__, "Patient", _PatientShim)
        p = ORUR01Transformer._build_patient(None, "PID|1||PIDX||Fam^Giv||19700101|M|")

        assert getattr(p, "id", None) is None
        assert p.name and p.name[0].family == "Fam"
    finally:
        monkeypatch.setitem(fn.__globals__, "Patient", Patient_orig)


# ------------------------------------------------------------------------------
# _build_observation()
# ------------------------------------------------------------------------------


def test_build_observation_value_from_obx5_rep_and_constructs_observation():

    class Obx:
        def __init__(self):
            self.obx_5 = ["3.16"]  # v5 from repeated field; numeric NM path

    patient = ORUR01Transformer._build_patient(None, "PID|1||OBX5REP||L^F||19700101|F|")
    obs = ORUR01Transformer._build_observation(
        obr=None,
        obx=Obx(),
        patient=patient,
        obr_line="OBR|1|O|F|X^Y|||20250102131313",
        obx_line="OBX|1|NM|X^Y|||||||F||||",  # no v5 in line -> pull from obx_5 rep
        ordinal=2,
    )

    assert (
        getattr(obs, "valueQuantity", None) and float(obs.valueQuantity.value) == 3.16
    )


def test_build_observation_identifiers_from_structured_obr(monkeypatch):

    class Token:
        def __init__(self, val):
            self._val = val

        def to_er7(self):
            return self._val

    class Obr:
        obr_2 = [Token("PL2-DIAG")]
        obr_3 = None

    def _diag_er7(x):
        return real_er7(x)

    obx_line = "OBX|1|ST|NOTE^Comment||hello|||||F||||"
    obr_line = "OBR|1||||||20250101101010"
    patient = ORUR01Transformer._build_patient(
        None, "PID|1||PDIAG||Last^First||19700101|F|"
    )
    fn = ORUR01Transformer._build_observation
    real_er7 = fn.__globals__["_er7"]
    monkeypatch.setitem(fn.__globals__, "_er7", _diag_er7)
    obs = ORUR01Transformer._build_observation(
        obr=Obr(),
        obx=None,
        patient=patient,
        obr_line=obr_line,
        obx_line=obx_line,
        ordinal=1,
    )
    vals = [getattr(i, "value", None) for i in obs.identifier]

    assert getattr(obs, "identifier", None)
    assert "PL2-DIAG" in vals


def test_build_observation_code_fallback_when_structured_obx3_empty():

    class Obx:
        obx_3 = []

    patient = ORUR01Transformer._build_patient(None, "PID|1||PID5||L^F||19700101|F|")
    obs = ORUR01Transformer._build_observation(
        obr=None,
        obx=Obx(),
        patient=patient,
        obr_line="OBR|1||||||20250103123456",
        obx_line="OBX|1|ST||||||||F||||",
        ordinal=1,
    )

    assert getattr(obs, "code", None)
    assert obs.code.text == "Unspecified Observation"
    assert not getattr(obs.code, "coding", None)


def test_build_observation_effective_dt_skips_on_invalid_dateonly():
    patient = ORUR01Transformer._build_patient(None, "PID|1||PIDZ||L^F||19700101|F|")
    obs = ORUR01Transformer._build_observation(
        obr=None,
        obx=None,
        patient=patient,
        obr_line="OBR|1||||||20251340",
        obx_line="OBX|1|NM|GLU^Glucose||5.5|mg/dL|||||F||||",
        ordinal=1,
    )

    assert obs is not None
    assert getattr(obs, "effectiveDateTime", None) in (None, "")


def test_build_observation_obx3_missing_attr():

    class Obx3:
        pass

    patient = ORUR01Transformer._build_patient(
        None, "PID|1||PX||Last^First||19700101|M|"
    )
    obx_stub = Obx3()
    obx_line = "OBX|1|NM|||4.2|mg/dL|||||F||||"
    obr_line = "OBR|1|P|F|X^Y|||20250102101010|||||||||||||||||||||||"
    obs = ORUR01Transformer._build_observation(
        obr=None,
        obx=obx_stub,
        patient=patient,
        obr_line=obr_line,
        obx_line=obx_line,
        ordinal=1,
    )

    assert getattr(obs, "code", None) is not None
    assert obs.code.text == "Unspecified Observation"
    assert not getattr(obs.code, "coding", None)


def test_build_observation_value_block_error_log(monkeypatch, caplog):

    def _flaky(line, field_index, comp_index):
        if field_index in (2, 5, 6):
            raise RuntimeError("nope-value")
        return real_field(line, field_index, comp_index)

    fn = ORUR01Transformer._build_observation
    real_field = fn.__globals__["_field_comp_from_er7"]
    monkeypatch.setitem(fn.__globals__, "_field_comp_from_er7", _flaky)
    try:
        patient = ORUR01Transformer._build_patient(None, "PID|1||VB1||L^F||19700101|F|")
        with caplog.at_level("ERROR"):
            obs = ORUR01Transformer._build_observation(
                obr=None,
                obx=None,
                patient=patient,
                obr_line="OBR|1|O|F|X^Y|||20250103",
                obx_line="OBX|1|NM|X^Y||3.14|mg/dL|||||F||||",
                ordinal=1,
            )

        assert obs is not None
        assert any(
            "Error parsing OBX-5/6 for value" in r.message for r in caplog.records
        )
    finally:
        monkeypatch.setitem(fn.__globals__, "_field_comp_from_er7", real_field)


def test_build_observation_init_retry_when_code_or_value_cause_failure(monkeypatch):

    class _ObsShim:
        def __init__(self, *args, **kwargs):
            if kwargs.get("code") is not None:
                raise ValueError("boom")
            for k, v in kwargs.items():
                setattr(self, k, v)

    fn = ORUR01Transformer._build_observation
    Obs_orig = fn.__globals__["Observation"]
    monkeypatch.setitem(fn.__globals__, "Observation", _ObsShim)
    try:
        patient = ORUR01Transformer._build_patient(None, "PID|1||P9||X^Y||19700101|M|")
        obs = ORUR01Transformer._build_observation(
            obr=None,
            obx=None,
            patient=patient,
            obr_line=None,
            obx_line="OBX|1|ST|NOTE^Comment||hello|||||F||||",
            ordinal=1,
        )
    finally:
        monkeypatch.setitem(fn.__globals__, "Observation", Obs_orig)

    assert getattr(obs, "status", None) == "final"
    assert getattr(obs, "id", None) == "obs-P9-1"


def test_build_observation_identifier_obx3_and_effective_dt_error_paths(monkeypatch):

    class _ObsShim:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
            self.id = None

    fn = ORUR01Transformer._build_observation
    Obs_orig = fn.__globals__["Observation"]
    try:
        monkeypatch.setitem(fn.__globals__, "Observation", _ObsShim)

        class ObrBad:
            def __getattr__(self, name):
                if name in ("obr_2", "obr_3"):
                    raise RuntimeError("OBR attr boom")
                raise AttributeError

        class ObxBad:
            @property
            def obx_3(self):
                raise RuntimeError("OBX3 boom")

        patient = ORUR01Transformer._build_patient(None, "PID|1||PX||L^F||19700101|U|")
        obs = ORUR01Transformer._build_observation(
            obr=ObrBad(),
            obx=ObxBad(),
            patient=patient,
            obr_line=object(),
            obx_line="OBX|1|NM|||notnum|u|||||F||||",
            ordinal=1,
        )

        assert getattr(obs, "status", None) == "final"
        assert getattr(obs, "subject", None) and obs.subject.reference.endswith("/PX")
        assert getattr(obs, "code", None) and obs.code.text
        assert getattr(obs, "effectiveDateTime", None) in (None, "")
    finally:
        monkeypatch.setitem(fn.__globals__, "Observation", Obs_orig)


def test_build_observation_id_setter_exception_branch(monkeypatch):

    class _ObsShim:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
            self._once = False
            self._id = None

        @property
        def id(self):
            return self._id

        @id.setter
        def id(self, v):
            if not self._once:
                self._once = True
                raise ValueError("reject id")
            self._id = v

    fn = ORUR01Transformer._build_observation
    Obs_orig = fn.__globals__["Observation"]
    try:
        monkeypatch.setitem(fn.__globals__, "Observation", _ObsShim)
        patient = ORUR01Transformer._build_patient(None, "PID|1||IID||L^F||19700101|U|")
        obs = ORUR01Transformer._build_observation(
            obr=None,
            obx=None,
            patient=patient,
            obr_line="OBR|1||||||20250101111111|||||||||||||||||||||||",
            obx_line="OBX|1|ST|NOTE^Comment||ok|||||F||||",
            ordinal=3,
        )

        assert getattr(obs, "id", None) is None or obs.id.startswith("obs-")
    finally:
        monkeypatch.setitem(fn.__globals__, "Observation", Obs_orig)


def test_build_observation_constructor_other_exception_is_re_raised(monkeypatch):

    class _BoomObs:
        def __init__(self, **kw):
            raise TypeError("bad args")

    fn = ORUR01Transformer._build_observation
    Obs_orig = fn.__globals__["Observation"]
    try:
        monkeypatch.setitem(fn.__globals__, "Observation", _BoomObs)
        patient = ORUR01Transformer._build_patient(None, "PID|1||AA1||L^F||19700101|M|")
        exc = None
        try:
            ORUR01Transformer._build_observation(
                obr=None,
                obx=None,
                patient=patient,
                obr_line="OBR|1||||||20250101111111",
                obx_line="OBX|1|ST|NOTE^Comment||ok|||||F||||",
                ordinal=1,
            )
        except TypeError as e:
            exc = e

        assert exc is not None, "TypeError was not raised"
        assert str(exc) == "bad args", f"Unexpected error message: {exc}"
    finally:
        monkeypatch.setitem(fn.__globals__, "Observation", Obs_orig)


def test_build_observation_first_rep_len_raises_via_obx6_units_path(monkeypatch):

    class BadSeq(list):
        def __len__(self):
            raise RuntimeError("nope")

    class U6Obj:
        def __init__(self):
            self.text = "u-badseq"

    class Obx:
        def __init__(self):
            self.obx_6 = BadSeq([U6Obj()])

    class _ObsShim:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
            self.id = None

    fn = ORUR01Transformer._build_observation
    Obs_orig = fn.__globals__["Observation"]
    try:
        monkeypatch.setitem(fn.__globals__, "Observation", _ObsShim)
        patient = ORUR01Transformer._build_patient(None, "PID|1||OX6||L^F||19700101|F|")
        obs = ORUR01Transformer._build_observation(
            obr=None,
            obx=Obx(),
            patient=patient,
            obr_line="OBR|1||||||20250101101010",
            obx_line="OBX|1|NM|X^Y||2.5|||||F||||",
            ordinal=1,
        )

        assert obs.valueQuantity and float(obs.valueQuantity.value) == 2.5
        assert getattr(obs.valueQuantity, "unit", None) is None
    finally:
        monkeypatch.setitem(fn.__globals__, "Observation", Obs_orig)
