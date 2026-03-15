# tests/test_rdf_serializer.py
"""
Tests for hl7_fhir_tool/rdf_serializer.
"""

import types

import pytest
from rdflib import Graph, Literal, Namespace, RDF, URIRef, XSD

from hl7_fhir_tool.rdf_serializer import (
    HFT,
    FHIR,
    _safe_get,
    _resource_uri,
    _ref_to_uri,
    _first_coding_uri,
    _add_identifiers,
    _add_patient,
    _add_encounter,
    _add_observation,
    _add_condition,
    _add_service_request,
    _add_diagnostic_report,
    serialize_resources,
)


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _graph() -> Graph:
    """Return a fresh empty Graph."""
    return Graph()


def _coding(code="GLU", system="http://loinc.org"):
    return types.SimpleNamespace(code=code, system=system)


def _codeable_concept(code="GLU", system="http://loinc.org"):
    return types.SimpleNamespace(coding=[_coding(code, system)])


def _identifier(value="ID001"):
    return types.SimpleNamespace(value=value)


def _quantity(value=110.0, unit="mg/dL"):
    return types.SimpleNamespace(value=value, unit=unit)


def _ref(reference="Patient/p1"):
    return types.SimpleNamespace(reference=reference)


# ------------------------------------------------------------------------------
# _safe_get
# ------------------------------------------------------------------------------


def test_safe_get_single_attr():
    obj = types.SimpleNamespace(x=42)
    assert _safe_get(obj, "x") == 42


def test_safe_get_chained_attrs():
    inner = types.SimpleNamespace(y=99)
    outer = types.SimpleNamespace(inner=inner)
    assert _safe_get(outer, "inner", "y") == 99


def test_safe_get_missing_attr_returns_none():
    obj = types.SimpleNamespace(x=1)
    assert _safe_get(obj, "z") is None


def test_safe_get_none_input_returns_none():
    assert _safe_get(None, "x") is None


def test_safe_get_none_in_chain_returns_none():
    obj = types.SimpleNamespace(x=None)
    assert _safe_get(obj, "x", "y") is None


def test_safe_get_no_attrs_returns_obj():
    obj = types.SimpleNamespace(x=1)
    assert _safe_get(obj) is obj


# ------------------------------------------------------------------------------
# _resource_uri
# ------------------------------------------------------------------------------


def test_resource_uri_form():
    uri = _resource_uri("Patient", "12345")
    assert uri == HFT["Patient_12345"]
    assert isinstance(uri, URIRef)


def test_resource_uri_different_types():
    assert _resource_uri("Encounter", "enc-1") == HFT["Encounter_enc-1"]
    assert _resource_uri("Observation", "obs-99") == HFT["Observation_obs-99"]


# ------------------------------------------------------------------------------
# _ref_to_uri
# ------------------------------------------------------------------------------


def test_ref_to_uri_valid():
    uri = _ref_to_uri("Patient/p1")
    assert uri == HFT["Patient_p1"]


def test_ref_to_uri_no_slash_returns_none():
    assert _ref_to_uri("Patient") is None


def test_ref_to_uri_empty_string_returns_none():
    assert _ref_to_uri("") is None


def test_ref_to_uri_none_returns_none():
    assert _ref_to_uri(None) is None


def test_ref_to_uri_multiple_slashes_splits_on_first():
    uri = _ref_to_uri("Patient/p1/extra")
    assert uri == HFT["Patient_p1/extra"]


# ------------------------------------------------------------------------------
# _first_coding_uri
# ------------------------------------------------------------------------------


def test_first_coding_uri_direct_coding():
    concept = _codeable_concept(code="4548-4", system="http://loinc.org")
    uri = _first_coding_uri(concept)
    assert uri == URIRef("http://loinc.org/4548-4")


def test_first_coding_uri_no_system_uses_default():
    concept = types.SimpleNamespace(
        coding=[types.SimpleNamespace(code="GLU", system=None)]
    )
    uri = _first_coding_uri(concept)
    assert uri == URIRef("http://example.org/code/GLU")


def test_first_coding_uri_r5_concept_nesting():
    inner = types.SimpleNamespace(coding=[_coding("HBA1C", "http://loinc.org")])
    concept = types.SimpleNamespace(concept=inner, coding=None)
    uri = _first_coding_uri(concept)
    assert uri == URIRef("http://loinc.org/HBA1C")


def test_first_coding_uri_empty_coding_list():
    concept = types.SimpleNamespace(coding=[])
    assert _first_coding_uri(concept) is None


def test_first_coding_uri_none_input():
    assert _first_coding_uri(None) is None


def test_first_coding_uri_coding_without_code():
    concept = types.SimpleNamespace(
        coding=[types.SimpleNamespace(code=None, system="http://loinc.org")]
    )
    assert _first_coding_uri(concept) is None


# ------------------------------------------------------------------------------
# _add_identifiers
# ------------------------------------------------------------------------------


def test_add_identifiers_single():
    g = _graph()
    subj = HFT["Patient_p1"]
    resource = types.SimpleNamespace(identifier=[_identifier("MRN-001")])
    _add_identifiers(g, subj, resource)
    assert (subj, HFT.identifier, Literal("MRN-001", datatype=XSD.string)) in g


def test_add_identifiers_multiple():
    g = _graph()
    subj = HFT["Patient_p1"]
    resource = types.SimpleNamespace(identifier=[_identifier("A"), _identifier("B")])
    _add_identifiers(g, subj, resource)
    vals = {str(o) for s, p, o in g if p == HFT.identifier}
    assert vals == {"A", "B"}


def test_add_identifiers_none():
    g = _graph()
    subj = HFT["Patient_p1"]
    resource = types.SimpleNamespace(identifier=None)
    _add_identifiers(g, subj, resource)
    assert len(g) == 0


def test_add_identifiers_empty_list():
    g = _graph()
    subj = HFT["Patient_p1"]
    resource = types.SimpleNamespace(identifier=[])
    _add_identifiers(g, subj, resource)
    assert len(g) == 0


def test_add_identifiers_value_none_skipped():
    g = _graph()
    subj = HFT["Patient_p1"]
    resource = types.SimpleNamespace(identifier=[types.SimpleNamespace(value=None)])
    _add_identifiers(g, subj, resource)
    assert len(g) == 0


# ------------------------------------------------------------------------------
# _add_patient
# ------------------------------------------------------------------------------


def test_add_patient_full():
    g = _graph()
    resource = types.SimpleNamespace(
        id="p1",
        identifier=[_identifier("MRN-1")],
        name=[types.SimpleNamespace(family="Doe", given=["John"])],
        birthDate="1970-01-01",
        gender="male",
    )
    subj = _add_patient(g, resource)
    assert (subj, RDF.type, HFT.Patient) in g
    assert (subj, HFT.family, Literal("Doe", datatype=XSD.string)) in g
    assert (subj, HFT.given, Literal("John", datatype=XSD.string)) in g
    assert (subj, HFT.birthDate, Literal("1970-01-01", datatype=XSD.date)) in g
    assert (subj, HFT.gender, HFT.male) in g


def test_add_patient_female_gender():
    g = _graph()
    resource = types.SimpleNamespace(
        id="p2", identifier=None, name=[], birthDate=None, gender="female"
    )
    subj = _add_patient(g, resource)
    assert (subj, HFT.gender, HFT.female) in g


def test_add_patient_unknown_gender_string_skipped():
    g = _graph()
    resource = types.SimpleNamespace(
        id="p3", identifier=None, name=[], birthDate=None, gender="nonbinary"
    )
    _add_patient(g, resource)
    gender_triples = [(s, p, o) for s, p, o in g if p == HFT.gender]
    assert len(gender_triples) == 0


def test_add_patient_no_birth_date():
    g = _graph()
    resource = types.SimpleNamespace(
        id="p4", identifier=None, name=[], birthDate=None, gender=None
    )
    _add_patient(g, resource)
    assert not any(p == HFT.birthDate for s, p, o in g)


def test_add_patient_multiple_given_names():
    g = _graph()
    resource = types.SimpleNamespace(
        id="p5",
        identifier=None,
        name=[types.SimpleNamespace(family="Smith", given=["Alice", "Marie"])],
        birthDate=None,
        gender=None,
    )
    subj = _add_patient(g, resource)
    given_vals = {str(o) for s, p, o in g if p == HFT.given}
    assert given_vals == {"Alice", "Marie"}


def test_add_patient_no_id_defaults_to_unknown():
    g = _graph()
    resource = types.SimpleNamespace(
        id=None, identifier=None, name=[], birthDate=None, gender=None
    )
    subj = _add_patient(g, resource)
    assert subj == HFT["Patient_unknown"]


def test_add_patient_name_without_family():
    g = _graph()
    resource = types.SimpleNamespace(
        id="p6",
        identifier=None,
        name=[types.SimpleNamespace(family=None, given=["John"])],
        birthDate=None,
        gender=None,
    )
    _add_patient(g, resource)
    assert not any(p == HFT.family for s, p, o in g)


# ------------------------------------------------------------------------------
# _add_encounter
# ------------------------------------------------------------------------------


def test_add_encounter_full():
    g = _graph()
    resource = types.SimpleNamespace(
        id="enc-1",
        identifier=[_identifier("ENC001")],
        status="in-progress",
        subject=_ref("Patient/p1"),
    )
    subj = _add_encounter(g, resource)
    assert (subj, RDF.type, HFT.Encounter) in g
    assert (subj, HFT.status, Literal("in-progress", datatype=XSD.string)) in g
    assert (subj, HFT.encounterSubject, HFT["Patient_p1"]) in g


def test_add_encounter_no_subject():
    g = _graph()
    resource = types.SimpleNamespace(
        id="enc-2", identifier=None, status="finished", subject=None
    )
    _add_encounter(g, resource)
    assert not any(p == HFT.encounterSubject for s, p, o in g)


def test_add_encounter_no_status():
    g = _graph()
    resource = types.SimpleNamespace(
        id="enc-3", identifier=None, status=None, subject=None
    )
    _add_encounter(g, resource)
    assert not any(p == HFT.status for s, p, o in g)


def test_add_encounter_subject_ref_no_slash():
    g = _graph()
    resource = types.SimpleNamespace(
        id="enc-4",
        identifier=None,
        status=None,
        subject=types.SimpleNamespace(reference="PatientNoSlash"),
    )
    _add_encounter(g, resource)
    assert not any(p == HFT.encounterSubject for s, p, o in g)


# ------------------------------------------------------------------------------
# _add_observation
# ------------------------------------------------------------------------------


def test_add_observation_numeric():
    g = _graph()
    resource = types.SimpleNamespace(
        id="obs-1",
        identifier=[_identifier("OBS001")],
        status="final",
        subject=_ref("Patient/p1"),
        code=_codeable_concept("GLU", "http://loinc.org"),
        valueQuantity=_quantity(110.0, "mg/dL"),
        valueString=None,
        effectiveDateTime=None,
    )
    subj = _add_observation(g, resource)
    assert (subj, RDF.type, HFT.NumericObservation) in g
    assert any(p == HFT.valueDecimal for s, p, o in g)
    assert (subj, HFT.hasUnit, Literal("mg/dL", datatype=XSD.string)) in g


def test_add_observation_non_numeric():
    g = _graph()
    resource = types.SimpleNamespace(
        id="obs-2",
        identifier=None,
        status="final",
        subject=None,
        code=None,
        valueQuantity=None,
        valueString="positive",
        effectiveDateTime=None,
    )
    subj = _add_observation(g, resource)
    assert (subj, RDF.type, HFT.Observation) in g
    assert (subj, HFT.valueString, Literal("positive", datatype=XSD.string)) in g


def test_add_observation_effective_datetime():
    g = _graph()
    resource = types.SimpleNamespace(
        id="obs-3",
        identifier=None,
        status=None,
        subject=None,
        code=None,
        valueQuantity=None,
        valueString=None,
        effectiveDateTime="2025-01-01T08:00:00",
    )
    subj = _add_observation(g, resource)
    assert (
        subj,
        HFT.effectiveDateTime,
        Literal("2025-01-01T08:00:00", datatype=XSD.dateTime),
    ) in g


def test_add_observation_invalid_decimal_skipped(monkeypatch):
    g = _graph()
    bad_qty = types.SimpleNamespace(value="not-a-number", unit=None)
    resource = types.SimpleNamespace(
        id="obs-4",
        identifier=None,
        status=None,
        subject=None,
        code=None,
        valueQuantity=bad_qty,
        valueString=None,
        effectiveDateTime=None,
    )
    # Should not raise; invalid decimal is caught and skipped
    _add_observation(g, resource)
    assert not any(p == HFT.valueDecimal for s, p, o in g)


def test_add_observation_subject_linked():
    g = _graph()
    resource = types.SimpleNamespace(
        id="obs-5",
        identifier=None,
        status=None,
        subject=_ref("Patient/p99"),
        code=None,
        valueQuantity=None,
        valueString=None,
        effectiveDateTime=None,
    )
    subj = _add_observation(g, resource)
    assert (subj, HFT.observationSubject, HFT["Patient_p99"]) in g


def test_add_observation_subject_ref_no_slash():
    g = _graph()
    resource = types.SimpleNamespace(
        id="obs-6",
        identifier=None,
        status=None,
        subject=types.SimpleNamespace(reference="PatientNoSlash"),
        code=None,
        valueQuantity=None,
        valueString=None,
        effectiveDateTime=None,
    )
    _add_observation(g, resource)
    assert not any(p == HFT.observationSubject for s, p, o in g)


# ------------------------------------------------------------------------------
# _add_condition
# ------------------------------------------------------------------------------


def test_add_condition_full():
    g = _graph()
    resource = types.SimpleNamespace(
        id="cond-1",
        identifier=[_identifier("C001")],
        subject=_ref("Patient/p1"),
        code=_codeable_concept("E11.9", "http://hl7.org/fhir/sid/icd-10"),
    )
    subj = _add_condition(g, resource)
    assert (subj, RDF.type, HFT.Condition) in g
    assert (subj, HFT.conditionSubject, HFT["Patient_p1"]) in g
    assert any(p == HFT.hasCode for s, p, o in g)


def test_add_condition_no_code():
    g = _graph()
    resource = types.SimpleNamespace(
        id="cond-2", identifier=None, subject=None, code=None
    )
    _add_condition(g, resource)
    assert not any(p == HFT.hasCode for s, p, o in g)


def test_add_condition_no_subject():
    g = _graph()
    resource = types.SimpleNamespace(
        id="cond-3", identifier=None, subject=None, code=None
    )
    _add_condition(g, resource)
    assert not any(p == HFT.conditionSubject for s, p, o in g)


def test_add_condition_subject_ref_no_slash():
    g = _graph()
    resource = types.SimpleNamespace(
        id="cond-4",
        identifier=None,
        subject=types.SimpleNamespace(reference="PatientNoSlash"),
        code=None,
    )
    _add_condition(g, resource)
    assert not any(p == HFT.conditionSubject for s, p, o in g)


# ------------------------------------------------------------------------------
# _add_service_request
# ------------------------------------------------------------------------------


def test_add_service_request_full():
    g = _graph()
    resource = types.SimpleNamespace(
        id="sr-1",
        identifier=[_identifier("SR001")],
        status="active",
        subject=_ref("Patient/p1"),
        code=_codeable_concept("GLU", "http://loinc.org"),
    )
    subj = _add_service_request(g, resource)
    assert (subj, RDF.type, HFT.ServiceRequest) in g
    assert (subj, HFT.status, Literal("active", datatype=XSD.string)) in g
    assert (subj, HFT.serviceRequestSubject, HFT["Patient_p1"]) in g
    assert any(p == HFT.hasCode for s, p, o in g)


def test_add_service_request_no_subject():
    g = _graph()
    resource = types.SimpleNamespace(
        id="sr-2", identifier=None, status=None, subject=None, code=None
    )
    _add_service_request(g, resource)
    assert not any(p == HFT.serviceRequestSubject for s, p, o in g)


def test_add_service_request_no_code():
    g = _graph()
    resource = types.SimpleNamespace(
        id="sr-3", identifier=None, status=None, subject=None, code=None
    )
    _add_service_request(g, resource)
    assert not any(p == HFT.hasCode for s, p, o in g)


def test_add_service_request_subject_ref_no_slash():
    g = _graph()
    resource = types.SimpleNamespace(
        id="sr-4",
        identifier=None,
        status=None,
        subject=types.SimpleNamespace(reference="PatientNoSlash"),
        code=None,
    )
    _add_service_request(g, resource)
    assert not any(p == HFT.serviceRequestSubject for s, p, o in g)


# ------------------------------------------------------------------------------
# _add_diagnostic_report
# ------------------------------------------------------------------------------


def test_add_diagnostic_report_full():
    g = _graph()
    resource = types.SimpleNamespace(
        id="dr-1",
        identifier=[_identifier("DR001")],
        status="final",
        subject=_ref("Patient/p1"),
        result=[_ref("Observation/obs-1")],
        basedOn=[_ref("ServiceRequest/sr-1")],
        issued="2025-01-01T09:00:00",
    )
    subj = _add_diagnostic_report(g, resource)
    assert (subj, RDF.type, HFT.DiagnosticReport) in g
    assert (subj, HFT.diagnosticReportSubject, HFT["Patient_p1"]) in g
    assert (subj, HFT.hasPart, HFT["Observation_obs-1"]) in g
    assert (subj, HFT.basedOn, HFT["ServiceRequest_sr-1"]) in g
    assert (
        subj,
        HFT.issuedDateTime,
        Literal("2025-01-01T09:00:00", datatype=XSD.dateTime),
    ) in g


def test_add_diagnostic_report_no_results():
    g = _graph()
    resource = types.SimpleNamespace(
        id="dr-2",
        identifier=None,
        status=None,
        subject=None,
        result=[],
        basedOn=[],
        issued=None,
    )
    _add_diagnostic_report(g, resource)
    assert not any(p == HFT.hasPart for s, p, o in g)


def test_add_diagnostic_report_no_based_on():
    g = _graph()
    resource = types.SimpleNamespace(
        id="dr-3",
        identifier=None,
        status=None,
        subject=None,
        result=None,
        basedOn=None,
        issued=None,
    )
    _add_diagnostic_report(g, resource)
    assert not any(p == HFT.basedOn for s, p, o in g)


def test_add_diagnostic_report_subject_ref_no_slash():
    g = _graph()
    resource = types.SimpleNamespace(
        id="dr-4",
        identifier=None,
        status=None,
        subject=types.SimpleNamespace(reference="PatientNoSlash"),
        result=None,
        basedOn=None,
        issued=None,
    )
    _add_diagnostic_report(g, resource)
    assert not any(p == HFT.diagnosticReportSubject for s, p, o in g)


def test_add_diagnostic_report_result_ref_no_reference_attr():
    g = _graph()
    resource = types.SimpleNamespace(
        id="dr-5",
        identifier=None,
        status=None,
        subject=None,
        result=[types.SimpleNamespace(reference=None)],
        basedOn=None,
        issued=None,
    )
    _add_diagnostic_report(g, resource)
    assert not any(p == HFT.hasPart for s, p, o in g)


def test_add_diagnostic_report_result_ref_no_slash():
    g = _graph()
    resource = types.SimpleNamespace(
        id="dr-6",
        identifier=None,
        status=None,
        subject=None,
        result=[types.SimpleNamespace(reference="ObservationNoSlash")],
        basedOn=None,
        issued=None,
    )
    _add_diagnostic_report(g, resource)
    assert not any(p == HFT.hasPart for s, p, o in g)


def test_add_diagnostic_report_based_on_ref_no_reference_attr():
    g = _graph()
    resource = types.SimpleNamespace(
        id="dr-7",
        identifier=None,
        status=None,
        subject=None,
        result=None,
        basedOn=[types.SimpleNamespace(reference=None)],
        issued=None,
    )
    _add_diagnostic_report(g, resource)
    assert not any(p == HFT.basedOn for s, p, o in g)


def test_add_diagnostic_report_based_on_ref_no_slash():
    g = _graph()
    resource = types.SimpleNamespace(
        id="dr-8",
        identifier=None,
        status=None,
        subject=None,
        result=None,
        basedOn=[types.SimpleNamespace(reference="ServiceRequestNoSlash")],
        issued=None,
    )
    _add_diagnostic_report(g, resource)
    assert not any(p == HFT.basedOn for s, p, o in g)


# ------------------------------------------------------------------------------
# serialize_resources
# ------------------------------------------------------------------------------


def test_serialize_resources_all_types():
    patient = types.SimpleNamespace(
        resource_type="Patient",
        id="p1",
        identifier=None,
        name=[],
        birthDate=None,
        gender=None,
    )
    encounter = types.SimpleNamespace(
        resource_type="Encounter",
        id="enc-1",
        identifier=None,
        status=None,
        subject=None,
    )
    observation = types.SimpleNamespace(
        resource_type="Observation",
        id="obs-1",
        identifier=None,
        status=None,
        subject=None,
        code=None,
        valueQuantity=None,
        valueString=None,
        effectiveDateTime=None,
    )
    condition = types.SimpleNamespace(
        resource_type="Condition",
        id="cond-1",
        identifier=None,
        subject=None,
        code=None,
    )
    sr = types.SimpleNamespace(
        resource_type="ServiceRequest",
        id="sr-1",
        identifier=None,
        status=None,
        subject=None,
        code=None,
    )
    dr = types.SimpleNamespace(
        resource_type="DiagnosticReport",
        id="dr-1",
        identifier=None,
        status=None,
        subject=None,
        result=None,
        basedOn=None,
        issued=None,
    )
    g = serialize_resources([patient, encounter, observation, condition, sr, dr])
    types_in_graph = {o for s, p, o in g if p == RDF.type}
    assert HFT.Patient in types_in_graph
    assert HFT.Encounter in types_in_graph
    assert HFT.Observation in types_in_graph
    assert HFT.Condition in types_in_graph
    assert HFT.ServiceRequest in types_in_graph
    assert HFT.DiagnosticReport in types_in_graph


def test_serialize_resources_unknown_type_skipped():
    resource = types.SimpleNamespace(resource_type="Practitioner", id="pr-1")
    g = serialize_resources([resource])
    assert len(g) == 0


def test_serialize_resources_empty_input():
    g = serialize_resources([])
    assert len(g) == 0


def test_serialize_resources_extends_existing_graph():
    existing = _graph()
    existing.add((HFT["Patient_p0"], RDF.type, HFT.Patient))
    patient = types.SimpleNamespace(
        resource_type="Patient",
        id="p1",
        identifier=None,
        name=[],
        birthDate=None,
        gender=None,
    )
    g = serialize_resources([patient], graph=existing)
    assert g is existing
    assert (HFT["Patient_p0"], RDF.type, HFT.Patient) in g
    assert (HFT["Patient_p1"], RDF.type, HFT.Patient) in g


def test_serialize_resources_prefixes_bound():
    g = serialize_resources([])
    bound = dict(g.namespaces())
    assert str(bound.get("hft")) == str(HFT)
    assert str(bound.get("fhir")) == str(FHIR)
    assert str(bound.get("xsd")) == str(XSD)


def test_serialize_resources_resource_type_fallback_to_resourceType():
    resource = types.SimpleNamespace(
        resource_type=None,
        resourceType="Patient",
        id="p1",
        identifier=None,
        name=[],
        birthDate=None,
        gender=None,
    )
    g = serialize_resources([resource])
    assert (HFT["Patient_p1"], RDF.type, HFT.Patient) in g


def test_serialize_resources_no_resource_type_skipped():
    resource = types.SimpleNamespace(resource_type=None, resourceType=None)
    g = serialize_resources([resource])
    assert len(g) == 0
