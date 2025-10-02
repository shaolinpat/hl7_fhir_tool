# src/hl7_fhir_tool/transform/__init__.py
"""
Transform package initializer.

Automatically imports all v2_to_fhir transformer modules so their
@register(...) decorators run and populate the registry.
"""

from __future__ import annotations

from .v2_to_fhir import load_all as _load_v2

# Idempotent; safe if tests/CLI import this multiple times.
_load_v2()
