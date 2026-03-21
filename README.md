# HL7 -> FHIR Tool

[![CI](https://github.com/shaolinpat/hl7_fhir_tool/actions/workflows/ci.yml/badge.svg)](https://github.com/shaolinpat/hl7_fhir_tool/actions/workflows/ci.yml)
[![Coverage (flag)](https://img.shields.io/codecov/c/github/shaolinpat/hl7_fhir_tool.svg?flag=hl7_fhir_tool&branch=main)](https://codecov.io/gh/shaolinpat/hl7_fhir_tool)  
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

This project demonstrates a complete HL7 -> FHIR -> RDF interoperability pipeline. HL7 v2 messages (ADT, ORM, ORU) are transformed into linked FHIR resources -- Patient, Encounter, Condition, ServiceRequest, Observation, DiagnosticReport -- with ICD-10 and LOINC code bindings. These FHIR resources are then serialized into RDF/Turtle, forming a coherent graph that supports SHACL-based data quality validation and SPARQL cohort queries. The result is a full proof-of-concept showing how legacy HL7 feeds can be normalized into FHIR and elevated into a semantic data layer suitable for analytics, reasoning, and deployment in a graph database such as GraphDB or Apache Jena.

---

## Table of Contents

- [Why This Project Matters](#why-this-project-matters)
  - [Why SPARQL and SHACL Belong Here](#why-sparql-and-shacl-belong-here)
  - [Java Integration Pathways](#java-integration-pathways)
- [Why LOINC Matters Here](#why-loinc-matters-here)
- [Why ICD-10 Matters Here](#why-icd-10-matters-here)
- [HL7 to FHIR Flow Diagram](#hl7-to-fhir-flow-diagram)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
  - [Parse HL7 v2 messages](#parse-hl7-v2-messages)
  - [Parse FHIR JSON or XML](#parse-fhir-json-or-xml)
  - [Transform HL7 v2 -> FHIR](#transform-hl7-v2--fhir)
    - [ADT^A01 (Admit)](#adta01-admit)
    - [ADT^A03 (Discharge)](#adta03-discharge)
    - [ORM^O01 (Order)](#ormo01-order)
    - [ORU^R01 (Observation Result)](#orur01-observation-result)
    - [List supported events](#list-supported-events)
  - [Serialize FHIR -> RDF](#serialize-fhir---rdf)
- [HL7 Stream Generator](#hl7-stream-generator)
- [Development](#development)
- [Continuous Integration](#continuous-integration)
- [Status](#status)
- [Ontology Model](#ontology-model)
- [GraphDB Integration](#graphdb-integration)
- [SPARQL Testing](#sparql-testing)
- [SHACL Testing](#shacl-testing)
- [License](#license)

---

## Why This Project Matters

Healthcare systems still run on HL7 v2 (ADT/ORU/ORM messages) while modern interoperability and analytics increasingly depend on FHIR APIs and knowledge graphs. This repo bridges that gap:

- **HL7 v2 -> FHIR**: Transforms core events (ADT^A01 admit, ADT^A03 discharge, ADT^A08 patient update, ORU lab results, ORM orders) into clean FHIR resources (Patient, Encounter, Condition, Observation, ServiceRequest, DiagnosticReport).  
- **Standards Alignment**: Positions legacy hospital feeds for use in FHIR-native apps, analytics platforms, and regulatory use cases (patient access, care coordination, research).  
- **Data Reuse**: Converts brittle, site-specific HL7 v2 streams into structured, web-friendly FHIR models that downstream systems can trust.  

### Why SPARQL and SHACL Belong Here

- **Knowledge Graph Analytics**: FHIR JSON is great for APIs, but cohort building, quality rules, and cross-encounter reasoning shine in RDF. Serializing FHIR to RDF enables:  
  - SPARQL queries for cohorts, outcomes, and KPI dashboards.  
  - SHACL constraints for data quality and conformance checks (e.g., every Encounter must have a Patient; Observations must have LOINC codes where expected).  

### Java Integration Pathways

A Java integration layer is planned for a future phase. Many hospitals and integration engines run on the JVM, and the FHIR outputs this pipeline produces are well-suited for consumption by HAPI FHIR, Mirth/NextGen Connect, and Spring Integration. See the open issue for scope and design notes.

---

## Why LOINC Matters Here

Lab results and clinical observations are only as useful as the codes behind them. Different hospitals and labs label the same test in inconsistent ways ("Glucose, fasting plasma" vs. "FPG" vs. "GLU-F"). The Logical Observation Identifiers Names and Codes (LOINC) standard provides a universal vocabulary for lab tests, vital signs, and other measurements.

- **HL7 v2**: ORU messages carry test identifiers in OBX segments, which can (and should) reference LOINC codes.  
- **FHIR**: Observations and DiagnosticReports are expected to use LOINC as their coding system, ensuring that "glucose test" means the same thing everywhere.  
- **RDF/SPARQL**: Once FHIR Observations are serialized into RDF, LOINC codes allow cross-institution queries like:  
  - "Find all patients with HbA1c (LOINC 4548-4) above 8.0."  
  - "Count distinct LOINC-coded blood pressure observations in the last 6 months."  

By including LOINC in the HL7 -> FHIR transformation, this project not only normalizes messy legacy data but also anchors it in the globally recognized clinical coding ecosystem, enabling meaningful analytics, interoperability, and quality checks across systems.

---

## Why ICD-10 Matters Here

If LOINC tells us *what was measured*, ICD-10 tells us *what condition the patient has*. ICD-10 (International Classification of Diseases, 10th Revision) is the global standard for diagnoses, used in clinical care, research, and billing. Together with LOINC, it anchors HL7 -> FHIR transformations in a standardized coding ecosystem.

- **HL7 v2**: Diagnoses typically appear in DG1 segments, where ICD-10 codes represent admitting, discharge, or encounter-associated conditions (e.g., E11.9 = Type 2 diabetes mellitus without complications).  
- **FHIR**: Diagnoses are captured as `Condition` resources with ICD-10 codes, linked to patients and encounters, and can be cross-referenced with Observations.  
- **RDF/SPARQL**: ICD-10 enables semantic queries such as:  
  - "Find all patients discharged with ICD-10 I21 (acute myocardial infarction)."  
  - "Count patients with ICD-10 E11.9 who also have an HbA1c (LOINC 4548-4) test over 8.0."  

By including ICD-10 in the HL7 -> FHIR transformation, this project does more than parse messages -- it aligns patient encounters and diagnoses with internationally recognized codes. That ensures the data can be used reliably for analytics, interoperability, regulatory reporting, and reimbursement.

---

## HL7 to FHIR Flow Diagram

The diagram below summarizes how HL7 v2 messages (ADT, ORM, ORU) map to FHIR resources, and where ICD-10 and LOINC fit in.  
It also shows RDF/SPARQL/SHACL and (yet to be implemented) Java integration layers.

![HL7 to FHIR Detailed Flow -- Dark](images/hl7_fhir_detailed_flow_dark.png#gh-dark-mode-only)
![HL7 to FHIR Detailed Flow -- Light](images/hl7_fhir_detailed_flow.png#gh-light-mode-only)

---

## Features

- Parse HL7 v2 messages (using [`hl7apy`](https://crs4.github.io/hl7apy/))
- Parse FHIR JSON or XML (using [`fhir.resources`](https://github.com/nazrulworld/fhir.resources))
- Transform HL7 v2 -> FHIR resource structures (ADT^A01/A03/A08, ORM^O01, ORU^R01)
- DG1 segment parsing -> FHIR Condition resources with ICD-10 code bindings (ADT^A01/A03/A08)
- Serialize FHIR resources -> RDF/Turtle using a custom OWL ontology (hft: namespace, rdfs:subClassOf fhir:)
- Load RDF output into GraphDB and run SPARQL cohort queries
- Minimal, production-style CLI for batch and file-level workflows
- 100% pytest coverage with CI/CD via GitHub Actions and Codecov

> **Note:** This tool is intentionally **one-way (HL7 v2 -> FHIR only)**. Reverse transformation (FHIR -> HL7) is not supported.

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

### Transform HL7 v2 -> FHIR

#### ADT^A01 (Admit)

_Without DG1:_
```bash
python -m src.hl7_fhir_tool.cli transform tests/data/adt_a01_251.hl7 --stdout --pretty
```
_Output:_
```json
{
  "resourceType": "Patient",
  "id": "12345",
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

_With DG1 (ICD-10 diagnosis):_
```bash
python -m src.hl7_fhir_tool.cli transform tests/data/adt_a01_with_dg1.hl7 --stdout --pretty
```
_Output:_
```json
{
  "resourceType": "Patient",
  "id": "12345",
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

{
  "resourceType": "Condition",
  "id": "cond-12345-1",
  "code": {
    "coding": [
      {
        "system": "http://hl7.org/fhir/sid/icd-10",
        "code": "E11.9"
      }
    ],
    "text": "Type 2 diabetes mellitus without complications"
  },
  "subject": {
    "reference": "Patient/12345"
  }
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
- **ORC-2/ORC-3** -> `ServiceRequest.identifier` (placer/filler numbers)
- **ORC-5** (order status) -> `ServiceRequest.status` (e.g., `NW` -> `active`, `CA` -> `revoked`, `CM` -> `completed`)
- **OBR-4** (Universal Service ID) -> `ServiceRequest.code` (prefer LOINC when available)
- **PID** -> `Patient` (linked via `ServiceRequest.subject`)

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
- **OBR-2/OBR-3** -> `Observation.identifier` (placer/filler numbers)
- **OBR-7** -> `Observation.effectiveDateTime` (date/time of observation)
- **OBX-2/OBX-5/OBX-6** -> `Observation.valueQuantity` or `Observation.valueString`
- **OBX-3** -> `Observation.code` (use LOINC if available)
- **PID** -> `Patient` (linked via `Observation.subject`)

### List supported events

```bash
python -m src.hl7_fhir_tool.cli transform - --list
```
_Output:_
```
Registered HL7 v2 -> FHIR events:
    ADT^A01
    ADT^A03
    ADT^A08
    ORM^O01
    ORU^R01
```

### Serialize FHIR -> RDF

The `to-rdf` command runs the full HL7 -> FHIR -> RDF pipeline in one step and writes a Turtle file.

```bash
python -m src.hl7_fhir_tool.cli to-rdf tests/data/oru_r01_min.hl7 --output-dir out/
```
_Output:_
```
Wrote out/oru_r01_min.ttl  (12 triples)
```

_Sample Turtle output:_
```turtle
@prefix hft: <http://example.org/hl7-fhir-tool#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

hft:Observation_obs-P12345-1 a hft:NumericObservation ;
    hft:hasCode <http://example.org/code/GLU> ;
    hft:hasUnit "mg/dL"^^xsd:string ;
    hft:identifier "1234"^^xsd:string,
        "5678"^^xsd:string ;
    hft:observationSubject hft:Patient_P12345 ;
    hft:status "final"^^xsd:string ;
    hft:valueDecimal 110.0 .

hft:Patient_P12345 a hft:Patient ;
    hft:birthDate "1983-05-14"^^xsd:date ;
    hft:family "Doe"^^xsd:string ;
    hft:gender hft:female ;
    hft:given "Jane"^^xsd:string .
```

_ADT^A01 with DG1 (ICD-10 diagnosis):_
```bash
python -m src.hl7_fhir_tool.cli to-rdf tests/data/adt_a01_with_dg1.hl7 --output-dir out/
```
_Output:_
```
Wrote out/adt_a01_with_dg1.ttl  (11 triples)
```

_Turtle output:_
```turtle
@prefix hft: <http://example.org/hl7-fhir-tool#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

hft:Condition_cond-12345-1 a hft:Condition ;
    hft:conditionSubject hft:Patient_12345 ;
    hft:hasCode <http://hl7.org/fhir/sid/icd-10/E11.9> .

hft:Encounter_unknown a hft:Encounter ;
    hft:status "in-progress"^^xsd:string .

hft:Patient_12345 a hft:Patient ;
    hft:birthDate "1970-01-01"^^xsd:date ;
    hft:family "Doe"^^xsd:string ;
    hft:gender hft:male ;
    hft:given "John"^^xsd:string ;
    hft:identifier "12345"^^xsd:string .
```

Each hft: class declares `rdfs:subClassOf` its canonical fhir: counterpart, making the hft: namespace an extension of FHIR rather than a parallel vocabulary. Queries and reasoners operating on fhir: terms will pick up hft: individuals through the subclass link.

Write to stdout instead of a file:

```bash
python -m src.hl7_fhir_tool.cli to-rdf tests/data/oru_r01_min.hl7 --stdout
```

---

## HL7 Stream Generator

A synthetic HL7 v2.5.1 generator is included for producing realistic test streams for all supported message types (ADT^A01, ADT^A03, ADT^A08, ORM^O01, ORU^R01).  
It generates pure HL7 messages and can output:

- Individual `.hl7` files (one per message)
- A single concatenated HL7 stream file for ingestion into the transformation pipeline

ADT messages (A01, A03, A08) include a `DG1` segment with a randomly selected ICD-10 code drawn from a built-in pool of eight common diagnoses. ORM and ORU messages do not include DG1.

Example (300-message mixed stream):

```bash
python scripts/generate_hl7_adt_a01_bulk.py \
    --count 300 \
    --message-type mixed_registered \
    --out tests/data/bulk_mixed_300 \
    --stream-file tests/data/hl7_stream/mixed_300.hl7 \
    --seed 22 \
    --line-endings cr
```

The generator is deterministic under a fixed seed and does not create any FHIR or RDF output; it is used solely for producing input for the transformation layer.

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
- End-to-end pipeline: HL7 v2 messages loaded into GraphDB as RDF triples and queried with SPARQL. The current test corpus (3 HL7 messages covering ADT, ORM, and ORU) produces 123 RDF triples.
- Engineering practices: CI/CD, full test coverage, typed Python, modular CLI design.

This tool is intended as a portfolio-quality demonstration of interoperability skills and engineering rigor. While not validated for clinical deployment, it showcases the foundations required to build scalable, standards-based healthcare data pipelines.

---

## Ontology Model

The **ontology** defines the RDF model that underpins HL7 -> FHIR transformations.  
It lives in `rdf/ontology/hl7_fhir_tool_schema.ttl` and includes:

- **Core classes:** `Patient`, `Encounter`, `Observation`, `Condition`, `ServiceRequest`, and `DiagnosticReport`  
- **Object properties:** `hasSubject`, `hasCode`, `hasPart`, `basedOn`, etc.  
- **Data properties:** `identifier`, `birthDate`, `status`, `valueDecimal`, and related attributes  

Each hft: class declares `rdfs:subClassOf` its canonical fhir: counterpart. This alignment makes hft: an extension of FHIR rather than a parallel vocabulary -- queries and reasoners operating on fhir: terms will pick up hft: individuals through the subclass link.

Open it in **Protege** or **TopBraid** for exploration or editing.

```bash
protege "file://$PWD/rdf/ontology/hl7_fhir_tool_schema.ttl"
```

---

## GraphDB Integration

RDF output from the pipeline can be loaded directly into GraphDB for SPARQL querying and graph exploration.

### Loading data

1. Create a repository in the GraphDB Workbench: **Setup -> Repositories -> Create new repository**
2. Switch to the new repository
3. Import Turtle files: **Import -> RDF Files -> Upload Files**

### Cohort query example

The query below finds all patients with a Type 2 diabetes diagnosis (ICD-10 E11.9) who also have an HbA1c observation (LOINC 4548-4) above 8.0. It runs against `tests/data/cohort_sample.ttl`, which is included in the repo as a reference dataset.

```sparql
PREFIX hft: <http://example.org/hl7-fhir-tool#>

SELECT ?patient ?family ?value WHERE {
  ?patient a hft:Patient ;
           hft:family ?family .
  ?cond hft:conditionSubject ?patient ;
        hft:hasCode <http://hl7.org/fhir/sid/icd-10/E11.9> .
  ?obs hft:observationSubject ?patient ;
       hft:hasCode <http://loinc.org/4548-4> ;
       hft:valueDecimal ?value .
  FILTER (?value > 8.0)
}
```

![GraphDB cohort query result](images/graphdb_cohort_query.png)

---

## SPARQL Testing

SPARQL queries verify schema consistency, data quality, and analytic cohorts.  
Queries live under `rdf/queries/` and are grouped into subfolders:

| Directory | Purpose |
|------------|----------|
| `schema_checks/` | Structural validation of ontology (e.g., missing labels, misaligned subclasses) |
| `data_quality/` | Detect missing or invalid instance data (e.g., missing subjects, values, or codes) |
| `cohorts/` | Cohort definitions and clinical logic (e.g., Diabetes + HbA1c > 8.0) |

Run all SPARQL checks using Apache Jena's **ARQ** engine:

```bash
bash tools/run_sparql_checks.sh
```

Example output excerpt:
```
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

Run SHACL validation via **pySHACL** on **one** data file:

```bash
    python tools/run_shacl.py \
        --data \
            tests/data/fhir_valid.ttl \
        --shapes \
            src/hl7_fhir_tool/shacl/modules/*.ttl \
            rdf/shapes/data_checks/*.ttl \
            rdf/shapes/schema_checks/*.ttl
```

Expected output:
```
--- SHACL Validation Suite --------------------------------------------
Inference     : rdfs
Shapes Loaded : 10
-----------------------------------------------------------------------
[  1/1] PASS  tests/data/fhir_valid.ttl
-----------------------------------------------------------------------
Files Checked : 1
Failures      : 0
Warnings (sum): 0
Result        : ALL EXPECTATIONS MET
```

Run SHACL validation via **pySHACL** on **multiple** data files where some are marked as expected to violate. The ones that violate as expected are passes:

```bash
    python tools/run_shacl.py \
        --data \
            tests/data/*.ttl \
        --shapes \
            src/hl7_fhir_tool/shacl/modules/*.ttl \
            rdf/shapes/data_checks/*.ttl \
            rdf/shapes/schema_checks/*.ttl \
        --expected-fail \
            tests/data/fhir_bad_closed.ttl \
            tests/data/fhir_bad_values.ttl
```

Expected output:
```
--- SHACL Validation Suite --------------------------------------------
Inference     : rdfs
Shapes Loaded : 10
Expected-Fail : 2
-----------------------------------------------------------------------
[  1/3] PASS (expected violations)  tests/data/fhir_bad_closed.ttl
      Details : Violations=1
[  2/3] PASS (expected violations)  tests/data/fhir_bad_values.ttl
      Details : Violations=2
[  3/3] PASS  tests/data/fhir_valid.ttl
-----------------------------------------------------------------------
Files Checked : 3
Failures      : 0
Warnings (sum): 0
Result        : ALL EXPECTATIONS MET
```

A run on the same shapes and data **without** `--expected-fail` produces failures:

```bash
    python tools/run_shacl.py \
        --data \
            tests/data/*.ttl \
        --shapes \
            src/hl7_fhir_tool/shacl/modules/*.ttl \
            rdf/shapes/data_checks/*.ttl \
            rdf/shapes/schema_checks/*.ttl
```

Expected output:
```
--- SHACL Validation Suite --------------------------------------------
Inference     : rdfs
Shapes Loaded : 10
-----------------------------------------------------------------------
[  1/3] FAIL  tests/data/fhir_bad_closed.ttl
      Details : Violations=1
[  2/3] FAIL  tests/data/fhir_bad_values.ttl
      Details : Violations=2
[  3/3] PASS  tests/data/fhir_valid.ttl
-----------------------------------------------------------------------
Files Checked : 3
Failures      : 0
Warnings (sum): 0
Result        : EXPECTATIONS NOT MET
```

Include `--details fail` or `--details all` for verbose output:

```bash
    python tools/run_shacl.py \
        --data \
            tests/data/*.ttl \
        --shapes \
            src/hl7_fhir_tool/shacl/modules/*.ttl \
            rdf/shapes/data_checks/*.ttl \
            rdf/shapes/schema_checks/*.ttl \
        --expected-fail \
            tests/data/fhir_bad_closed.ttl \
            tests/data/fhir_bad_values.ttl \
        --details all
```

Expected output:
```
--- SHACL Validation Suite --------------------------------------------
Inference     : rdfs
Shapes Loaded : 10
Expected-Fail : 2
-----------------------------------------------------------------------
[  1/3] PASS (expected violations)  tests/data/fhir_bad_closed.ttl
      Details : Violations=1
      ----- Validation Report (pySHACL) -----
Validation Report
Conforms: False
Results (1):
Constraint Violation in ClosedConstraintComponent (http://www.w3.org/ns/shacl#ClosedConstraintComponent):
        Severity: sh:Violation
        Source Shape: <http://example.org/hl7-fhir-tool#PatientClosedShape>
        Focus Node: ex:P2
        Value Node: Literal("oops")
        Result Path: <http://hl7.org/fhir/unknownProp>
        Message: Patient contains an unexpected property (closed-shape violation).

      ---------------------------------------
      Total Results : 1
      Data File     : tests/data/fhir_bad_closed.ttl
      Inference     : rdfs

[  2/3] PASS (expected violations)  tests/data/fhir_bad_values.ttl
      Details : Violations=2
      ----- Validation Report (pySHACL) -----
Validation Report
Conforms: False
Results (2):
Constraint Violation in MinCountConstraintComponent (http://www.w3.org/ns/shacl#MinCountConstraintComponent):
        Severity: sh:Violation
        Source Shape: [ sh:message Literal("Encounter must reference a Patient (encounterSubject/subject).") ; sh:minCount Literal("1", datatype=xsd:integer) ; sh:path [ sh:alternativePath ( <http://example.org/hl7-fhir-tool#encounterSubject> <http://hl7.org/fhir/subject> ) ] ; sh:severity sh:Violation ]
        Focus Node: ex:E2
        Result Path: [ sh:alternativePath ( <http://example.org/hl7-fhir-tool#encounterSubject> <http://hl7.org/fhir/subject> ) ]
        Message: Encounter must reference a Patient (encounterSubject/subject).
Constraint Violation in InConstraintComponent (http://www.w3.org/ns/shacl#InConstraintComponent):
        Severity: sh:Violation
        Source Shape: [ sh:message Literal("Status must be a permitted value for this resource.") ; sh:path [ sh:alternativePath ( <http://example.org/hl7-fhir-tool#status> <http://hl7.org/fhir/status> ) ] ; sh:severity sh:Violation ]
        Focus Node: ex:SR2
        Value Node: Literal("bogus")
        Result Path: [ sh:alternativePath ( <http://example.org/hl7-fhir-tool#status> <http://hl7.org/fhir/status> ) ]
        Message: Status must be a permitted value for this resource.

      ---------------------------------------
      Total Results : 2
      Data File     : tests/data/fhir_bad_values.ttl
      Inference     : rdfs

[  3/3] PASS  tests/data/fhir_valid.ttl
      ----- Validation Report (pySHACL) -----
Validation Report
Conforms: True

      ---------------------------------------
      Total Results : 0
      Data File     : tests/data/fhir_valid.ttl
      Inference     : rdfs

-----------------------------------------------------------------------
Files Checked       : 3
Failures      : 0
Warnings (sum): 0
Result        : ALL EXPECTATIONS MET
```

**Interpreting results:**
- `ALL EXPECTATIONS MET` -> all shapes satisfied.
- `EXPECTATIONS NOT MET` -> not all shapes satisfied.

---

## License

MIT
