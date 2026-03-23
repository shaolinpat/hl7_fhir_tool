# src/hl7_fhir_tool/rdf_serializer.py
"""
Serialize FHIR resource objects into RDF/Turtle using the hft: ontology.

Each FHIR resource is typed to its hft: class, which declares rdfs:subClassOf
its canonical fhir: counterpart, and annotated with hft: data and object
properties drawn from hl7_fhir_tool_schema.ttl.

Supported resource types
------------------------
Patient, Encounter, Observation (+ NumericObservation), Condition,
ServiceRequest, DiagnosticReport.

Usage
-----
    from hl7_fhir_tool.rdf_serializer import serialize_resources

    graph = serialize_resources(fhir_resources)
    turtle_str = graph.serialize(format="turtle")
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Optional

from rdflib import Graph, Literal, Namespace, RDF, URIRef, XSD
from rdflib.namespace import RDFS

# ------------------------------------------------------------------------------
# namespaces
# ------------------------------------------------------------------------------

HFT = Namespace("https://w3id.org/shaolinpat/hft#")
FHIR = Namespace("http://hl7.org/fhir/")

# FHIR gender string -> hft: named individual
_GENDER_MAP: dict[str, URIRef] = {
    "male": HFT.male,
    "female": HFT.female,
    "other": HFT.other,
    "unknown": HFT.unknown,
}


# ------------------------------------------------------------------------------
# internal helpers
# ------------------------------------------------------------------------------


def _safe_get(obj, *attrs):
    """
    Traverse a dotted attribute chain, returning None on any miss.

    Parameters
    ----------
    obj : object
        Starting object.
    *attrs : str
        Attribute names to traverse in order.

    Returns
    -------
    object or None
        The value at the end of the chain, or None if any attribute is missing.
    """
    for attr in attrs:
        if obj is None:
            return None
        obj = getattr(obj, attr, None)
    return obj


def _resource_uri(resource_type: str, resource_id: str) -> URIRef:
    """
    Build a hft: URIRef for a resource instance.

    Parameters
    ----------
    resource_type : str
        FHIR resource type name, e.g., "Patient".
    resource_id : str
        Resource id value, e.g., "12345".

    Returns
    -------
    URIRef
        A URI of the form hft:Patient_12345.
    """
    return HFT[f"{resource_type}_{resource_id}"]


def _ref_to_uri(reference: str) -> Optional[URIRef]:
    """
    Convert a FHIR reference string to a hft: URIRef.

    Expects the form "ResourceType/id" (e.g., "Patient/12345").
    Returns None if the reference is missing or does not contain a slash.

    Parameters
    ----------
    reference : str
        FHIR relative reference string.

    Returns
    -------
    URIRef or None
        Corresponding hft: URI, or None if the reference is unusable.
    """
    if not reference or "/" not in reference:
        return None
    rtype, rid = reference.split("/", 1)
    return HFT[f"{rtype}_{rid}"]


def _first_coding_uri(code_obj) -> Optional[URIRef]:
    """
    Extract the first coding from a FHIR CodeableConcept and return a URIRef.

    Handles both direct .coding lists and the FHIR R5 .concept.coding nesting.

    Parameters
    ----------
    code_obj : object
        A FHIR CodeableConcept or equivalent pydantic model.

    Returns
    -------
    URIRef or None
        URI built from the first coding's system and code values,
        or None if no usable coding is present.
    """
    coding_list = (
        _safe_get(code_obj, "concept", "coding") or _safe_get(code_obj, "coding") or []
    )
    for coding in coding_list:
        code_val = _safe_get(coding, "code")
        if code_val:
            system = _safe_get(coding, "system") or "http://loinc.org"
            return URIRef(f"{system}/{code_val}")
    return None


def _add_identifiers(g: Graph, subj: URIRef, resource) -> None:
    """
    Emit hft:identifier triples for all identifier values on a resource.

    Parameters
    ----------
    g : Graph
        RDFLib graph to extend.
    subj : URIRef
        Subject URI for the resource individual.
    resource : object
        FHIR resource instance with an optional .identifier list.

    Returns
    -------
    None
    """
    for ident in getattr(resource, "identifier", None) or []:
        val = _safe_get(ident, "value")
        if val:
            g.add((subj, HFT.identifier, Literal(str(val), datatype=XSD.string)))


def _patient_uri_from_encounter(resource) -> Optional[URIRef]:
    """
    Derive the Patient URI for an Encounter.

    Tries resource.subject.reference first (FHIR standard). Falls back to
    extracting the patient id from the encounter id, which follows the
    convention enc-{patient_id} used by all ADT transformers in this project.

    Parameters
    ----------
    resource : object
        FHIR Encounter resource instance.

    Returns
    -------
    URIRef or None
        hft:Patient_{id} URI, or None if it cannot be determined.
    """
    # Prefer explicit subject reference
    ref_str = _safe_get(resource, "subject", "reference")
    if ref_str:
        uri = _ref_to_uri(ref_str)
        if uri:
            return uri

    # Fall back: enc-{patient_id} convention
    enc_id = getattr(resource, "id", None) or ""
    if enc_id.startswith("enc-"):
        patient_id = enc_id[4:]
        if patient_id:
            return HFT[f"Patient_{patient_id}"]

    return None


# ------------------------------------------------------------------------------
# per-resource-type serializers
# ------------------------------------------------------------------------------


def _add_patient(g: Graph, resource) -> URIRef:
    """
    Add Patient triples to the graph.

    Types the resource as hft:Patient and emits triples for hft:identifier,
    hft:family, hft:given, hft:birthDate, and hft:gender.

    Parameters
    ----------
    g : Graph
        RDFLib graph to extend.
    resource : fhir.resources.patient.Patient
        FHIR Patient resource instance.

    Returns
    -------
    URIRef
        The subject URI for this Patient individual.
    """
    rid = getattr(resource, "id", None) or "unknown"
    subj = _resource_uri("Patient", rid)
    g.add((subj, RDF.type, HFT.Patient))

    _add_identifiers(g, subj, resource)

    # Name -- use first HumanName entry
    names = getattr(resource, "name", None) or []
    if names:
        name = names[0]
        family = _safe_get(name, "family")
        if family:
            g.add((subj, HFT.family, Literal(str(family), datatype=XSD.string)))
        for given in getattr(name, "given", None) or []:
            g.add((subj, HFT.given, Literal(str(given), datatype=XSD.string)))

    # Birth date
    birth = getattr(resource, "birthDate", None)
    if birth:
        g.add((subj, HFT.birthDate, Literal(str(birth), datatype=XSD.date)))

    # Administrative gender
    gender_str = getattr(resource, "gender", None)
    if gender_str:
        gender_uri = _GENDER_MAP.get(str(gender_str).lower())
        if gender_uri:
            g.add((subj, HFT.gender, gender_uri))

    return subj


def _add_encounter(g: Graph, resource) -> URIRef:
    """
    Add Encounter triples to the graph.

    Types the resource as hft:Encounter and emits triples for hft:identifier,
    hft:status, and hft:encounterSubject.

    The patient URI is derived via _patient_uri_from_encounter, which checks
    resource.subject.reference first and falls back to the enc-{patient_id}
    id convention used by all ADT transformers in this project.

    Parameters
    ----------
    g : Graph
        RDFLib graph to extend.
    resource : fhir.resources.encounter.Encounter
        FHIR Encounter resource instance.

    Returns
    -------
    URIRef
        The subject URI for this Encounter individual.
    """
    rid = getattr(resource, "id", None) or "unknown"
    subj = _resource_uri("Encounter", rid)
    g.add((subj, RDF.type, HFT.Encounter))

    _add_identifiers(g, subj, resource)

    status = getattr(resource, "status", None)
    if status:
        g.add((subj, HFT.status, Literal(str(status), datatype=XSD.string)))

    pat_uri = _patient_uri_from_encounter(resource)
    if pat_uri:
        g.add((subj, HFT.encounterSubject, pat_uri))

    return subj


def _add_observation(g: Graph, resource) -> URIRef:
    """
    Add Observation triples to the graph.

    Types the resource as hft:NumericObservation when a valueQuantity is
    present, otherwise hft:Observation. Emits triples for hft:identifier,
    hft:status, hft:observationSubject, hft:hasCode, hft:valueDecimal,
    hft:hasUnit, hft:valueString, and hft:effectiveDateTime as available.

    Parameters
    ----------
    g : Graph
        RDFLib graph to extend.
    resource : fhir.resources.observation.Observation
        FHIR Observation resource instance.

    Returns
    -------
    URIRef
        The subject URI for this Observation individual.
    """
    rid = getattr(resource, "id", None) or "unknown"

    # Use hft:NumericalObservation when a quanitative value is present
    vq = getattr(resource, "valueQuantity", None)
    is_numeric = vq is not None and _safe_get(vq, "value") is not None
    rdf_class = HFT.NumericObservation if is_numeric else HFT.Observation

    subj = _resource_uri("Observation", rid)
    g.add((subj, RDF.type, rdf_class))

    _add_identifiers(g, subj, resource)

    status = getattr(resource, "status", None)
    if status:
        g.add((subj, HFT.status, Literal(str(status), datatype=XSD.string)))

    ref_str = _safe_get(resource, "subject", "reference")
    if ref_str:
        obs_pat = _ref_to_uri(ref_str)
        if obs_pat:
            g.add((subj, HFT.observationSubject, obs_pat))

    # Observation code -> hft:hasCode
    code_uri = _first_coding_uri(getattr(resource, "code", None))
    if code_uri:
        g.add((subj, HFT.hasCode, code_uri))

    # Numeric value + unit
    if is_numeric:
        try:
            g.add(
                (
                    subj,
                    HFT.valueDecimal,
                    Literal(Decimal(str(_safe_get(vq, "value"))), datatype=XSD.decimal),
                )
            )
        except (InvalidOperation, TypeError):
            pass
        unit = _safe_get(vq, "unit")
        if unit:
            g.add((subj, HFT.hasUnit, Literal(str(unit), datatype=XSD.string)))

    # String value
    vs = getattr(resource, "valueString", None)
    if vs:
        g.add((subj, HFT.valueString, Literal(str(vs), datatype=XSD.string)))

    # Effective date/time
    edt = getattr(resource, "effectiveDateTime", None)
    if edt:
        g.add((subj, HFT.effectiveDateTime, Literal(str(edt), datatype=XSD.dateTime)))

    return subj


def _add_condition(g: Graph, resource) -> URIRef:
    """
    Add Condition triples to the graph.

    Types the resource as hft:Condition and emits triples for hft:identifier,
    hft:conditionSubject, and hft:hasCode.

    Parameters
    ----------
    g : Graph
        RDFLib graph to extend.
    resource : fhir.resources.condition.Condition
        FHIR Condition resource instance.

    Returns
    -------
    URIRef
        The subject URI for this Condition individual.
    """
    rid = getattr(resource, "id", None) or "unknown"
    subj = _resource_uri("Condition", rid)
    g.add((subj, RDF.type, HFT.Condition))

    _add_identifiers(g, subj, resource)

    ref_str = _safe_get(resource, "subject", "reference")
    if ref_str:
        pat_uri = _ref_to_uri(ref_str)
        if pat_uri:
            g.add((subj, HFT.conditionSubject, pat_uri))

    code_uri = _first_coding_uri(getattr(resource, "code", None))
    if code_uri:
        g.add((subj, HFT.hasCode, code_uri))

    return subj


def _add_service_request(g: Graph, resource) -> URIRef:
    """
    Add ServiceRequest triples to the graph.

    Types the resource as hft:ServiceRequest and emits triples for
    hft:identifier, hft:status, hft:serviceRequestSubject, and hft:hasCode.

    Parameters
    ----------
    g : Graph
        RDFLib graph to extend.
    resource : fhir.resources.servicerequest.ServiceRequest
        FHIR ServiceRequest resource instance.

    Returns
    -------
    URIRef
        The subject URI for this ServiceRequest individual.
    """
    rid = getattr(resource, "id", None) or "unknown"
    subj = _resource_uri("ServiceRequest", rid)
    g.add((subj, RDF.type, HFT.ServiceRequest))

    _add_identifiers(g, subj, resource)

    status = getattr(resource, "status", None)
    if status:
        g.add((subj, HFT.status, Literal(str(status), datatype=XSD.string)))

    ref_str = _safe_get(resource, "subject", "reference")
    if ref_str:
        pat_uri = _ref_to_uri(ref_str)
        if pat_uri:
            g.add((subj, HFT.serviceRequestSubject, pat_uri))

    code_uri = _first_coding_uri(getattr(resource, "code", None))
    if code_uri:
        g.add((subj, HFT.hasCode, code_uri))

    return subj


def _add_diagnostic_report(g: Graph, resource) -> URIRef:
    """
    Add DiagnosticReport triples to the graph.

    Types the resource as hft:DiagnosticReport and emits triples for
    hft:identifier, hft:status, hft:diagnosticReportSubject, hft:hasPart,
    hft:basedOn, and hft:issuedDateTime.

    Parameters
    ----------
    g : Graph
        RDFLib graph to extend.
    resource : fhir.resources.diagnosticreport.DiagnosticReport
        FHIR DiagnosticReport resource instance.

    Returns
    -------
    URIRef
        The subject URI for this DiagnosticReport individual.
    """
    rid = getattr(resource, "id", None) or "unknown"
    subj = _resource_uri("DiagnosticReport", rid)
    g.add((subj, RDF.type, HFT.DiagnosticReport))

    _add_identifiers(g, subj, resource)

    status = getattr(resource, "status", None)
    if status:
        g.add((subj, HFT.status, Literal(str(status), datatype=XSD.string)))

    ref_str = _safe_get(resource, "subject", "reference")
    if ref_str:
        pat_uri = _ref_to_uri(ref_str)
        if pat_uri:
            g.add((subj, HFT.diagnosticReportSubject, pat_uri))

    # hasPart -- Observation results
    for result_ref in getattr(resource, "result", None) or []:
        obs_str = _safe_get(result_ref, "reference")
        if obs_str:
            obs_uri = _ref_to_uri(obs_str)
            if obs_uri:
                g.add((subj, HFT.hasPart, obs_uri))

    # basedOn -- ServiceRequest
    for based_ref in getattr(resource, "basedOn", None) or []:
        sr_str = _safe_get(based_ref, "reference")
        if sr_str:
            sr_uri = _ref_to_uri(sr_str)
            if sr_uri:
                g.add((subj, HFT.basedOn, sr_uri))

    issued = getattr(resource, "issued", None)
    if issued:
        g.add((subj, HFT.issuedDateTime, Literal(str(issued), datatype=XSD.dateTime)))

    return subj


# ------------------------------------------------------------------------------
# handlers table
# ------------------------------------------------------------------------------

_HANDLERS = {
    "Patient": _add_patient,
    "Encounter": _add_encounter,
    "Observation": _add_observation,
    "Condition": _add_condition,
    "ServiceRequest": _add_service_request,
    "DiagnosticReport": _add_diagnostic_report,
}


# ------------------------------------------------------------------------------
# public api
# ------------------------------------------------------------------------------


def serialize_resources(
    resources: Iterable,
    graph: Optional[Graph] = None,
) -> Graph:
    """
    Serialize FHIR resource objects into an RDFLib Graph.

    Each resource is typed to its hft: class (rdfs:subClassOf the canonical
    fhir: class) and annotated with hft: data and object properties as defined
    in hl7_fhir_tool_schema.ttl. Unknown resource types are silently skipped.

    After individual resource serialization, a second pass adds
    hft:hasCondition triples linking each Encounter to all Conditions that
    share the same patient subject. This mirrors the FHIR Encounter.diagnosis
    relationship and is required by the cohort SPARQL queries.

    Parameters
    ----------
    resources : Iterable
        FHIR resource instances (pydantic models from fhir.resources).
    graph : rdflib.Graph, optional
        Existing graph to extend. A fresh Graph is created when None.

    Returns
    -------
    rdflib.Graph
        Graph containing all serialized triples, with hft:, fhir:, xsd:, rdf:,
        and rdfs: prefixes bound for clean Turtle output.

    Notes
    -----
    Unknown resource types are silently skipped; the caller can detect them by
    comparing len(resources) against g.subjects() if needed.
    """
    g = graph if graph is not None else Graph()
    g.bind("hft", HFT)
    g.bind("fhir", FHIR)
    g.bind("xsd", XSD)
    g.bind("rdf", RDF)
    g.bind("rdfs", RDFS)

    # Collect encounter and condition URIs keyed by patient URI for the
    # second-pass hft:hasCondition linking step.
    encounter_by_patient: dict[URIRef, List[URIRef]] = defaultdict(list)
    condition_by_patient: dict[URIRef, List[URIRef]] = defaultdict(list)

    resource_list = list(resources)

    for resource in resource_list:
        rtype = (
            getattr(resource, "resource_type", None)
            or getattr(resource, "resourceType", None)
            or type(resource).__name__
        )
        handler = _HANDLERS.get(str(rtype) if rtype else "")
        if not handler:
            continue

        subj = handler(g, resource)

        # Track encounters and conditions by patient for second pass.
        if str(rtype) == "Encounter":
            pat_uri = _patient_uri_from_encounter(resource)
            if pat_uri:
                encounter_by_patient[pat_uri].append(subj)

        elif str(rtype) == "Condition":
            ref_str = _safe_get(resource, "subject", "reference")
            if ref_str:
                pat_uri = _ref_to_uri(ref_str)
                if pat_uri:
                    condition_by_patient[pat_uri].append(subj)

    # Second pass: link each Encounter to all Conditions sharing its patient.
    for pat_uri, enc_uris in encounter_by_patient.items():
        cond_uris = condition_by_patient.get(pat_uri, [])
        for enc_uri in enc_uris:
            for cond_uri in cond_uris:
                g.add((enc_uri, HFT.hasCondition, cond_uri))

    return g
