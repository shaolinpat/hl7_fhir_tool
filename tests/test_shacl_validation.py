# tests/test_shacl_validation.py

"""
SHACL tests for modular shapes with closed shapes, value sets, and a lab profile
for glucose observations.
"""
import os
import pytest
import subprocess
import sys

from pyshacl import validate

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

# ------------------------------------------------------------------------------
# globals
# ------------------------------------------------------------------------------

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, ".."))
VALID = os.path.join(ROOT, "tests", "data", "fhir_valid.ttl")
INVALID = os.path.join(ROOT, "tests", "data", "fhir_bad_values.ttl")
DATA = os.path.join(ROOT, "tests/data/fhir_valid.ttl")

SHAPES = [
    os.path.join(ROOT, "rdf/ontology/hl7_fhir_tool_schema.ttl"),
    os.path.join(ROOT, "src/hl7_fhir_tool/shacl/modules/00_namespaces.ttl"),
    os.path.join(ROOT, "src/hl7_fhir_tool/shacl/modules/20_core_shapes.ttl"),
    os.path.join(ROOT, "src/hl7_fhir_tool/shacl/modules/30_profile_lab.ttl"),
]

PY = sys.executable


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _validate(data_rel, shapes=SHAPES):
    data = os.path.join(ROOT, "tests", "data", data_rel)
    dg = Graph().parse(data, format="turtle")

    # --------------------------------------------------------------------------
    # Include enumerations (hft:male, hft:female, etc.) as data facts
    # so that sh:class hft:AdminstrativeGenderCode succeeds.
    # --------------------------------------------------------------------------
    ontology_path = os.path.join(ROOT, "rdf/ontology/hl7_fhir_tool_schema.ttl")
    if os.path.exists(ontology_path):
        dg += Graph().parse(ontology_path, format="turtle")

    sg = Graph()
    for s in shapes:
        sg += Graph().parse(s, format="turtle")

    print("---- DEBUG: triples containing AdministrativeGenderCode ----")
    for s, p, o in dg.triples(
        (
            None,
            RDF.type,
            URIRef("http://example.org/hl7-fhir-tool#AdministrativeGenderCode"),
        )
    ):
        print(s, "is a AdministrativeGenderCode")
    print("---- DEBUG: total triples in data graph:", len(dg))

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


def _find_runner():
    candidates = [
        os.path.join(ROOT, "tools", "run_shacl.py"),
        os.path.abspath(os.path.join(ROOT, "..", "tools", "run_shacl.py")),
        os.path.abspath(os.path.join(BASE, "..", "..", "tools", "run_shacl.py")),
    ]

    for p in candidates:
        if os.path.exists(p):
            return p
    return ""


# ------------------------------------------------------------------------------
# tests
# ------------------------------------------------------------------------------


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


def test_cli_valid_exits_zero(tmp_path):
    out = tmp_path / "report_valid.ttl"
    cmd = [
        PY,
        _find_runner(),
        "--data",
        VALID,
        "--shapes",
        *SHAPES,
        "--report-out",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + "\n" + res.stderr


def test_cli_invalid_exits_nonzero(tmp_path):
    out = tmp_path / "report_invalid.ttl"
    cmd = [
        PY,
        _find_runner(),
        "--data",
        INVALID,
        "--shapes",
        *SHAPES,
        "--report-out",
        str(out),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode != 0, res.stdout + "\n" + res.stderr
