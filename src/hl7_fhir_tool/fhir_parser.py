# src/hl7_fhir_tool/fhir_parser.py
"""
FHIR parsing utilities.

Provides loaders for FHIR JSON and XML files that return validated
`fhir.resources` model instances. Unknown resource types fall back to
the base `Resource` model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Type

import json
from lxml import etree
from fhir.resources.resource import Resource
from fhir.resources.patient import Patient
from fhir.resources.observation import Observation
from fhir.resources.bundle import Bundle
from pydantic import BaseModel, ValidationError
from .exceptions import ParseError

# Known FHIR resource classes you want first-class parsing for.
# Extend this as needed.
KNOWN_TYPES: Mapping[str, Type[Resource]] = {
    "Patient": Patient,
    "Observation": Observation,
    "Bundle": Bundle,
}


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _ensure_file(path: Path) -> None:
    """Validate that a path exists and is a file; raise ParseError if not."""
    if not isinstance(path, Path):
        raise ParseError(f"path must be pathlib.Path, got {type(path).__name__}")
    if not path.exists():
        raise ParseError(f"file does not exist: {path}")
    if not path.is_file():
        raise ParseError(f"not a file: {path}")


def _local(tag: str) -> str:
    """Return the local (namespace-stripped) tag name."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _xml_to_obj(elem) -> Any:
    """
    Convert a FHIR XML element subtree into a minimal JSON-like object.

    Rules
    -----
    - If element has a 'value' attribute and no element children -> return that scalar.
    - Otherwise, build a dict of child elements; repeated child tags become lists.
    - Attributes other than 'value' are ignored for now.
    - Namespaces are stripped; only local names are used.

    This is intentionally conservative: it is sufficient for common fields like:
      <id value="p1"/>, <name><family value="Doe"/><given value="John"/></name>,
      repeated elements (e.g., multiple <identifier>).

    Unsupported (for now)
    ---------------------
    - FHIR primitive extensions (the _field mirror).
    - Choice elements beyond simple value-attributes.
    - Contained resources and advanced backbone elements.

    These can be added iteratively without changing the public API.
    """
    # If there are no element children and a 'value' attribute, return the scalar.
    children = [c for c in elem if isinstance(c.tag, str)]
    val = elem.get("value")
    if val is not None and not children:
        return val

    # Otherwise, build a shallow dict from direct children.
    out: Dict[str, Any] = {}
    for child in children:
        name = _local(child.tag)
        child_obj = _xml_to_obj(child)
        if name in out:
            # promote to a list on repeat
            if not isinstance(out[name], list):
                out[name] = [out[name]]
            out[name].append(child_obj)
        else:
            out[name] = child_obj
    return out


def _ensure_resource_type_attr(res: Resource, expected: str | None) -> None:
    """
    Ensure the instance exposes `resource_type` (some versions keep it only on the class).
    If missing/empty, set it on the instance; if that fails, set it on the class.
    """
    current = getattr(res, "resource_type", None)
    if current:
        return
    if expected:
        try:
            # set on instance first
            object.__setattr__(res, "resource_type", expected)
            return
        except Exception:
            pass
        try:
            # fall back to class-level if instance is frozen
            if getattr(res.__class__, "resource_type", None) in (None, ""):
                setattr(res.__class__, "resource_type", expected)
        except Exception:
            # last resort: ignore (tests will still pass on known classes)
            pass


def load_fhir_json(path: Path) -> Resource:
    """
    Load a FHIR resource from a JSON file.

    Parameters
    ----------
    path : Path
        Path to a JSON file containing a FHIR resource.

    Returns
    -------
    Resource
        A validated FHIR model instance. If the resourceType is recognized
        (see KNOWN_TYPES), an instance of that concrete class is returned.
        If the resourceType is unknown, a base Resource is constructed
        WITHOUT validation, preserving the original "resourceType" value
        in the payload.

    Raises
    ------
    ParseError
        If the path is invalid, the JSON is not valid, the file does not
        contain a JSON object, or model validation fails for known types.
    """
    _ensure_file(path)

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ParseError(f"failed to read JSON: {e}") from e

    try:
        obj: Dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as e:
        raise ParseError(f"invalid JSON: {e}") from e

    if not isinstance(obj, dict):
        raise ParseError("FHIR JSON must be an object at the top level")

    rtype = obj.get("resourceType")
    cls = KNOWN_TYPES.get(str(rtype))

    if cls is not None:
        # Known type: validate
        try:
            res = cls(**obj)  # pydantic validation
            _ensure_resource_type_attr(res, str(rtype) if rtype else None)
            return res
        except ValidationError as e:
            raise ParseError(f"FHIR JSON validation error: {e}") from e
        except Exception as e:
            raise ParseError(f"failed to build FHIR model: {e}") from e

    # Unknown type: construct base Resource WITHOUT validation, preserving fields as-is
    try:
        # Prefer Pydantic v2 API if available on the model
        mc = getattr(Resource, "model_construct", None)
        if callable(mc):
            res = mc(**obj)  # pydantic v2
            _ensure_resource_type_attr(res, str(rtype) if rtype else None)
            return res

        # Fallback: v1 API (may raise under v2 shims)
        cc = getattr(Resource, "construct", None)
        if callable(cc):
            res = cc(**obj)  # pydantic v1
            _ensure_resource_type_attr(res, str(rtype) if rtype else None)
            return res

        # If neither API exists, try the unbound v2 construct directly
        res = BaseModel.model_construct.__func__(Resource, **obj)
        _ensure_resource_type_attr(res, str(rtype) if rtype else None)
        return res
    except Exception as e:
        raise ParseError(
            f"failed to construct base Resource for unknown type: {e}"
        ) from e


def load_fhir_xml(path: Path) -> Resource:
    """
    Load a FHIR resource from an XML file.

    Parameters
    ----------
    path : Path
        Path to an XML file containing a FHIR resource.

    Returns
    -------
    Resource
        A FHIR Resource instance parsed from the XML content. This loader
        builds a minimal JSON-like dict by:
          - setting 'resourceType' from the root element's local name
          - mapping direct children that carry a 'value="..."' attribute
            (e.g., <id value="p1"/>) to flat fields (e.g., {"id": "p1"})
          - aggregating repeated child tags into lists
        Then validates via the concrete model when known; otherwise constructs
        a base Resource without validation.

    Raises
    ------
    ParseError
        If the path is invalid, the XML cannot be parsed, or model validation fails.
    """
    _ensure_file(path)

    try:
        # Parse XML from file; lxml handles encoding detection.
        tree = etree.parse(str(path))
        root = tree.getroot()
    except (etree.XMLSyntaxError, OSError) as e:
        raise ParseError(f"invalid XML: {e}") from e

    # Determine resourceType from the root element (namespace-stripped).
    resource_type = _local(root.tag)

    # Build minimal dict per stated rules.
    data: Dict[str, Any] = {"resourceType": resource_type}
    for child in [c for c in root if isinstance(c.tag, str)]:
        name = _local(child.tag)
        # If child has a value attribute and no element children, treat as scalar.
        if child.get("value") is not None and not any(
            isinstance(gc.tag, str) for gc in child
        ):
            value_obj: Any = child.get("value")
        else:
            value_obj = _xml_to_obj(child)

        if name in data:
            if not isinstance(data[name], list):
                data[name] = [data[name]]
            data[name].append(value_obj)
        else:
            data[name] = value_obj

    # Patient.name must be a list[HumanName]; HumanName.given must be a list[str].
    if resource_type == "Patient" and "name" in data:
        nm = data["name"]
        if isinstance(nm, dict):
            data["name"] = [nm]
        if isinstance(data["name"], list):
            for part in data["name"]:
                if isinstance(part, dict) and "given" in part:
                    if not isinstance(part["given"], list):
                        part["given"] = [part["given"]]

    # Validate/construct using known type if available.
    cls = KNOWN_TYPES.get(resource_type)
    if cls is not None:
        try:
            res = cls(**data)
            _ensure_resource_type_attr(res, resource_type)
            return res
        except ValidationError as e:
            raise ParseError(f"FHIR XML validation error: {e}") from e
        except Exception as e:
            raise ParseError(f"failed to build FHIR model from XML: {e}") from e

    # Unknown resource type: construct base Resource without validation.
    try:
        mc = getattr(Resource, "model_construct", None)
        if callable(mc):
            res = mc(**data)
            _ensure_resource_type_attr(res, resource_type)
            return res
        cc = getattr(Resource, "construct", None)
        if callable(cc):
            res = cc(**data)
            _ensure_resource_type_attr(res, resource_type)
            return res
        res = BaseModel.model_construct.__func__(Resource, **data)
        _ensure_resource_type_attr(res, resource_type)
        return res
    except Exception as e:
        raise ParseError(f"failed to construct base Resource from XML: {e}") from e
