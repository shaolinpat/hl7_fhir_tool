# tests/test_adt_a01.py
"""
Tests for ADTA01Transformer (ADT^A01 v2 -> FHIR Patient/Encounter).

Covers:
- applies() truth table across correct/mismatched/missing MSH-9
- transform() returns Patient and Encounter in all cases
- PID parsing: identifier, name (family/given), birthDate normalization
- Gender mapping M/F/O/U and fallback behavior
- Robustness: missing segments, odd value formats, safe string conversion
"""

import sys
import importlib
import types as pytypes
from dataclasses import dataclass

import pytest
from hl7apy.core import Message

from hl7_fhir_tool.transform.v2_to_fhir.adt_a01 import (
    ADTA01Transformer,
    _safe_str,
    _get_trigger,
    _seq_len_safe,
    _pid_identifier,
    _pid_name,
    _pid_birthdate,
    _pid_gender,
)

# also import the module for targeted monkeypatch in specific tests
import hl7_fhir_tool.transform.v2_to_fhir.adt_a01 as mod

_REAL_REGISTRY_MOD = importlib.import_module("hl7_fhir_tool.transform.registry")

# ------------------------------------------------------------------------------
# Lightweight HL7-like stubs
# ------------------------------------------------------------------------------


class _WithToEr7:
    def __init__(self, v):
        self.v = v

    def to_er7(self):
        return self.v


class _BoomToEr7:
    def to_er7(self):
        raise ValueError("boom")


class _IdComp:
    def __init__(self, id_number):
        self.id_number = id_number


class _NameComp:
    def __init__(self, family=None, given=None):
        self.family_name = family
        self.given_name = given


@dataclass
class _MSH:
    msh_9: object = None


@dataclass
class _PID:
    pid_3: object = None
    pid_5: object = None
    pid_7: object = None
    pid_8: object = None


@dataclass
class _PV1:
    pv1_2: object = None
    pv1_44: object = None


@dataclass
class _Msg:
    MSH: object = None
    PID: object = None
    PV1: object = None
    pid: object = None
    pv1: object = None


# ------------------------------------------------------------------------------
# Helpers: re-import adt_a01 safely to cover import-time branches
# ------------------------------------------------------------------------------


def _install_fake_fhir_modules(assign_raises: bool):
    fhir = pytypes.ModuleType("fhir")
    resources = pytypes.ModuleType("fhir.resources")
    patient = pytypes.ModuleType("fhir.resources.patient")
    encounter = pytypes.ModuleType("fhir.resources.encounter")

    if assign_raises:

        class RaisingObj:
            def __setattr__(self, name, value):
                raise RuntimeError("boom")

        patient.Patient = RaisingObj()
        encounter.Encounter = RaisingObj()
    else:
        patient.Patient = pytypes.SimpleNamespace()
        encounter.Encounter = pytypes.SimpleNamespace()

    sys.modules["fhir"] = fhir
    sys.modules["fhir.resources"] = resources
    sys.modules["fhir.resources.patient"] = patient
    sys.modules["fhir.resources.encounter"] = encounter


def _uninstall_fake_fhir_modules():
    for k in (
        "fhir.resources.encounter",
        "fhir.resources.patient",
        "fhir.resources",
        "fhir",
    ):
        sys.modules.pop(k, None)


def _install_fake_registry_module():
    fake = pytypes.ModuleType("hl7_fhir_tool.transform.registry")

    def register(event):
        def deco(cls):
            return cls  # no-op; avoids duplicate registration error on re-import

        return deco

    fake.register = register
    sys.modules["hl7_fhir_tool.transform.registry"] = fake


def _restore_real_registry_module():
    sys.modules["hl7_fhir_tool.transform.registry"] = _REAL_REGISTRY_MOD


def _reimport_adt_a01_for_import_branch(assign_raises: bool):
    _install_fake_fhir_modules(assign_raises=assign_raises)
    _install_fake_registry_module()
    try:
        sys.modules.pop("hl7_fhir_tool.transform.v2_to_fhir.adt_a01", None)
        fresh = importlib.import_module("hl7_fhir_tool.transform.v2_to_fhir.adt_a01")
        return fresh
    finally:
        _uninstall_fake_fhir_modules()
        _restore_real_registry_module()


# ------------------------------------------------------------------------------
# Normalizers so asserts work with real fhir.resources models
# ------------------------------------------------------------------------------


def _ident_values(patient):
    """Return list of identifier.value (works for FHIR models or dicts)."""
    out = []
    items = getattr(patient, "identifier", None)
    if not items:
        return out
    for it in items:
        if isinstance(it, dict):
            out.append(it.get("value"))
        else:
            out.append(getattr(it, "value", None))
    return out


def _name_as_dicts(patient):
    """Return list of {'family':..., 'given':[...]} from FHIR HumanName or dict."""
    out = []
    items = getattr(patient, "name", None)
    if not items:
        return out
    for it in items:
        if isinstance(it, dict):
            fam = it.get("family")
            given = it.get("given")
        else:
            fam = getattr(it, "family", None)
            given = getattr(it, "given", None)
        out.append({"family": fam, "given": list(given) if given else None})
    return out


def _birth_as_str(patient):
    val = getattr(patient, "birthDate", None)
    if val is None:
        return None
    try:
        return val.isoformat()
    except Exception:
        return str(val)


# ------------------------------------------------------------------------------
# Small helpers tests
# ------------------------------------------------------------------------------


def test_safe_str_paths():
    assert _safe_str(_WithToEr7("X")) == "X"

    class S:
        def __str__(self):
            return "Y"

    assert _safe_str(S()) == "Y"

    class Bad:
        def __str__(self):
            raise RuntimeError("fail")

    assert _safe_str(Bad()) == ""


def test_get_trigger_paths():
    assert _get_trigger(None) is None
    assert _get_trigger("ADT^A01") == "ADT^A01"
    assert _get_trigger(_WithToEr7("ADT^A01")) == "ADT^A01"
    assert _get_trigger(_BoomToEr7()) is None


def test_seq_len_safe_simple():
    assert _seq_len_safe([1, 2, 3]) == 3


# ------------------------------------------------------------------------------
# PID helpers
# ------------------------------------------------------------------------------


def test_pid_identifier_ok_and_fallbacks():
    pid1 = _PID(pid_3=[_IdComp(_WithToEr7("123"))])
    assert _pid_identifier(pid1) == "123"
    pid2 = _PID(pid_3=[_IdComp(None)])
    assert _pid_identifier(pid2) is None

    class BadSeq:
        def __len__(self):
            raise RuntimeError("len boom")

    pid3 = _PID(pid_3=BadSeq())
    assert _pid_identifier(pid3) is None


def test_pid_name_variants_and_exceptions():
    pid = _PID(pid_5=[_NameComp(_WithToEr7("Doe"), _WithToEr7("John"))])
    fam1, giv1 = _pid_name(pid)
    assert fam1 == "Doe" and giv1 == ["John"]
    pid_fam = _PID(pid_5=[_NameComp(_WithToEr7("Solo"), None)])
    fam_only, giv_only = _pid_name(pid_fam)
    assert fam_only == "Solo" and giv_only == []
    pid_giv = _PID(pid_5=[_NameComp(None, _WithToEr7("Alone"))])
    fam3, giv3 = _pid_name(pid_giv)
    assert fam3 is None and giv3 == ["Alone"]

    # pid_5 empty list -> short-circuit branch
    pid_empty = _PID(pid_5=[])
    fam4, giv4 = _pid_name(pid_empty)
    assert fam4 is None and giv4 == []

    # exception branch inside try
    class BadPid:
        @property
        def pid_5(self):
            raise RuntimeError("boom")

    fam5, giv5 = _pid_name(BadPid())
    assert fam5 is None and giv5 == []


def test_pid_birthdate_formats_and_exceptions():
    assert _pid_birthdate(_PID(pid_7=_WithToEr7("19700102"))) == "1970-01-02"
    assert _pid_birthdate(_PID(pid_7=_WithToEr7("197001"))) == "1970-01"
    assert _pid_birthdate(_PID(pid_7=_WithToEr7("1970"))) == "1970"
    assert _pid_birthdate(_PID(pid_7=_WithToEr7("19700102T1200"))) is None

    # whitespace only
    assert _pid_birthdate(_PID(pid_7=_WithToEr7("   "))) is None

    # numeric but invalid length (5) -> fall-through None
    assert _pid_birthdate(_PID(pid_7=_WithToEr7("19700"))) is None

    # exception path
    class Bad:
        @property
        def pid_7(self):
            raise RuntimeError("boom")

    assert _pid_birthdate(Bad()) is None


def test_pid_gender_all_cases():
    assert _pid_gender(_PID(pid_8="M")) == "male"
    assert _pid_gender(_PID(pid_8="F")) == "female"
    assert _pid_gender(_PID(pid_8="O")) == "other"
    assert _pid_gender(_PID(pid_8="U")) == "unknown"
    assert _pid_gender(_PID(pid_8="")) is None
    assert _pid_gender(_PID(pid_8="Z")) == "unknown"

    class Bad:
        @property
        def pid_8(self):
            raise RuntimeError("boom")

    assert _pid_gender(Bad()) is None


# ------------------------------------------------------------------------------
# applies()
# ------------------------------------------------------------------------------


def test_applies_true_false_and_exception():
    t = ADTA01Transformer()
    msg1 = _Msg(MSH=_MSH(msh_9=_WithToEr7("ADT^A01")))
    assert t.applies(msg1)
    msg2 = _Msg(MSH=_MSH(msh_9=_WithToEr7("ORM^O01")))
    assert not t.applies(msg2)

    class BadMsg:
        @property
        def MSH(self):
            raise RuntimeError("boom")

    assert not t.applies(BadMsg())
    msg3 = _Msg(MSH=_MSH(msh_9="ADT^A01"))
    assert t.applies(msg3)


# ------------------------------------------------------------------------------
# transform()
# ------------------------------------------------------------------------------


def test_transform_always_returns_patient_and_encounter():
    t = ADTA01Transformer()
    pat, enc = t.transform(_Msg())

    # With real FHIR models, resource_type is present
    assert getattr(pat, "resource_type", "Patient") == "Patient"
    assert getattr(enc, "resource_type", "Encounter") == "Encounter"


def test_transform_with_pid_only_minimal_fields():
    t = ADTA01Transformer()
    pid = _PID(
        pid_3=[_IdComp(_WithToEr7("999"))],
        pid_5=[_NameComp(_WithToEr7("Doe"), _WithToEr7("Jane"))],
        pid_7=_WithToEr7("19800101"),
        pid_8="F",
    )
    patient, encounter = t.transform(_Msg(PID=pid))
    assert _ident_values(patient) == ["999"]
    names = _name_as_dicts(patient)
    assert names and names[0]["family"] == "Doe" and names[0]["given"] == ["Jane"]
    assert _birth_as_str(patient) == "1980-01-01"
    assert getattr(patient, "gender", None) == "female"
    assert getattr(encounter, "status", None) is None


def test_transform_with_pv1_sets_encounter_in_progress():
    # Lowercase fallback path: no uppercase PV1 on the message class
    class _MsgLower:
        def __init__(self, pid=None, pv1=None):
            self.pid = pid
            self.pv1 = pv1

    t = ADTA01Transformer()
    pid = _PID(pid_5=[_NameComp(_WithToEr7("Roe"), _WithToEr7("Janet"))])
    pv1 = _PV1(pv1_2=_WithToEr7("I"))
    _, enc = t.transform(_MsgLower(pid=pid, pv1=pv1))
    assert getattr(enc, "status", None) == "in-progress"


def test_transform_lowercase_pid_only():
    class _MsgLower:
        def __init__(self, pid=None):
            self.pid = pid

    t = ADTA01Transformer()
    pid = _PID(
        pid_3=[_IdComp(_WithToEr7("321"))],
        pid_5=[_NameComp(_WithToEr7("Smith"), _WithToEr7("Jo"))],
        pid_7=_WithToEr7("19990101"),
        pid_8="M",
    )
    patient, encounter = t.transform(_MsgLower(pid=pid))
    assert _ident_values(patient) == ["321"]
    names = _name_as_dicts(patient)
    assert names and names[0]["family"] == "Smith" and names[0]["given"] == ["Jo"]
    assert _birth_as_str(patient) == "1999-01-01"
    assert getattr(patient, "gender", None) == "male"
    assert getattr(encounter, "status", None) is None


def test_transform_encounter_status_setter_raises(monkeypatch):
    # Encounter stub whose status setter raises, so the except path is covered
    class _StatusSetterRaises:
        def __setattr__(self, k, v):
            if k == "status":
                raise RuntimeError("boom")
            object.__setattr__(self, k, v)

        @classmethod
        def model_construct(cls):
            return cls()

        @classmethod
        def construct(cls):
            return cls()

    monkeypatch.setattr(mod, "Encounter", _StatusSetterRaises, raising=True)
    t = ADTA01Transformer()
    _, enc = t.transform(_Msg(PV1=_PV1(pv1_2=_WithToEr7("O"))))
    assert isinstance(enc, _StatusSetterRaises)


# ------------------------------------------------------------------------------
# Import-time branch coverage
# ------------------------------------------------------------------------------


def test_import_branch_sets_resource_type_ok():
    fresh = _reimport_adt_a01_for_import_branch(assign_raises=False)
    assert hasattr(fresh, "ADTA01Transformer")


def test_import_branch_sets_resource_type_raises():
    fresh = _reimport_adt_a01_for_import_branch(assign_raises=True)
    assert hasattr(fresh, "ADTA01Transformer")


# ------------------------------------------------------------------------------
# Construct fallbacks
# ------------------------------------------------------------------------------


def test_build_patient_construct_fallback(monkeypatch):
    class OnlyConstruct:
        @classmethod
        def construct(cls):
            # Return a real Patient-like object with expected attrs
            return type(
                "P",
                (),
                {"identifier": None, "name": None, "birthDate": None, "gender": None},
            )()

    monkeypatch.setattr(mod, "Patient", OnlyConstruct, raising=True)
    out = ADTA01Transformer._build_patient(None)
    # Just validate we got *something* shaped like a patient.
    assert hasattr(out, "identifier") and hasattr(out, "name")


def test_build_patient_name_family_only_and_gender_absent():
    # family present, given absent, gender absent
    pid = _PID(pid_5=[_NameComp(_WithToEr7("Solo"), None)], pid_8="")
    p = ADTA01Transformer._build_patient(pid)
    names = _name_as_dicts(p)
    assert names == [{"family": "Solo", "given": None}]
    assert getattr(p, "gender", None) is None


def test_build_patient_name_given_only_and_gender_absent():
    # family absent, given present, gender absent
    pid = _PID(pid_5=[_NameComp(None, _WithToEr7("Only"))], pid_8="")
    p = ADTA01Transformer._build_patient(pid)
    names = _name_as_dicts(p)
    assert names == [{"family": None, "given": ["Only"]}]
    assert getattr(p, "gender", None) is None


def test_build_patient_name_absent_entirely_and_gender_absent():
    pid = _PID(pid_5=[], pid_8="")
    p = ADTA01Transformer._build_patient(pid)
    # No name set at all
    assert getattr(p, "name", None) in (None, [])
    # No gender set
    assert getattr(p, "gender", None) is None


def test_build_encounter_construct_fallback(monkeypatch):
    class OnlyConstruct:
        @classmethod
        def construct(cls):
            return type("E", (), {"status": None})()

    monkeypatch.setattr(mod, "Encounter", OnlyConstruct, raising=True)
    out = ADTA01Transformer._build_encounter(None)
    assert hasattr(out, "status")
