# tests/test_dg1.py
"""
Tests for hl7_fhir_tool/transform/v2_to_fhir/_dg1.py
"""
from __future__ import annotations

import types


import hl7_fhir_tool.transform.v2_to_fhir._dg1 as mod
from hl7_fhir_tool.transform.v2_to_fhir._dg1 import (
    _DEFAULT_SYSTEM,
    _build_condition_from_dg1,
    _dg1_er7_lines,
    _er7,
    _field_comp_from_er7,
    _find_dg1_segments,
    _resolve_system,
    build_conditions,
)


# ------------------------------------------------------------------------------
# _er7
# ------------------------------------------------------------------------------


def test_er7_none():
    assert _er7(None) == ""


def test_er7_with_to_er7():
    obj = types.SimpleNamespace()
    obj.to_er7 = lambda: "  E11.9  "
    assert _er7(obj) == "E11.9"


def test_er7_str_fallback():
    assert _er7("E11.9") == "E11.9"


def test_er7_exception_returns_empty():
    class Boom:
        def to_er7(self):
            raise RuntimeError("boom")

    assert _er7(Boom()) == ""


# ------------------------------------------------------------------------------
# _field_comp_from_er7
# ------------------------------------------------------------------------------


def test_field_comp_from_er7_valid_extractions():
    line = "DG1|1||E11.9^Type 2 diabetes^I10|||F"
    assert _field_comp_from_er7(line, 3, 1) == "E11.9"
    assert _field_comp_from_er7(line, 3, 2) == "Type 2 diabetes"
    assert _field_comp_from_er7(line, 3, 3) == "I10"


def test_field_comp_from_er7_none_input():
    assert _field_comp_from_er7(None, 3, 1) is None


def test_field_comp_from_er7_empty_string():
    assert _field_comp_from_er7("", 3, 1) is None


def test_field_comp_from_er7_field_out_of_range():
    assert _field_comp_from_er7("DG1|1||E11.9", 99, 1) is None


def test_field_comp_from_er7_field_index_zero():
    assert _field_comp_from_er7("DG1|1||E11.9", 0, 1) is None


def test_field_comp_from_er7_comp_out_of_range():
    assert _field_comp_from_er7("DG1|1||E11.9", 3, 99) is None


def test_field_comp_from_er7_comp_index_zero():
    assert _field_comp_from_er7("DG1|1||E11.9", 3, 0) is None


def test_field_comp_from_er7_empty_value_returns_none():
    line = "DG1|1||^Type 2 diabetes^I10"
    assert _field_comp_from_er7(line, 3, 1) is None


# ------------------------------------------------------------------------------
# _resolve_system
# ------------------------------------------------------------------------------


def test_resolve_system_i10():
    assert _resolve_system("I10") == "http://hl7.org/fhir/sid/icd-10"


def test_resolve_system_icd10():
    assert _resolve_system("ICD10") == "http://hl7.org/fhir/sid/icd-10"


def test_resolve_system_icd_dash_10():
    assert _resolve_system("ICD-10") == "http://hl7.org/fhir/sid/icd-10"


def test_resolve_system_i9():
    assert _resolve_system("I9") == "http://hl7.org/fhir/sid/icd-9-cm"


def test_resolve_system_icd9():
    assert _resolve_system("ICD9") == "http://hl7.org/fhir/sid/icd-9-cm"


def test_resolve_system_unknown_falls_back_to_default():
    assert _resolve_system("SNOMED") == _DEFAULT_SYSTEM


def test_resolve_system_none():
    assert _resolve_system(None) == _DEFAULT_SYSTEM


def test_resolve_system_empty_string():
    assert _resolve_system("") == _DEFAULT_SYSTEM


def test_resolve_system_case_insensitive():
    assert _resolve_system("i10") == "http://hl7.org/fhir/sid/icd-10"


# ------------------------------------------------------------------------------
# _dg1_er7_lines
# ------------------------------------------------------------------------------


def test_dg1_er7_lines_single():
    msg = types.SimpleNamespace()
    msg.to_er7 = lambda: "MSH|...\rPID|1\rDG1|1||E11.9^Diabetes^I10\r"
    lines = _dg1_er7_lines(msg)
    assert lines == ["DG1|1||E11.9^Diabetes^I10"]


def test_dg1_er7_lines_multiple():
    msg = types.SimpleNamespace()
    msg.to_er7 = lambda: "MSH|...\rDG1|1||E11.9^Diabetes^I10\rDG1|2||I21^AMI^I10\r"
    lines = _dg1_er7_lines(msg)
    assert len(lines) == 2
    assert lines[0].startswith("DG1|1")
    assert lines[1].startswith("DG1|2")


def test_dg1_er7_lines_none_present():
    msg = types.SimpleNamespace()
    msg.to_er7 = lambda: "MSH|...\rPID|1\r"
    assert _dg1_er7_lines(msg) == []


def test_dg1_er7_lines_no_to_er7():
    msg = types.SimpleNamespace()
    assert _dg1_er7_lines(msg) == []


def test_dg1_er7_lines_to_er7_raises():
    class Boom:
        def to_er7(self):
            raise RuntimeError("boom")

    assert _dg1_er7_lines(Boom()) == []


def test_dg1_er7_lines_lf_line_endings():
    msg = types.SimpleNamespace()
    msg.to_er7 = lambda: "MSH|...\nDG1|1||E11.9^Diabetes^I10\n"
    lines = _dg1_er7_lines(msg)
    assert len(lines) == 1
    assert lines[0].startswith("DG1")


# ------------------------------------------------------------------------------
# _find_dg1_segments
# ------------------------------------------------------------------------------


def test_find_dg1_segments_single_attribute():
    seg = types.SimpleNamespace(name="DG1")
    msg = types.SimpleNamespace(DG1=seg)
    assert _find_dg1_segments(msg) == [seg]


def test_find_dg1_segments_list_attribute():
    s1 = types.SimpleNamespace(name="DG1")
    s2 = types.SimpleNamespace(name="DG1")
    msg = types.SimpleNamespace(DG1=[s1, s2])
    assert _find_dg1_segments(msg) == [s1, s2]


def test_find_dg1_segments_list_filters_none():
    s1 = types.SimpleNamespace(name="DG1")
    msg = types.SimpleNamespace(DG1=[s1, None])
    assert _find_dg1_segments(msg) == [s1]


def test_find_dg1_segments_via_children():
    dg1 = types.SimpleNamespace(name="DG1")
    pid = types.SimpleNamespace(name="PID")
    msg = types.SimpleNamespace(DG1=None, children=[pid, dg1])
    result = _find_dg1_segments(msg)
    assert dg1 in result


def test_find_dg1_segments_no_dg1_returns_empty():
    msg = types.SimpleNamespace(DG1=None, children=[])
    assert _find_dg1_segments(msg) == []


def test_find_dg1_segments_attribute_raises_falls_to_children():
    class BadMsg:
        @property
        def DG1(self):
            raise RuntimeError("boom")

        children = []

    assert _find_dg1_segments(BadMsg()) == []


def test_find_dg1_segments_children_raises_returns_empty():
    class BadMsg:
        DG1 = None

        @property
        def children(self):
            raise RuntimeError("boom")

    assert _find_dg1_segments(BadMsg()) == []


def test_find_dg1_segments_child_getattr_raises_skipped():
    class BadChild:
        @property
        def name(self):
            raise RuntimeError("boom")

    msg = types.SimpleNamespace(DG1=None, children=[BadChild()])
    assert _find_dg1_segments(msg) == []


# ------------------------------------------------------------------------------
# _build_condition_from_dg1
# ------------------------------------------------------------------------------


def test_build_condition_from_dg1_full_er7_line():
    line = "DG1|1||E11.9^Type 2 diabetes^I10|||F"
    cond = _build_condition_from_dg1(None, line, "p1", 1)
    assert cond is not None
    assert cond.id == "cond-p1-1"
    assert cond.subject.reference == "Patient/p1"
    assert cond.code.coding[0].code == "E11.9"
    assert cond.code.coding[0].system == "http://hl7.org/fhir/sid/icd-10"
    assert cond.code.text == "Type 2 diabetes"


def test_build_condition_from_dg1_no_code_returns_none():
    line = "DG1|1||||F"
    assert _build_condition_from_dg1(None, line, "p1", 1) is None


def test_build_condition_from_dg1_no_line_no_seg_returns_none():
    assert _build_condition_from_dg1(None, None, "p1", 1) is None


def test_build_condition_from_dg1_default_system_when_no_system():
    line = "DG1|1||E11.9^Diabetes"
    cond = _build_condition_from_dg1(None, line, "p1", 1)
    assert cond is not None
    assert cond.code.coding[0].system == _DEFAULT_SYSTEM


def test_build_condition_from_dg1_icd9_system():
    line = "DG1|1||250.00^Diabetes^I9|||F"
    cond = _build_condition_from_dg1(None, line, "p1", 1)
    assert cond is not None
    assert cond.code.coding[0].system == "http://hl7.org/fhir/sid/icd-9-cm"


def test_build_condition_from_dg1_ordinal_in_id():
    line = "DG1|2||I21^AMI^I10|||F"
    cond = _build_condition_from_dg1(None, line, "p99", 2)
    assert cond is not None
    assert cond.id == "cond-p99-2"


def test_build_condition_from_dg1_structured_fallback_for_code():
    # No ER7 line; code extracted via structured attribute
    ident = types.SimpleNamespace()
    ident.to_er7 = lambda: "E11.9"
    dg1_3 = types.SimpleNamespace(
        identifier=ident, text=None, name_of_coding_system=None
    )
    dg1_seg = types.SimpleNamespace(dg1_3=dg1_3)
    cond = _build_condition_from_dg1(dg1_seg, None, "p1", 1)
    assert cond is not None
    assert cond.code.coding[0].code == "E11.9"


def test_build_condition_from_dg1_structured_access_raises_returns_none():
    class BoomSeg:
        @property
        def dg1_3(self):
            raise RuntimeError("boom")

    assert _build_condition_from_dg1(BoomSeg(), None, "p1", 1) is None


def test_build_condition_from_dg1_construct_fallback(monkeypatch):
    class OnlyConstruct:
        @classmethod
        def construct(cls):
            obj = object.__new__(cls)
            return obj

        def __setattr__(self, k, v):
            object.__setattr__(self, k, v)

    monkeypatch.setattr(mod, "Condition", OnlyConstruct, raising=True)
    line = "DG1|1||E11.9^Diabetes^I10|||F"
    cond = _build_condition_from_dg1(None, line, "p1", 1)
    assert cond is not None


def test_build_condition_from_dg1_no_text_when_absent():
    line = "DG1|1||E11.9"
    cond = _build_condition_from_dg1(None, line, "p1", 1)
    assert cond is not None
    assert cond.code.text is None


def test_build_condition_from_dg1_text_access_raises():
    class BoomText:
        @property
        def text(self):
            raise RuntimeError("boom text")

        identifier = None
        ce_1 = None
        cwe_1 = None

    seg = types.SimpleNamespace(dg1_3=BoomText())
    line = "DG1|1||E11.9"
    cond = _build_condition_from_dg1(seg, line, "p1", 1)
    assert cond is not None
    assert cond.code.coding[0].code == "E11.9"


def test_build_condition_from_dg1_system_access_raises():
    class BoomSystem:
        @property
        def name_of_coding_system(self):
            raise RuntimeError("boom system")

        identifier = None
        ce_1 = None
        cwe_1 = None
        text = None
        ce_2 = None
        cwe_2 = None

    seg = types.SimpleNamespace(dg1_3=BoomSystem())
    line = "DG1|1||E11.9^Diabetes"
    cond = _build_condition_from_dg1(seg, line, "p1", 1)
    assert cond is not None
    assert cond.code.coding[0].code == "E11.9"


def test_build_condition_from_dg1_empty_list_no_er7_line():
    seg = types.SimpleNamespace(dg1_3=[])
    cond = _build_condition_from_dg1(seg, None, "p1", 1)
    assert cond is None


def test_build_condition_from_dg1_empty_list_in_text_and_system_blocks():
    seg = types.SimpleNamespace(dg1_3=[])
    line = "DG1|1||E11.9"  # no text or system components in ER7 line
    cond = _build_condition_from_dg1(seg, line, "p1", 1)
    assert cond is not None
    assert cond.code.coding[0].code == "E11.9"
    assert cond.code.text is None
    assert cond.code.coding[0].system == _DEFAULT_SYSTEM


# ------------------------------------------------------------------------------
# build_conditions
# ------------------------------------------------------------------------------


def test_build_conditions_single_dg1():
    msg = types.SimpleNamespace()
    msg.to_er7 = lambda: "MSH\rPID\rDG1|1||E11.9^Diabetes^I10|||F\r"
    conditions = build_conditions(msg, "p1")
    assert len(conditions) == 1
    assert conditions[0].code.coding[0].code == "E11.9"
    assert conditions[0].subject.reference == "Patient/p1"


def test_build_conditions_multiple_dg1():
    msg = types.SimpleNamespace()
    msg.to_er7 = lambda: "MSH\rDG1|1||E11.9^Diabetes^I10\rDG1|2||I21^AMI^I10\r"
    conditions = build_conditions(msg, "p2")
    assert len(conditions) == 2
    codes = {c.code.coding[0].code for c in conditions}
    assert codes == {"E11.9", "I21"}


def test_build_conditions_no_dg1_returns_empty():
    msg = types.SimpleNamespace()
    msg.to_er7 = lambda: "MSH\rPID\rPV1\r"
    assert build_conditions(msg, "p1") == []


def test_build_conditions_dg1_without_code_skipped():
    msg = types.SimpleNamespace()
    msg.to_er7 = lambda: "MSH\rDG1|1||||\r"
    assert build_conditions(msg, "p1") == []


def test_build_conditions_no_to_er7_returns_empty():
    msg = types.SimpleNamespace()
    assert build_conditions(msg, "p1") == []


def test_build_conditions_ids_are_stable_and_ordered():
    msg = types.SimpleNamespace()
    msg.to_er7 = lambda: "MSH\rDG1|1||E11.9^D1^I10\rDG1|2||I21^D2^I10\r"
    conditions = build_conditions(msg, "pat-1")
    assert conditions[0].id == "cond-pat-1-1"
    assert conditions[1].id == "cond-pat-1-2"
