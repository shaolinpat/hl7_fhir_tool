# tests/test_fhir_parser.py
"""
Tests for hl7_fhir_tool/fhir_parser.
"""

import json
import pytest

from fhir.resources.patient import Patient
from fhir.resources.resource import Resource
from lxml import etree
from pathlib import Path
from pydantic import BaseModel

from hl7_fhir_tool.fhir_parser import (
    KNOWN_TYPES,
    _ensure_resource_type_attr,
    _xml_to_obj,
    load_fhir_json,
    load_fhir_xml,
    _inject_extras,
)
from hl7_fhir_tool.exceptions import ParseError

# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _to_doc(res):
    return (
        res.model_dump(by_alias=True)
        if hasattr(res, "model_dump")
        else res.dict(by_alias=True)
    )


# ------------------------------------------------------------------------------
# _ensure_resource_type_attr
# ------------------------------------------------------------------------------


def test_ensure_resource_type_attr_noop_on_existing():
    """
    Give the instance its own resource_type so helper returns immediately.
    """
    if hasattr(Resource, "model_construct"):
        inst = Resource.model_construct()  # pydantic v2
    else:
        inst = Resource.construct()  # pydantic v1

    # instance-level attr (not just class) so getattr(inst, ...) returns a truth value
    object.__setattr__(inst, "resource_type", "Already")
    _ensure_resource_type_attr(inst, "Other")
    assert getattr(inst, "resource_type") == "Already"


def test_ensure_resource_type_attr_sets_on_instance_when_missing():
    """
    Exercise the set-on-instance path when resource_type is false.
    """
    if hasattr(Resource, "model_construct"):
        inst = Resource.model_construct()  # pydantic v2
    else:
        inst = Resource.construct()  # pydandic v1

    object.__setattr__(inst, "resource_type", "")  # false at instance level
    _ensure_resource_type_attr(inst, "SetNow")
    assert getattr(inst, "resource_type") == "SetNow"


def test_ensure_resource_type_attr_sets_on_class_when_instance_set_fails():
    """
    Force instance-level setattr to fail (no __dict___), so helper sets class attr.
    """

    class FrozenNoDict:
        __slots__ = ()
        resource_type = ""

    inst = FrozenNoDict()
    _ensure_resource_type_attr(inst, "ClassLevelSet")

    # Instance lookup resolves to update class attribute
    assert type(inst).resource_type == "ClassLevelSet"
    assert not hasattr(inst, "__dict__")


def test_ensure_resource_type_attr_class_already_skips_setattr():
    # Instance setattr must fail -> we reach the class-level branch
    class FroxenAlready:
        __slots__ = ()
        resource_type = "Existing"

        def __getattribute__(self, name):
            # Hide instance-level lookup so getattr(inst, "resource_type", None) -> None
            if name == "resource_type":
                raise AttributeError
            return object.__getattribute__(self, name)

    inst = FroxenAlready()
    _ensure_resource_type_attr(inst, "NewValue")

    # Because class already had a non-empty value, helper should not overwrite it
    assert type(inst).resource_type == "Existing"


def test_ensure_resource_type_attr_class_setattr_failure_ignored():
    # Instance settattr failse (immutable), class settattr also fails (built-in type)
    _ensure_resource_type_attr(1, "Nope")
    assert not hasattr(int, "resource_type")


def test_ensure_resource_type_attr_sets_class_when_instance_set_fails():
    class NoDict:
        __slots__ = ()
        resource_type = ""

    inst = NoDict()
    _ensure_resource_type_attr(inst, "ClassLevel")
    assert type(inst).resource_type == "ClassLevel"
    assert not hasattr(inst, "__dict__")


def test_ensure_resource_type_attr_noop_instance_present():
    inst = (
        Resource.model_construct()
        if hasattr(Resource, "model_construct")
        else Resource.construct()
    )
    object.__setattr__(inst, "resource_type", "Already")
    _ensure_resource_type_attr(inst, "Ignored")
    assert getattr(inst, "resource_type") == "Already"


def test_ensure_resource_type_attr_early_return_when_present():
    class HasRT:
        pass

    inst = HasRT()
    object.__setattr__(inst, "resource_type", "Already")

    _ensure_resource_type_attr(inst, "Ignored")

    assert getattr(inst, "resource_type") == "Already"


def test_ensure_resource_type_attr_no_expected_does_nothing():
    # current is falsy("") and expected is None -> helper should no-op and return
    inst = (
        Resource.model_construct()
        if hasattr(Resource, "model_construct")
        else Resource.construct()
    )
    object.__setattr__(inst, "resource_type", "")
    _ensure_resource_type_attr(inst, None)
    assert getattr(inst, "resource_type") == ""


# -----------------------------------------------------------------------------
# _xml_to_obj_promotes_to_list()
# -----------------------------------------------------------------------------


def test_xml_to_obj_promotes_to_list():
    xml = "<root><child value='a'/><child value='b'/><child value='c'/></root>"
    root = etree.fromstring(xml)
    out = _xml_to_obj(root)
    assert isinstance(out["child"], list)
    assert out["child"] == ["a", "b", "c"]


def test_xml_to_obj_first_repeat_promotes_scalar_to_list():
    xml = "<root><child><grand value='x'/></child><child value='y'/></root>"
    root = etree.fromstring(xml)
    out = _xml_to_obj(root)
    # First child is a dict (scalar promotion), second makes it a list
    assert isinstance(out["child"], list)
    assert out["child"][0] == {"grand": "x"}
    assert out["child"][1] == "y"


# ------------------------------------------------------------------------------
# _construct_base
# ------------------------------------------------------------------------------


def test_construct_base_v2_path_json(tmp_path, monkeypatch):
    """
    Cover the v2 path in _construct_base: Resource.model_construct(**data).
    We re-enable it and make it delegate to a real BaseModel construct to produce a Resource.
    """
    # Ensure v1 path is not taken
    monkeypatch.setattr(Resource, "construct", None, raising=False)

    # Provide a v2-like model_construct that binds via BaseModel and returns a Resource
    def _mc(**data):
        bound = BaseModel.model_construct.__get__(Resource, type(Resource))
        return bound(**data)

    monkeypatch.setattr(Resource, "model_construct", _mc, raising=False)

    obj = {"resourceType": "CustomThing", "id": "x1"}
    p = tmp_path / "custom_v2.json"
    p.write_text(json.dumps(obj), encoding="utf-8")

    res = load_fhir_json(p)
    assert getattr(res, "resource_type", None) == "CustomThing"
    # sanity: field carried through
    assert getattr(res, "id", None) == "x1"


def test_construct_base_v1_path_json(tmp_path, monkeypatch):
    """
    Cover the v1 path in _construct_base: Resource.construct(**data).
    """
    # Disable v2; enable v1
    monkeypatch.setattr(Resource, "model_construct", None, raising=False)

    def _construct(**data):
        bound = BaseModel.model_construct.__get__(Resource, type(Resource))
        return bound(**data)

    monkeypatch.setattr(Resource, "construct", _construct, raising=False)

    obj = {"resourceType": "LegacyThing", "id": "y1"}
    p = tmp_path / "legacy_v1.json"
    p.write_text(json.dumps(obj), encoding="utf-8")

    res = load_fhir_json(p)
    assert getattr(res, "resource_type", None) == "LegacyThing"
    assert getattr(res, "id", None) == "y1"


def test_construct_base_no_apis_error_xml(tmp_path, monkeypatch):
    """
    Cover the final error branch: no model_construct/construct anywhere.
    """
    monkeypatch.setattr(Resource, "model_construct", None, raising=False)
    monkeypatch.setattr(Resource, "construct", None, raising=False)
    monkeypatch.setattr(BaseModel, "model_construct", None, raising=False)

    xml = '<Unknown xmlns="http://hl7.org/fhir"><id value="z"/></Unknown>'
    p = tmp_path / "none_left.xml"
    p.write_text(xml, encoding="utf-8")

    with pytest.raises(
        ParseError,
        match=r"^failed to construct base Resource from XML: Resource does not "
        "expose model_construct or construct",
    ):
        load_fhir_xml(p)


# def test_construct_base_descriptor_success_xml(tmp_path, monkeypatch):
#     """Cover the descriptor-binding path."""
#     # Force _construct_base to skip v2/v1 on Resource
#     monkeypatch.setattr(Resource, "model_construct", None, raising=False)
#     monkeypatch.setattr(Resource, "construct", None, raising=False)

#     # Provide a BaseModel.model_construct that *does* have __get__ and works
#     orig_bm_mc = BaseModel.model_construct

#     class HasGet:
#         def __get__(self, _owner, _type):
#             return orig_bm_mc  # return the original (bound) callable

#     monkeypatch.setattr(BaseModel, "model_construct", HasGet(), raising=False)

#     xml = (
#         '<CustomResource xmlns="http://hl7.org/fhir">'
#         '<id value="z"/><identifier value="a"/><identifier value="b"/></CustomResource>'
#     )
#     p = tmp_path / "custom_desc.xml"
#     p.write_text(xml, encoding="utf-8")

#     res = load_fhir_xml(p)
#     # resource_type assigned + list promotion (hits list-aggregation branch)
#     assert getattr(res, "resource_type", None) == "CustomResource"
#     # Ensure identifiers were aggregated into a list via _xml_to_obj branch
#     ids = getattr(res, "identifier", None)
#     assert isinstance(ids, list) and ids == ["a", "b"]


# def test_construct_base_unbound_func_raises_xml(tmp_path, monkeypatch):
#     """
#     Cover the __func__ path and ensure the inner exception bubbles as 'explode',
#     matching the test that expects that exact message.
#     """
#     # Disable Resource v2/v1 APIs
#     monkeypatch.setattr(Resource, "model_construct", None, raising=False)
#     monkeypatch.setattr(Resource, "construct", None, raising=False)

#     class Boom:
#         def __call__(self, *a, **k):
#             raise RuntimeError("explode")

#     # Provide an object with __func__ that raises
#     monkeypatch.setattr(
#         BaseModel,
#         "model_construct",
#         type("X", (), {"__func__": Boom()})(),
#         raising=False,
#     )

#     xml = '<CustomResource xmlns="http://hl7.org/fhir"><id value="z"/></CustomResource>'
#     p = tmp_path / "custom_basefail.xml"
#     p.write_text(xml, encoding="utf-8")

#     with pytest.raises(
#         ParseError, match=r"^failed to construct base Resource from XML: explode$"
#     ):
#         load_fhir_xml(p)


# ------------------------------------------------------------------------------
# _inject_extras
# ------------------------------------------------------------------------------


def test_inject_extras_v2_store_updates_and_attr_set():
    """
    Cover v2 style path in _inject_extras:
        - field names come from class model_fields
        - extras go into __pydantic_extra__
        - attributes are also set on the instance
    """

    class V2LikeResource:
        # emulate pydantic v2 class metadata
        model_fields = {"id": object, "resourceType": object}

        def __init__(self):
            # emulate pydantic v2 extra store
            self.__pydantic_extra__ = {}

    inst = V2LikeResource()
    data = {"resourceType": "X", "id": "x1", "identifier": ["A", "B"], "foo": 7}

    _inject_extras(inst, data)

    # extras were stored
    assert inst.__pydantic_extra__.get("identifier") == ["A", "B"]
    assert inst.__pydantic_extra__.get("foo") == 7
    # attributes set for convenience
    assert getattr(inst, "identifier") == ["A", "B"]
    assert getattr(inst, "foo") == 7


def test_inject_extras_v1_fallback_dict_update_and_attr_set():
    """
    Cover v1 style path in _inject_extras:
        - field names come from class __fields__
        - no __pydantic_extra__ so fall back to __dict__ update
        - attributes are also set on the instance
    """

    class V1LikeResource:
        __fields__ = {"id": object, "resourceType": object}

        def __init__(self):
            self.id = "y1"  # ensure __dict__ exists

    inst = V1LikeResource()
    data = {"resourceType": "Y", "id": "y1", "bar": "baz"}

    _inject_extras(inst, data)

    # dict updated with extra
    assert getattr(inst, "__dict__", {}).get("bar") == "baz"
    # attribute also set
    assert getattr(inst, "bar") == "baz"


def test_inject_extras_early_return_when_no_extras():
    """
    Cover early return when extras is empty.
    """

    class OnlyModelFields:
        model_fields = {"resourceType": object, "id": object}

    inst = OnlyModelFields()
    data = {"resourceType": "Z", "id": "z1"}  # no extras

    _inject_extras(inst, data)
    # nothing added
    assert not hasattr(inst, "anything_else")


def test_inject_extras_attr_set_failure_is_ignored():
    """
    Cover attribute setting failure path in _inject_extras.
    object.__setattr__ should fail when class forbids new attributes.
    """

    class SlottedNoNew:
        __slots__ = ()  # no new attributes allowed
        __fields__ = {}  # make field set empty so everything is extra

    inst = SlottedNoNew()
    data = {"resourceType": "W", "id": "w1", "extra_field": 123}

    _inject_extras(inst, data)
    # still no attribute created, but no exception
    assert not hasattr(inst, "extra_field")


# ------------------------------------------------------------------------------
# load_fhir_json
# ------------------------------------------------------------------------------


def test_load_fhir_json_raises_on_missing_file(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(ParseError, match=r"^file does not exist"):
        load_fhir_json(missing)


def test_load_fhir_json_raises_on_directory(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises(ParseError, match=r"^not a file"):
        load_fhir_json(d)


def test_load_fhir_json_raises_on_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not-valid-json")
    with pytest.raises(ParseError, match=r"^invalid JSON"):
        load_fhir_json(p)


def test_load_fhir_json_raises_on_non_object_top_level(tmp_path):
    p = tmp_path / "list.json"
    p.write_text(json.dumps([{"resourceType": "Patient"}]))
    with pytest.raises(
        ParseError, match=r"^FHIR JSON must be an object at the top level"
    ):
        load_fhir_json(p)


def test_load_fhir_json_patient_returns_patient(tmp_path):
    p = tmp_path / "patient.json"
    p.write_text(json.dumps({"resourceType": "Patient", "id": "p1"}))
    f = load_fhir_json(p)
    assert isinstance(f, Patient)
    assert f.id == "p1"


def test_load_fhir_json_unknown_type_returns_base_resource(tmp_path):
    p = tmp_path / "custom.json"
    p.write_text(json.dumps({"resourceType": "CustomResource", "id": "x"}))
    r = load_fhir_json(p)

    # Should fall back to generic Resource
    assert isinstance(r, Resource)
    assert type(r) is Resource

    if hasattr(r, "model_dump"):  # pydantic v2
        data = r.model_dump(by_alias=True)
    else:  # pydantic v1
        data = r.dict(by_alias=True)

    # resourceType may normalize to "Resource" on the base model
    assert data["resourceType"] in ("CustomResource", "Resource")
    assert data["id"] == "x"


def test_load_fhir_json_validation_error(tmp_path):
    # Intentionally wrong type for a known field to provoke validation error.
    # 'active' should be a boolean if present; set it to a dict.
    p = tmp_path / "bad_patient.json"
    p.write_text(json.dumps({"resourceType": "Patient", "active": {"nope": True}}))
    with pytest.raises(ParseError, match=r"^FHIR JSON validation error"):
        load_fhir_json(p)


def test_load_fhir_json_type_check_and_oserror(tmp_path, monkeypatch):
    # Type check: not a Path -> ParseError from _ensure_file()
    with pytest.raises(ParseError, match=r"^path must be pathlib\.Path"):
        load_fhir_json("not-a-path")

    # OSError on read: exercise the except OSError path in load_fhir_json
    p = tmp_path / "will_boom.json"
    p.write_text("{}", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(ParseError, match=r"^failed to read JSON"):
        load_fhir_json(p)


def test_load_fhir_json_known_type_build_error(tmp_path, monkeypatch):
    class RaisingPatient:
        def __init__(self, a, **k):
            raise RuntimeError("explode")

    monkeypatch.setitem(KNOWN_TYPES, "Patient", RaisingPatient)

    p = tmp_path / "patient.json"
    p.write_text('{"resourceType": "Patient"}', encoding="utf-8")

    with pytest.raises(ParseError, match=r"^failed to build FHIR model"):
        load_fhir_json(p)


def test_load_fhir_json_unknown_type_construct_faulure(tmp_path, monkeypatch):
    # Force the unknown-type path and make Resource.model_construct raise.
    def mc_raise(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(Resource, "model_construct", staticmethod(mc_raise))

    p = tmp_path / "strange.json"
    p.write_text('{"resourceType":"StrangeThing", "id":"x"}', encoding="utf-8")

    with pytest.raises(
        ParseError, match=r"^failed to construct base Resource for unknown"
    ):
        load_fhir_json(p)


def test_load_fhir_json_unknown_type_construct_success(tmp_path, monkeypatch):
    # Keep a handle to the original v2 constructor
    orig_mc = getattr(Resource, "model_construct")

    # Force the code to choose the construct() branch
    monkeypatch.setattr(Resource, "model_construct", None, raising=False)

    # Stub construct() to build via the original model_construct(), avoiding v2 deprecation
    def fake_construct(**kwargs):
        return orig_mc(**kwargs)

    monkeypatch.setattr(
        Resource, "construct", staticmethod(fake_construct), raising=False
    )

    p = tmp_path / "weird.json"
    p.write_text('{"resourceType":"WeirdThing", "id":"w"}', encoding="utf-8")

    r = load_fhir_json(p)
    assert isinstance(r, Resource)
    doc = (
        r.model_dump(by_alias=True)
        if hasattr(r, "model_dump")
        else r.dict(by_alias=True)
    )
    assert doc.get("id") == "w"


# ------------------------------------------------------------------------------
# load_fhir_xml
# ------------------------------------------------------------------------------


def test_load_fhir_xml_raises_on_missing_file(tmp_path):
    missing = tmp_path / "missing.xml"
    with pytest.raises(ParseError, match=r"^file does not exist"):
        load_fhir_xml(missing)


def test_load_fhir_xml_raises_on_invalid_xml(tmp_path):
    p = tmp_path / "bad.xml"
    p.write_text("<Patient")
    with pytest.raises(ParseError, match=r"^invalid XML"):
        load_fhir_xml(p)


def test_load_fhir_xml_raises_on_directory_and_type_check(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises(ParseError, match=r"^not a file"):
        load_fhir_xml(d)
    with pytest.raises(ParseError, match=r"^path must be pathlib\.Path"):
        load_fhir_xml("not-a-path")


def test_load_fhir_xml_patient_parses(tmp_path):
    # Minimal FHIR Patient XML with namespace
    xml = '<Patient xmlns="http://hl7.org/fhir"><id value="p1"/></Patient>'

    p = tmp_path / "patient.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)

    # The helper returns a Resource (could be a subclass), but it should reflect
    # the type.
    assert isinstance(r, Resource)
    assert getattr(r, "resource_type", None) in ("Patient", "Resource")

    if hasattr(r, "model_dump_json"):  # pydantic v2
        js = r.model_dump(by_alias=True)
    else:
        js = r.dict(by_alias=True)
    assert js["id"] == "p1"
    assert js["resourceType"] in ("Patient", "Resource")


def test_load_fhir_xml_repaated_children_promotes_to_list(tmp_path):
    # Covers _xml_to_obj recursion and the "promot to list" branch.
    xml = """
    <Patient xmlns="http://hl7.org/fhir">
      <identifier>
        <value value="A"/>
      </identifier>
      <identifier>
        <value value="B"/>
      </identifier>
    </Patient>
    """.strip()

    p = tmp_path / "patient_ids.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)

    if hasattr(r, "model_dump_json"):
        js = r.model_dump(by_alias=True)
    else:
        js = r.dict(by_alias=True)

    ids = js.get("identifier")
    assert isinstance(ids, list)
    assert any("A" in str(item) for item in ids)
    assert any("B" in str(item) for item in ids)


def test_load_fhir_xml_known_type_validation_error(tmp_path):
    # 'active' must be boolean; string triggers ValidationError branch.
    xml = '<Patient xmlns="http://hl7.org/fhir"><active value="nope"/></Patient>'

    p = tmp_path / "bad_active.xml"
    p.write_text(xml, encoding="utf-8")

    with pytest.raises(ParseError, match=r"^FHIR XML validation error"):
        load_fhir_xml(p)


def test_load_fhir_xml_repeated_children_promote_to_list(tmp_path):
    """
    When a known resource type has repeated children, the loader should
    promote the field into a list rather than overwriting the earlier value.
    """

    xml = """
    <Patient xmlns="http://hl7.org/fhir">
      <identifier><value value="A"/></identifier>
      <identifier><value value="B"/></identifier>
    </Patient>
    """.strip()

    p = tmp_path / "patient_ids.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)
    doc = (
        r.model_dump(by_alias=True)
        if hasattr(r, "model_dump")
        else r.dict(by_alias=True)
    )

    ids = doc.get("identifier")
    assert isinstance(ids, list)
    assert any(isinstance(x, dict) and x.get("value") == "A" for x in ids)
    assert any(isinstance(x, dict) and x.get("value") == "B" for x in ids)


def test_load_fhir_xml_repeated_root_children_promote_and_append(tmp_path):
    # Unknown resource: no schema validation to interfere
    xml = "<X><y value='1'/><y value='2'/><y value='3'/></X>"

    p = tmp_path / "x.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)
    assert isinstance(r, Resource)


def test_load_fhir_xml_known_type_other_exception(tmp_path, monkeypatch):
    class RaisingPatient:
        def __init__(self, *a, **k):
            raise RuntimeError("boom")

    # Replace the constructor used by the loader
    monkeypatch.setitem(KNOWN_TYPES, "Patient", RaisingPatient)

    xml = '<Patient xmlns="http://hl7.org/fhir"><id value="p1"/></Patient>'
    p = tmp_path / "patient_boom.xml"
    p.write_text(xml, encoding="utf-8")

    with pytest.raises(ParseError, match=r"^failed to build FHIR model from XML"):
        load_fhir_xml(p)


def test_load_fhir_xml_unknown_type_uses_construct(tmp_path, monkeypatch):
    # Drive the unknown-type XML path through Resource.construct(...) (success).
    # Disable model_construct so the loader chooses the construct() branch.
    orig_mc = getattr(Resource, "model_construct")
    monkeypatch.setattr(Resource, "model_construct", None, raising=False)

    # Make construct() delegate to the original v2 model model_construct() to
    # avoid deprecation issues.
    def fake_construct(**kwargs):
        return orig_mc(**kwargs)

    monkeypatch.setattr(
        Resource, "construct", staticmethod(fake_construct), raising=False
    )

    xml = '<CustomResource xmlns="http://hl7.org/fhir"><id value="x"/></CustomResource>'
    p = tmp_path / "custom_construct.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)
    assert isinstance(r, Resource)
    doc = (
        r.model_dump(by_alias=True)
        if hasattr(r, "model_dump")
        else r.dict(by_alias=True)
    )
    assert doc.get("id") == "x"


def test_load_fhir_xml_patient_name_scalar_given_wrapped(tmp_path):
    """
    Single <name> block with scalar <given value="..."> becomes list[str],
    and overall Patient.name becomes a list[HumanName].
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Patient xmlns="http://hl7.org/fhir">
        <id value="pnorm1"/>
        <name>
            <family value="Doe"/>
            <given value="John"/>
        </name>
    </Patient>
    """
    p = tmp_path / "patient_scalar_given.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)
    doc = _to_doc(r)

    assert doc["resourceType"] in ("Patient", "Resource")
    assert isinstance(doc["name"], list)
    assert len(doc["name"]) == 1
    hn = doc["name"][0]
    assert hn["family"] == "Doe"
    assert isinstance(hn["given"], list)
    assert hn["given"] == ["John"]


def test_load_fhir_xml_patient_name_dict_wrapped_to_list(tmp_path):
    """
    If <name> appears once, dict->list coercion wraps it so Patient.name is a list.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Patient xmlns="http://hl7.org/fhir">
        <id value="pnorm2"/>
        <name>
            <family value="Solo"/>
        </name>
    </Patient>
    """
    p = tmp_path / "patient_single_name.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)
    doc = _to_doc(r)

    assert doc["resourceType"] in ("Patient", "Resource")
    assert isinstance(doc["name"], list)
    assert doc["name"] == [{"family": "Solo"}]


def test_load_fhir_xml_patient_multi_given_preserved_as_list(tmp_path):
    """
    Multiple <given> elements become a list of values in order.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Patient xmlns="http://hl7.org/fhir">
        <id value="pnorm3"/>
        <name>
            <family value="Doe"/>
            <given value="John"/>
            <given value="Quincy"/>
        </name>
    </Patient>
    """
    p = tmp_path / "patient_multi_given.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)
    doc = _to_doc(r)

    assert doc["resourceType"] in ("Patient", "Resource")
    assert isinstance(doc["name"], list)
    hn = doc["name"][0]
    assert hn["family"] == "Doe"
    assert hn["given"] == ["John", "Quincy"]


def test_load_fhir_xml_patient_name_missing_given_preserved(tmp_path):
    """
    A HumanName without <given> is preserved; no crash or unwanted keys.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Patient xmlns="http://hl7.org/fhir">
        <id value="pnorm4"/>
        <name>
            <family value="Roe"/>
        </name>
    </Patient>
    """
    p = tmp_path / "patient_no_given.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)
    doc = _to_doc(r)

    assert doc["resourceType"] in ("Patient", "Resource")
    assert isinstance(doc["name"], list)
    assert doc["name"] == [{"family": "Roe"}]


def test_load_fhir_xml_non_patient_root_no_name_normalization(tmp_path):
    """
    Root is not Patient -> normalization block is skipped.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Foo xmlns="http://hl7.org/fhir">
        <name>
            <family value="Doe"/>
            <given value="John"/>
        </name>
    </Foo>
    """
    p = tmp_path / "foo_name.xml"
    p.write_text(xml, encoding="utf-8")

    r = load_fhir_xml(p)
    doc = _to_doc(r)

    assert doc["resourceType"] in ("Foo", "Resource")
    assert "name" not in doc or isinstance(doc["name"], dict)


def test_load_fhir_xml_patient_name_block_nm_not_dict(tmp_path):
    """
    Covers the branch where nm is not a dict (list directly).
    """
    xml = """
    <Patient xmlns="http://hl7.org/fhir">
        <id value="pX1"/>
        <name>
            <family value="Doe"/>
            <given value="John"/>
        </name>
        <name>
            <family value="Smith"/>
            <given value="Jane"/>
        </name>
    </Patient>
    """
    p = tmp_path / "patient_list_name.xml"
    p.write_text(xml, encoding="utf-8")
    r = load_fhir_xml(p)
    assert isinstance(r, Resource)


def test_load_fhir_xml_patient_name_block_name_not_list(tmp_path):
    """
    Covers the branch where data["name"] is not a list (scalar),
    which triggers a validation error in the Patient model.
    """
    xml = """
    <Patient xmlns="http://hl7.org/fhir">
        <id value="pX2"/>
        <name value="JustAString"/>
    </Patient>
    """
    p = tmp_path / "patient_scalar_name.xml"
    p.write_text(xml, encoding="utf-8")
    with pytest.raises(ParseError, match=r"^FHIR XML validation error"):
        load_fhir_xml(p)
