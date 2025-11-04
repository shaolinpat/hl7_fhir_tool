# tests/test_shacl_validation.py

"""
SHACL tests for modular shapes with closed shapes, value sets, and a lab profile
for glucose observations.
"""
import os
import pytest
from rdflib import Graph
from pyshacl import validate

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, ".."))

SHAPES = [
    os.path.join(ROOT, "src/hl7_fhir_tool/shacl/modules/00_namespaces.ttl"),
    os.path.join(ROOT, "src/hl7_fhir_tool/shacl/modules/10_valuesets.ttl"),
    os.path.join(ROOT, "src/hl7_fhir_tool/shacl/modules/20_core_shapes.ttl"),
    os.path.join(ROOT, "src/hl7_fhir_tool/shacl/modules/30_profile_lab.ttl"),
]


def _validate(data_rel, shapes=SHAPES):
    data = os.path.join(BASE, "data", data_rel)
    dg = Graph().parse(data, format="turtle")
    sg = Graph()
    for s in shapes:
        sg += Graph().parse(s, format="turtle")
    conforms, r_graph, r_text = validate(
        data_graph=dg,
        shacl_graph=sg,
        inference="rdfs",
        abort_on_error=False,
        allow_infos=True,
        allow_warnings=True,
        advanced=True,
        js=False,
        inplace=False,
        debug=False,
    )
    return conforms, r_text


@pytest.mark.parametrize("fname", ["fhir_valid.ttl"])
def test_valid_conforms(fname):
    ok, report = _validate(fname)
    assert ok, "Expected valid graph to conform, got:\n%s" % report


@pytest.mark.parametrize(
    "fname,needle",
    [
        ("fhir_bad_closed.ttl", "sh:closed"),  # closed shape extra property
        ("fhir_bad_values.ttl", "must be a permitted"),  # enum failures, etc.
    ],
)
def test_invalid_violates(fname, needle):
    ok, report = _validate(fname)
    assert not ok, "Expected invalid graph to violate shapes."
    assert needle in report or "Violation" in report
