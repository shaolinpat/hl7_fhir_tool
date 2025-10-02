# src/hl7_fhir_tool/transform/v2_to_fhir/__init__.py
"""
Auto-discovery for v2_to_fhir transformers.

Any module under this package that defines a transformer and uses
@register("ADT^...") will be imported automatically by load_all().
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Iterable, Set

_DISCOVERED: Set[str] = set()


def _iter_modules(pkg_name: str) -> Iterable[str]:
    """
    Yield fully-qualified module names under the given package.

    Only direct Python modules and subpackages beneath pkg_name are returned.
    """
    pkg = importlib.import_module(pkg_name)
    pkg_path = getattr(pkg, "__path__", None)
    if not pkg_path:
        # Early exit for namespace-less packages -- keep generator semantics.
        return
    for _, name, _ in pkgutil.walk_packages(pkg_path, prefix=pkg_name + "."):
        yield name


def load_all() -> None:
    """
    Import all transformer modules under hl7_fhir_tool.transform.v2_to_fhir.

    Idempotent: safe to call multiple times.
    """
    base = __name__  # e.g., "hl7_fhir_tool.transform.v2_to_fhir"
    for modname in _iter_modules(base):
        if modname in _DISCOVERED:
            continue
        short = modname.rsplit(".", 1)[-1]
        # Skip private/dunder modules if any
        if short.startswith("_"):
            continue
        importlib.import_module(modname)
        _DISCOVERED.add(modname)


__all__ = ["load_all"]
