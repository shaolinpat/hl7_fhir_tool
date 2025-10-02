# tests/test_v2_to_fhir_loader.py
"""
Tests that hit src/hl7_fhir_tool/transform/v2_to_fhir/__init__.py
"""
import importlib
from types import SimpleNamespace


def test_iter_modules_no_pkg_path(monkeypatch):
    mod = importlib.import_module("hl7_fhir_tool.transform.v2_to_fhir")
    _iter_modules = getattr(mod, "_iter_modules")

    def fake_import(name):
        return SimpleNamespace()

    monkeypatch.setattr(importlib, "import_module", fake_import)
    assert list(_iter_modules("any.pkg")) == []


def test_load_all_skips_private_and_imports_public(monkeypatch):
    v2pkg = importlib.import_module("hl7_fhir_tool.transform.v2_to_fhir")
    load_all = getattr(v2pkg, "load_all")
    _iter_modules = getattr(v2pkg, "_iter_modules")

    monkeypatch.setattr(v2pkg, "_DISCOVERED", set(), raising=True)

    base = v2pkg.__name__  # "hl7_fhir_tool.transform.v2_to_fhir"

    # Fake walk: one public, one private, another public
    names = [
        f"{base}.adt_a01",
        f"{base}._helper_internal",
        f"{base}.adt_a03",
    ]

    # Patch _iter_modules to yield our names without touching pkgutil
    monkeypatch.setattr(
        v2pkg, "_iter_modules", lambda pkg_name: iter(names), raising=True
    )

    imported = []

    def fake_import(name):
        imported.append(name)
        # Return a dummy module object
        return SimpleNamespace(__name__=name)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    load_all()

    # Private module was skipped, public ones imported
    assert imported == [f"{base}.adt_a01", f"{base}.adt_a03"]


def test_load_all_idempotent(monkeypatch):
    v2pkg = importlib.import_module("hl7_fhir_tool.transform.v2_to_fhir")
    load_all = getattr(v2pkg, "load_all")

    # Reset discovered set
    monkeypatch.setattr(v2pkg, "_DISCOVERED", set(), raising=True)

    base = v2pkg.__name__
    names = [f"{base}.adt_a01"]

    # Provide deterministic module list
    monkeypatch.setattr(
        v2pkg, "_iter_modules", lambda pkg_name: iter(names), raising=True
    )

    calls = []

    def fake_import(name):
        calls.append(name)
        return SimpleNamespace(__name__=name)

    monkeypatch.setattr(importlib, "import_module", fake_import)

    # First call imports once
    load_all()
    # Second call should not import again
    load_all()

    assert calls == [f"{base}.adt_a01"]
