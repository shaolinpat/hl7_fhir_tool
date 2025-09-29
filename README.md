# HL7 -> FHIR Tool

[![CI](https://github.com/shaolinpat/ecg_cnn_pytorch/actions/workflows/ci.yml/badge.svg)](https://github.com/shaolinpat/hl7_fhir_tool/actions/workflows/ci.yml)
[![Coverage (flag)](https://img.shields.io/codecov/c/github/shaolinpat/ecg_cnn_pytorch.svg?flag=hl7_fhir_tool&branch=main)](https://codecov.io/gh/shaolinpat/hl7_fhir_tool)  
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)


A prototype Python package for parsing, validating, and transforming **HL7 v2** messages into **FHIR** resources.  
This project demonstrates healthcare data parsing, normalization, and CLI design with full test coverage.

---

## Features

- Parse HL7 v2 messages (using [`hl7apy`](https://crs4.github.io/hl7apy/))
- Parse FHIR JSON or XML (using [`pydantic-fhir`](https://github.com/nazrulworld/fhir.resources))
- Transform HL7 v2 → FHIR resource structures
- Minimal, production-style CLI for batch and file-level workflows
- 100% pytest coverage with CI/CD via GitHub Actions and Codecov

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

Examples:

```bash
# Parse HL7 v2 messages
python -m src.hl7_fhir_tool.cli parse-hl7 tests/data/adt_a01_251.hl7

# Parse FHIR JSON/XML
python -m src.hl7_fhir_tool.cli parse-fhir tests/data/patient.json

# Transform HL7 v2 → FHIR
python -m src.hl7_fhir_tool.cli transform tests/data/adt_a01_251.hl7 --stdout --pretty
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

This repository is a prototype intended to demonstrate:

- Familiarity with healthcare data standards (HL7 v2, FHIR)  
- Strong test coverage practices  
- Professional software engineering (CI/CD, packaging, typing)  

It is not intended for clinical or production use.

---

## License

MIT
