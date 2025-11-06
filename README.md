# HL7 -> FHIR Tool

[![CI](https://github.com/shaolinpat/ecg_cnn_pytorch/actions/workflows/ci.yml/badge.svg)](https://github.com/shaolinpat/hl7_fhir_tool/actions/workflows/ci.yml)
[![Coverage (flag)](https://img.shields.io/codecov/c/github/shaolinpat/ecg_cnn_pytorch.svg?flag=hl7_fhir_tool&branch=main)](https://codecov.io/gh/shaolinpat/hl7_fhir_tool)  
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A prototype Python package for parsing, validating, and transforming **HL7 v2** messages into **FHIR** resources.  
This project demonstrates healthcare data parsing, normalization, and CLI design with full test coverage.

---

## Table of Contents

- [Why This Project Matters](#why-this-project-matters)
  - [Why SPARQL and SHACL Belong Here](#why-sparql-and-shacl-belong-here)
  - [Where Java Fits](#where-java-fits)
- [Why LOINC Matters Here](#why-loinc-matters-here)
- [Why ICD-10 Matters Here](#why-icd-10-matters-here)
- [HL7 to FHIR Flow Diagram](#hl7-to-fhir-flow-diagram)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
  - [Parse HL7 v2 messages](#parse-hl7-v2-messages)
  - [Parse FHIR JSON or XML](#parse-fhir-json-or-xml)
  - [Transform HL7 v2 → FHIR](#transform-hl7-v2--fhir)
    - [ADT^A01 (Admit)](#adta01-admit)
    - [ADT^A03 (Discharge)](#adta03-discharge)
    - [List supported events](#list-supported-events)
- [Development](#development)
- [Continuous Integration](#continuous-integration)
- [Status](#status)

- [Ontology](#ontology)
- [SPARQL Testing](#sparql-testing)
- [SHACL Testing](#shacl-testing)

- [License](#license)

---

## Why This Project Matters

Healthcare systems still run on HL7 v2 (ADT/ORU/ORM messages) while modern interoperability and analytics increasingly depend on FHIR APIs and knowledge graphs. This repo bridges that gap:

- **HL7 v2 → FHIR**: Transforms core events (ADT^A01 admit, ADT^A03 discharge, ADT^A08 patient update, ORU lab results, ORM orders) into clean FHIR resources (Patient, Encounter, Observation, ServiceRequest, DiagnosticReport).  
- **Standards Alignment**: Positions legacy hospital feeds for use in FHIR-native apps, analytics platforms, and regulatory use cases (patient access, care coordination, research).  
- **Data Reuse**: Converts brittle, site-specific HL7 v2 streams into structured, web-friendly FHIR models that downstream systems can trust.  

### Why SPARQL and SHACL Belong Here

- **Knowledge Graph Analytics**: FHIR JSON is great for APIs, but cohort building, quality rules, and cross-encounter reasoning shine in RDF. Serializing FHIR to RDF enables:  
  - SPARQL queries for cohorts, outcomes, and KPI dashboards.  
  - SHACL constraints for data quality and conformance checks (e.g., every Encounter must have a Patient; Observations must have LOINC codes where expected).  

### Where Java Fits

- **Enterprise Connectors**: Many hospitals and integration engines run on the JVM. A Java module can:  
  - Consume the same FHIR outputs (via HAPI FHIR) for server-side validation, persistence, and RESTful exposure.  
  - Offer HL7 v2 interfaces where JVM-based tools (Mirth/NextGen Connect, Camel, Spring Integration) are standard.  
  - Run SHACL validation (via Java RDF libraries) and publish results to operational dashboards.  
- **Production Hardening**: JVM services can wrap the Python transforms for scale (queue workers, retries, circuit breakers) and integrate with existing enterprise logging and SSO.  

---

## Why LOINC Matters Here

Lab results and clinical observations are only as useful as the codes behind them. Different hospitals and labs label the same test in inconsistent ways ("Glucose, fasting plasma" vs. "FPG" vs. "GLU-F"). The Logical Observation Identifiers Names and Codes (LOINC) standard provides a universal vocabulary for lab tests, vital signs, and other measurements. 

- **HL7 v2**: ORU messages carry test identifiers in OBX segments, which can (and should) reference LOINC codes.  
- **FHIR**: Observations and DiagnosticReports are expected to use LOINC as their coding system, ensuring that "glucose test" means the same thing everywhere.  
- **RDF/SPARQL**: Once FHIR Observations are serialized into RDF, LOINC codes allow cross-institution queries like:  
  - "Find all patients with HbA1c (LOINC 4548-4) above 8.0."  
  - "Count distinct LOINC-coded blood pressure observations in the last 6 months."  
- **Java Integration**: Enterprise-grade tools can validate LOINC coding in Observations, enforce SHACL rules (e.g., "Every Observation must carry a valid LOINC code if it is a lab test"), and publish results to downstream systems.  

By including LOINC in the HL7 → FHIR transformation, this project not only normalizes messy legacy data but also anchors it in the globally recognized clinical coding ecosystem, enabling meaningful analytics, interoperability, and quality checks across systems.

---

## Why ICD-10 Matters Here

If LOINC tells us *what was measured*, ICD-10 tells us *what condition the patient has*. ICD-10 (International Classification of Diseases, 10th Revision) is the global standard for diagnoses, used in clinical care, research, and billing. Together with LOINC, it anchors HL7 → FHIR transformations in a standardized coding ecosystem.

- **HL7 v2**: Diagnoses typically appear in DG1 segments, where ICD-10 codes represent admitting, discharge, or encounter-associated conditions (e.g., E11.9 = Type 2 diabetes mellitus without complications).  
- **FHIR**: Diagnoses are captured as `Condition` resources with ICD-10 codes, linked to patients and encounters, and can be cross-referenced with Observations.  
- **RDF/SPARQL**: ICD-10 enables semantic queries such as:  
  - "Find all patients discharged with ICD-10 I21 (acute myocardial infarction)."  
  - "Count patients with ICD-10 E11.9 who also have an HbA1c (LOINC 4548-4) test over 8.0."  
- **Java Integration**: Enterprise-grade tools can validate ICD-10 coding in Conditions, enforce SHACL rules (e.g., "Every Encounter must reference at least one ICD-10-coded Condition"), and feed ICD-10-coded data into quality reporting or claims workflows.  

By including ICD-10 in the HL7 → FHIR transformation, this project does more than parse messages — it aligns patient encounters and diagnoses with internationally recognized codes. That ensures the data can be used reliably for analytics, interoperability, regulatory reporting, and reimbursement.

---

## HL7 to FHIR Flow Diagram

The diagram below summarizes how HL7 v2 messages (ADT, ORM, ORU) map to FHIR resources, and where ICD-10 and LOINC fit in.  
It also shows optional RDF/SPARQL/SHACL and Java integration layers.

![HL7 to FHIR Detailed Flow – Dark](images/hl7_fhir_detailed_flow_dark.png#gh-dark-mode-only)
![HL7 to FHIR Detailed Flow – Light](images/hl7_fhir_detailed_flow.png#gh-light-mode-only)


---

## Features

- Parse HL7 v2 messages (using [`hl7apy`](https://crs4.github.io/hl7apy/))
- Parse FHIR JSON or XML (using [`pydantic-fhir`](https://github.com/nazrulworld/fhir.resources))
- Transform HL7 v2 → FHIR resource structures (ADT^A01/A03/A08, ORM^O01, ORU^R01)
- Minimal, production-style CLI for batch and file-level workflows
- 100% pytest coverage with CI/CD via GitHub Actions and Codecov

> **Note:** This tool is intentionally **one-way (HL7 v2 → FHIR only)**. Reverse transformation (FHIR → HL7) is not supported.

---

## Installation

Clone the repo and create the Conda environment:

```bash
git clone git@github.com:shaolinpat/hl7_fhir_tool.git
cd hl7_fhir_tool
conda env create -f environment.yml
conda activate hl7_fhir_env
```

---

## Usage

The CLI is installed as a Python entry point. Run with:

```bash
python -m src.hl7_fhir_tool.cli --help
```

### Parse HL7 v2 messages
```bash
python -m src.hl7_fhir_tool.cli parse-hl7 tests/data/adt_a01_251.hl7
```
_Output (segments pretty-printed):_
```
MSH|^~\&|HIS|RIH|EKG|EKG|20250101123000||ADT^A01|MSG00001|P|2.5.1
EVN|A01|20250101123000
PID|1||12345^^^MRN||Doe^John^^^^^L||19700101|M|||123 Main St^^Cincinnati^OH^45220||5551234567
PV1|1|I|2000^2012^01||||1234^Physician^Primary
```

### Parse FHIR JSON or XML
```bash
python -m src.hl7_fhir_tool.cli parse-fhir tests/data/patient.json
```
_Output:_
```json
{
  "resourceType": "Patient",
  "id": "p1",
  "name": [
    {
      "family": "Doe",
      "given": [
        "John"
      ]
    }
  ],
  "gender": "male",
  "birthDate": "1970-01-01"
}
```

### Transform HL7 v2 → FHIR

#### ADT^A01 (Admit)
```bash
python -m src.hl7_fhir_tool.cli transform tests/data/adt_a01_251.hl7 --stdout --pretty
```
_Output:_
```json
{
  "resourceType": "Patient",
  "identifier": [
    {
      "value": "12345"
    }
  ],
  "name": [
    {
      "family": "Doe",
      "given": [
        "John"
      ]
    }
  ],
  "gender": "male",
  "birthDate": "1970-01-01"
}

{
  "resourceType": "Encounter",
  "status": "in-progress"
}
```

#### ADT^A03 (Discharge)

_Minimal example:_
```bash
python -m src.hl7_fhir_tool.cli transform tests/data/adt_a03_min.hl7 --stdout --pretty
```
_Output:_
```json
{
  "resourceType": "Patient",
  "id": "12345",
  "name": [
    {
      "family": "Doe",
      "given": [
        "Jane"
      ]
    }
  ]
}

{
  "resourceType": "Encounter",
  "id": "enc-12345",
  "status": "finished",
  "class": {
    "coding": [
      {
        "code": "I"
      }
    ]
  }
}
```

_With encounter period:_
```bash
python -m src.hl7_fhir_tool.cli transform tests/data/adt_a03_with_period.hl7 --stdout --pretty
```
_Output:_
```json
{
  "resourceType": "Patient",
  "id": "77777",
  "name": [
    {
      "family": "Alpha",
      "given": [
        "Test"
      ]
    }
  ]
}

{
  "resourceType": "Encounter",
  "id": "enc-77777",
  "status": "finished",
  "class": {
    "coding": [
      {
        "code": "I"
      }
    ]
  }
}
```

#### ORM^O01 (Order)

_Minimal example:_
```bash
python -m src.hl7_fhir_tool.cli transform tests/data/orm_o01_min.hl7 --stdout --pretty
```
_Output:_
```json
{
  "resourceType": "Patient",
  "id": "12345",
  "name": [
    {
      "family": "Doe",
      "given": [
        "John"
      ]
    }
  ],
  "gender": "male",
  "birthDate": "1970-01-01"
}

{
  "resourceType": "ServiceRequest",
  "id": "ORD123",
  "identifier": [
    {
      "value": "ORD123"
    }
  ],
  "status": "active",
  "intent": "order",
  "subject": {
    "reference": "Patient/12345"
  }
}

```

_With OBR-driven code (e.g., OBR-4):_
```bash
python -m src.hl7_fhir_tool.cli transform tests/data/orm_o01_glu.hl7 --stdout --pretty
```
_Output:_
```json
{
  "resourceType": "Patient",
  "id": "12345",
  "name": [
    {
      "family": "Doe",
      "given": [
        "John"
      ]
    }
  ],
  "gender": "male",
  "birthDate": "1970-01-01"
}

{
  "resourceType": "ServiceRequest",
  "id": "ORD123",
  "identifier": [
    {
      "value": "ORD123"
    }
  ],
  "status": "active",
  "intent": "order",
  "code": {
    "concept": {
      "coding": [
        {
          "code": "GLU"
        }
      ],
      "text": "Glucose"
    }
  },
  "subject": {
    "reference": "Patient/12345"
  }
}

```

_Mapping notes:_
- **ORC-2/ORC-3** → `ServiceRequest.identifier` (placer/filler numbers)
- **ORC-5** (order status) → `ServiceRequest.status` (e.g., `NW` ⇒ `active`, `CA` ⇒ `revoked`, `CM` ⇒ `completed`)
- **OBR-4** (Universal Service ID) → `ServiceRequest.code` (prefer LOINC when available)
- **PID** → `Patient` (linked via `ServiceRequest.subject`)

#### ORU^R01 (Observation Result)

_Minimal example:_
```bash
python -m src.hl7_fhir_tool.cli transform tests/data/oru_r01_min.hl7 --stdout --pretty
```
_Output:_
```json
{
  "resourceType": "Patient",
  "id": "P12345",
  "name": [
    {
      "family": "Doe",
      "given": [
        "Jane"
      ]
    }
  ],
  "gender": "female",
  "birthDate": "1983-05-14"
}

{
  "resourceType": "Observation",
  "id": "obs-P12345-1",
  "identifier": [
    {
      "value": "1234"
    },
    {
      "value": "5678"
    }
  ],
  "status": "final",
  "code": {
    "coding": [
      {
        "code": "GLU"
      }
    ],
    "text": "Glucose"
  },
  "subject": {
    "reference": "Patient/P12345"
  },
  "valueQuantity": {
    "value": 110.0,
    "unit": "mg/dL"
  }
}
```

_Mapping notes:_
- **OBR-2/OBR-3** → `Observation.identifier` (placer/filler numbers)
- **OBR-7** → `Observation.effectiveDateTime` (date/time of observation)
- **OBX-2/OBX-5/OBX-6** → `Observation.valueQuantity` or `Observation.valueString`
- **OBX-3** → `Observation.code` (use LOINC if available)
- **PID** → `Patient` (linked via `Observation.subject`)



### List supported events
```bash
python -m src.hl7_fhir_tool.cli transform - --list
```
_Output:_
```
Registered HL7 v2 → FHIR events:
    ADT^A01
    ADT^A03
    ADT^A08
    ORM^O01
    ORU^R01
```

---

## Development

Run tests with coverage:

```bash
pytest --cov=hl7_fhir_tool --cov-report=term --cov-report=xml
```

Static analysis and linting:

```bash
ruff check src tests
mypy
```

---

## Continuous Integration

- GitHub Actions runs the full test suite on each push/pull request
- Code coverage is uploaded to [Codecov](https://about.codecov.io/)

Badges are displayed at the top of this file.

---

## Status

This project is an evolving prototype interoperability toolkit, positioned at the intersection of healthcare standards and modern data engineering. It is not a production system, but it demonstrates:

- Healthcare standards mastery: HL7 v2 messaging, FHIR resource modeling, LOINC for labs, ICD-10 for diagnoses.
- Data transformation and normalization: Converting brittle HL7 v2 feeds into structured, FHIR-compliant resources.
- Knowledge graph readiness: RDF serialization, SPARQL queries, and SHACL validation for advanced analytics and conformance checking.
- Engineering practices: CI/CD, full test coverage, typed Python, modular CLI design, and integration pathways for Java ecosystems.

This tool is intended as a portfolio-quality demonstration of interoperability skills and engineering rigor. While not validated for clinical deployment, it showcases the foundations required to build scalable, standards-based healthcare data pipelines.

---


---

## Ontology

The **ontology** defines the RDF model that underpins HL7 → FHIR transformations.  
It lives in `rdf/ontology/hl7_fhir_tool_schema.ttl` and includes:

- **Core classes:** `Patient`, `Encounter`, `Observation`, `Condition`, `ServiceRequest`, and `DiagnosticReport`  
- **Object properties:** `hasSubject`, `hasCode`, `hasPart`, `basedOn`, etc.  
- **Data properties:** `identifier`, `birthDate`, `status`, `valueDecimal`, and related attributes  

These definitions ensure semantic integrity between transformed FHIR data and their relationships in RDF.  
Open it in **Protégé** or **TopBraid** for exploration or editing.

```bash
protege "file://$PWD/rdf/ontology/hl7_fhir_tool_schema.ttl"
```

---

## SPARQL Testing

SPARQL queries verify schema consistency, data quality, and analytic cohorts.  
Queries live under `rdf/queries/` and are grouped into subfolders:

| Directory | Purpose |
|------------|----------|
| `schema_checks/` | Structural validation of ontology (e.g., missing labels, misaligned subclasses) |
| `data_quality/` | Detect missing or invalid instance data (e.g., missing subjects, values, or codes) |
| `cohorts/` | Cohort definitions and clinical logic (e.g., Diabetes + HbA1c > 8.0) |

Run all SPARQL checks using Apache Jena’s **ARQ** engine:

```bash
bash tools/run_sparql_checks.sh
```

Example output excerpt:
```bash
== Cohorts (expect rows) ==
>>> rdf/queries/cohorts/cohort_e11_9_hba1c_over_8.rq
?patient  ?value
exi:Patient_p1001  "8.6"^^xsd:decimal
```

Schema and data-quality checks should return **no rows** (PASS).  
Cohort queries should return matching instances.

---

## SHACL Testing

SHACL shapes enforce structural and semantic conformance against the ontology.  
Shapes are organized under `rdf/shapes/`:

| Directory | Purpose |
|------------|----------|
| `data_checks/` | Instance-level data rules (subjects, values, units, relationships) |
| `schema_checks/` | Ontology-aligned schema-level rules |

Run SHACL validation via **pySHACL**:

```bash
python tools/run_shacl.py   --data rdf/instances/cohort_diabetes_e11_9_hb1ac_over_8.ttl   --shapes rdf/shapes/data_checks/*.ttl rdf/shapes/schema_checks/*.ttl   --inference rdfs   --report-out outputs/shacl_report.ttl
```

**Interpreting results:**
- `Conforms: True` → all shapes satisfied.  
- Warnings (e.g., HbA1c > 8.0) flag analytic exceptions but don’t fail validation.  
- Change `sh:severity sh:Warning` to `sh:severity sh:Violation` to make failures non-conforming.

---

## License

MIT
