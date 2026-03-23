# src/hl7_fhir_tool/cli.py
"""
Command-line interface for hl7_fhir_tool.

Subcommands
-----------
parse-hl7
    Pretty-print parsed HL7 v2 segments from a file (or stdin with "-").

parse-fhir
    Parse a FHIR resource from a JSON or XML file and print JSON to stdout.

transform
    Transform an HL7 v2 message into minimal FHIR resources and either:
        - list supported event codes (with --list), or
        - write resources to files (default), or
        - print resources to stdout (with --stdout).

to-fhir
    Transform an HL7 v2 message into a FHIR Bundle (JSON) and write to disk.
    This is stage 1 of the two-stage pipeline:
        HL7 v2 -> FHIR Bundle JSON -> RDF/Turtle

to-rdf
    Serialize to RDF/Turtle. Accepts either:
        - an HL7 v2 .hl7 file (single-stage: HL7 -> RDF), or
        - a FHIR Bundle .json file produced by to-fhir (stage 2 of pipeline).

Exit codes
----------
0  success
1  handled, expected error (HL7FHIRToolError or KeyboardInterrupt)
2  CLI usage error (argparse or validation failure)

Notes
-----
- This module does not change the signatures or behavior of your internal
  parsers or transformers. It validates inputs, structures output, and provides
  actionable errors.
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import json
import logging
import os
import sys

from collections.abc import Mapping, Iterable as _Iterable
from decimal import Decimal as _Decimal
from fhir.resources.condition import Condition
from fhir.resources.diagnosticreport import DiagnosticReport
from fhir.resources.encounter import Encounter
from fhir.resources.observation import Observation
from fhir.resources.patient import Patient
from fhir.resources.servicerequest import ServiceRequest
from hl7apy.core import Message
from hl7apy.parser import parse_message
from hl7apy.validation import VALIDATION_LEVEL
from pathlib import Path
from typing import Any, Iterable, List, Optional
from uuid import UUID as _UUID

from .config import load_config
from .exceptions import HL7FHIRToolError
from .fhir_parser import load_fhir_json, load_fhir_xml
from .hl7_parser import parse_hl7_v2, to_pretty_segments
from .logging_utils import configure_logging
from .rdf_serializer import serialize_resources
from .transform.registry import available_events, get_transformer


# ------------------------------------------------------------------------------
# globals
# ------------------------------------------------------------------------------

LOG = logging.getLogger("hl7_fhir_tool")

EXIT_OK = 0
EXIT_ERR = 1
EXIT_CLI = 2

# Dispatch table: FHIR resourceType string -> fhir.resources class.
# Used by _load_resources_from_bundle_json to reconstruct resource objects from
# a FHIR Bundle JSON file produced by the to-fhir subcommand.
_FHIR_RESOURCE_CLASSES: dict = {
    "Condition": Condition,
    "DiagnosticReport": DiagnosticReport,
    "Encounter": Encounter,
    "Observation": Observation,
    "Patient": Patient,
    "ServiceRequest": ServiceRequest,
}


# ------------------------------------------------------------------------------
# parser construction
# ------------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """
    Build and return the top-level argparse parser and subcommands.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser with subcommands: parse-hl7, parse-fhir, transform,
        to-fhir, to-rdf.

    Raises
    ------
    None
    """
    parser = argparse.ArgumentParser(
        prog="hl7-fhir",
        description="Parse HL7 v2 and FHIR, and transform v2 to FHIR resources.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to YAML config file (overrides defaults).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv, -vvv).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="hl7-fhir-tool (cli) 1.0.0",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("parse-hl7", help="Parse an HL7 v2 message file.")
    s1.add_argument(
        "path",
        type=Path,
        help='Path to HL7 v2 message file. Use "-" to read from stdin.',
    )
    s2 = sub.add_parser("parse-fhir", help="Parse a FHIR JSON or XML file.")
    s2.add_argument(
        "path",
        type=Path,
        help="Path to FHIR resource file (.json or .xml).",
    )
    s3 = sub.add_parser("transform", help="Transform HL7 v2 to FHIR resources.")
    s3.add_argument(
        "path",
        type=Path,
        help='Path to HL7 v2 message file. Use "-" to read from stdin.',
    )
    s3.add_argument(
        "--list",
        action="store_true",
        help="List supported HL7 v2 event codes and exit.",
    )
    s3.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write JSON resources (defaults to config.default_output_dir).",
    )
    s3.add_argument(
        "--stdout",
        action="store_true",
        help="Write transformed resources to stdout (NDJSON unless --pretty).",
    )
    s3.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (for stdout or files).",
    )
    s4 = sub.add_parser(
        "to-fhir",
        help=(
            "Transform HL7 v2 to a FHIR Bundle (JSON) and write to disk. "
            "Stage 1 of the HL7 -> FHIR Bundle -> RDF/Turtle pipeline."
        ),
    )
    s4.add_argument(
        "path",
        type=Path,
        help='Path to HL7 v2 message file. Use "-" for stdin.',
    )
    s4.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write .json Bundle output.",
    )
    s4.add_argument(
        "--stdout",
        action="store_true",
        help="Write Bundle JSON to stdout instead of to a file.",
    )
    s4.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    s5 = sub.add_parser(
        "to-rdf",
        help=(
            "Serialize to RDF/Turtle. Accepts an HL7 v2 .hl7 file (single-stage) "
            "or a FHIR Bundle .json file produced by to-fhir (stage 2 of pipeline)."
        ),
    )
    s5.add_argument(
        "path",
        type=Path,
        help=(
            "Path to an HL7 v2 .hl7 file or a FHIR Bundle .json file. "
            'Use "-" for stdin (HL7 only).'
        ),
    )
    s5.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write .ttl output.",
    )
    s5.add_argument(
        "--stdout",
        action="store_true",
        help="Write Turtle to stdout instead of to a file.",
    )

    return parser


# ------------------------------------------------------------------------------
# validation helpers
# ------------------------------------------------------------------------------


def _validate_existing_file(path: Path, allow_stdin: bool = False) -> None:
    """
    Validate that a path exists and is a file, or is "-" if allow_stdin is True.

    Parameters
    ----------
    path : Path
        Path provided by the user.
    allow_stdin : bool, default False
        If True, the special value "-" is accepted to indicate stdin.

    Returns
    -------
    None

    Raises
    ------
    HL7FHIRToolError
        If the path does not exist, is not a file, is not readable,
        or if "-" is used but allow_stdin is False.
    """
    if allow_stdin and str(path) == "-":
        return
    if not path.exists():
        raise HL7FHIRToolError(f"File not found: {path}")
    if not path.is_file():
        raise HL7FHIRToolError(f"Not a file: {path}")
    if not os.access(path, os.R_OK):
        raise HL7FHIRToolError(f"File is not readable: {path}")


def _validate_fhir_suffix(path: Path) -> str:
    """
    Validate FHIR file suffix and return normalized format string.

    Parameters
    ----------
    path : Path
        File path to validate.

    Returns
    -------
    str
        "json" or "xml" (normalized format).

    Raises
    ------
    HL7FHIRToolError
        If suffix is not .json or .xml.
    """
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".xml":
        return "xml"
    raise HL7FHIRToolError(
        f"Unsupported FHIR file type: {path.name} (expected .json or .xml)"
    )


def _validate_output_mode(output_dir: Optional[Path], to_stdout: bool) -> None:
    """
    Validate output mode selection for the transform command.

    Rules
    -----
    - If to_stdout is True, output_dir may still be provided but is ignored.
    - If to_stdout is False, ensure output_dir (or config default) is writable.

    Parameters
    ----------
    output_dir : Path or None
        Directory the user requested, or None to use config default.
    to_stdout : bool
        True to write resources to stdout instead of files.

    Returns
    -------
    None

    Raises
    ------
    HL7FHIRToolError
        If the selected output directory cannot be created or is not writable.
    """
    if to_stdout:
        return
    if output_dir is None:
        return  # will validate after resolving from config
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HL7FHIRToolError(f"Cannot create output directory: {output_dir} ({e})")
    if not os.access(output_dir, os.W_OK):
        raise HL7FHIRToolError(f"Output directory not writable: {output_dir}")


def _read_text_input(path: Path) -> str:
    """
    Read text either from a file or from stdin when path is "-".

    Parameters
    ----------
    path : Path
        Path to a file or "-" for stdin.

    Returns
    -------
    str
        The input text in UTF-8.

    Raises
    ------
    HL7FHIRToolError
        On missing files, permission errors, or OS read failures.
    """
    try:
        if str(path) == "-":
            return sys.stdin.read()
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HL7FHIRToolError(f"File not found: {path}")
    except PermissionError:
        raise HL7FHIRToolError(f"Permission denied: {path}")
    except OSError as e:
        raise HL7FHIRToolError(f"Failed to read {path}: {e}") from e


# ------------------------------------------------------------------------------
# json helpers
# ------------------------------------------------------------------------------


def _resource_to_json_str(resource: Any, pretty: bool) -> str:
    """
    Convert a FHIR resource object to a JSON string.

    Preference order
    ----------------
    1) Pydantic v2: model_dump_json(indent=...)
    2) Pydantic v2: model_dump() + json.dumps
    3) Pydantic v1: dict(by_alias=True) + json.dumps
    4) Generic: normalize to JSON-able structure (dates, decimals, UUIDs, bytes,
       sets, objects) + json.dumps

    Parameters
    ----------
    resource : Any
        FHIR resource (pydantic v2/v1), mapping, or arbitrary object tree.
    pretty : bool
        If True, indent JSON for readability; otherwise compact.

    Returns
    -------
    str
        Serialized JSON.

    Raises
    ------
    HL7FHIRToolError
        If the object cannot be serialized to JSON.
    """
    indent = 2 if pretty else None

    # --------------------------------------------------------------------------
    # pydantic v2 (preferred)
    # --------------------------------------------------------------------------
    try:
        mdj = getattr(resource, "model_dump_json", None)
        if callable(mdj):
            # Ensure str return type without mypy casts
            return str(mdj(indent=indent))
    except Exception:
        pass
    try:
        md = getattr(resource, "model_dump", None)
        if callable(md):
            return json.dumps(md(), indent=indent)
    except Exception:
        pass

    # --------------------------------------------------------------------------
    # pydantic v1 (avoid deprecated .json())
    # --------------------------------------------------------------------------
    try:
        dmethod = getattr(resource, "dict", None)
        if callable(dmethod):
            return json.dumps(dmethod(by_alias=True), indent=indent)
    except Exception:
        pass

    # --------------------------------------------------------------------------
    # generic fallback
    # --------------------------------------------------------------------------
    def _to_jsonable(obj: Any) -> Any:
        # primitives
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        # dates/times
        if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
            # ISO 8601; strip tzinfo micro-ambiguity by using .isoformat()
            return obj.isoformat()
        # decimals -> str (FHIR often treats quantities as strings in JSON)
        if isinstance(obj, _Decimal):
            return str(obj)
        # UUIDs -> str
        if isinstance(obj, _UUID):
            return str(obj)
        # bytes/bytearray -> base64 string
        if isinstance(obj, (bytes, bytearray)):
            try:
                return base64.b64encode(bytes(obj)).decode("ascii")
            except Exception:
                return (
                    obj.decode("utf-8", "ignore")
                    if isinstance(obj, bytes)
                    else str(obj)
                )
        # mappings
        if isinstance(obj, Mapping):
            return {str(k): _to_jsonable(v) for k, v in obj.items()}
        # sets/tuples/lists (but not strings/bytes)
        if isinstance(obj, _Iterable) and not isinstance(obj, (str, bytes, bytearray)):
            return [_to_jsonable(v) for v in obj]
        # object with __dict__ (drop private attrs)
        d = getattr(obj, "__dict__", None)
        if isinstance(d, dict):
            return {k: _to_jsonable(v) for k, v in d.items() if not k.startswith("_")}
        # last resort: string form
        return str(obj)

    try:
        return json.dumps(_to_jsonable(resource), indent=indent)
    except Exception as e:
        raise HL7FHIRToolError(f"Resource is not JSON serializable: {e}") from e


def _write_resources_to_dir(
    resources: Iterable[Any], out_dir: Path, pretty: bool
) -> None:
    """
    Write resources to JSON files in the given directory.

    Filenames include a 2-digit index and, when available, the resource type.

    Parameters
    ----------
    resources : Iterable
        Iterable of FHIR resource instances.
    out_dir : Path
        Destination directory. Will be created if needed.
    pretty : bool
        Pretty-print JSON output when True.

    Returns
    -------
    None

    Raises
    ------
    HL7FHIRToolError
        If any write fails.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, res in enumerate(resources, start=1):
        rtype = getattr(res, "resource_type", None) or getattr(
            res, "resourceType", None
        )
        stem = f"{i:02d}_{rtype}" if rtype else f"resource_{i}"
        out_path = out_dir / f"{stem}.json"
        try:
            out_path.write_text(_resource_to_json_str(res, pretty), encoding="utf-8")
        except OSError as e:
            raise HL7FHIRToolError(f"Failed to write {out_path}: {e}") from e
        LOG.info("Wrote %s", out_path)


def _write_resources_to_stdout(resources: Iterable[Any], pretty: bool) -> None:
    """
    Write resources to stdout.

    When pretty is False, emits compact NDJSON (one JSON object per line).
    When pretty is True, prints indented JSON separated by a blank line.

    Parameters
    ----------
    resources : Iterable
        Iterable of FHIR resource instances.
    pretty : bool
        If True, pretty-print JSON output.

    Returns
    -------
    None

    Raises
    ------
    None
    """
    first = True
    for res in resources:
        s = _resource_to_json_str(res, pretty)
        if pretty:
            if not first:
                sys.stdout.write("\n")
            sys.stdout.write(s)
            sys.stdout.write("\n")
        else:
            try:
                # Normalize to compact single line if possible
                sys.stdout.write(json.dumps(json.loads(s), separators=(",", ":")))
            except Exception:
                sys.stdout.write(s)
            sys.stdout.write("\n")
        first = False
    sys.stdout.flush()


# ------------------------------------------------------------------------------
# FHIR Bundle helpers
# ------------------------------------------------------------------------------


def _build_fhir_bundle_json(resources: List[Any], pretty: bool) -> str:
    """
    Wrap a list of FHIR resource objects into a FHIR Bundle (type: collection).

    The bundle is assembled as a plain dict and serialized to JSON using
    _resource_to_json_str for each entry resource. This avoids a dependency on
    fhir.resources.bundle, whose API varies across fhir.resources versions.

    Parameters
    ----------
    resources : list
        FHIR resource instances (pydantic models from fhir.resources).
    pretty : bool
        If True, indent the JSON output.

    Returns
    -------
    str
        FHIR Bundle JSON string with resourceType "Bundle" and type "collection".

    Raises
    ------
    HL7FHIRToolError
        If any resource cannot be serialized to JSON.
    """
    entries = []
    for res in resources:
        res_json_str = _resource_to_json_str(res, pretty=False)
        try:
            res_dict = json.loads(res_json_str)
        except json.JSONDecodeError as e:
            raise HL7FHIRToolError(
                f"Failed to parse resource JSON during Bundle assembly: {e}"
            ) from e
        entries.append({"resource": res_dict})

    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": entries,
    }
    return json.dumps(bundle, indent=2 if pretty else None)


def _load_resources_from_bundle_json(bundle_json_str: str) -> List[Any]:
    """
    Parse a FHIR Bundle JSON string and return a list of reconstructed resource objects.

    Each entry's resource dict is dispatched on resourceType and reconstructed
    using the corresponding fhir.resources class from _FHIR_RESOURCE_CLASSES.
    Unknown resource types are silently skipped, matching the behavior of
    serialize_resources.

    Parameters
    ----------
    bundle_json_str : str
        FHIR Bundle JSON string as produced by _build_fhir_bundle_json.

    Returns
    -------
    list
        Reconstructed fhir.resources instances in entry order.

    Raises
    ------
    HL7FHIRToolError
        If the JSON is malformed or the top-level resourceType is not "Bundle".
    """
    try:
        bundle_dict = json.loads(bundle_json_str)
    except json.JSONDecodeError as e:
        raise HL7FHIRToolError(f"Invalid JSON in FHIR Bundle file: {e}") from e

    if bundle_dict.get("resourceType") != "Bundle":
        raise HL7FHIRToolError(
            f"Expected resourceType 'Bundle', got '{bundle_dict.get('resourceType')}'"
        )

    resources = []
    for entry in bundle_dict.get("entry", []):
        res_dict = entry.get("resource", {})
        rtype = res_dict.get("resourceType")
        cls = _FHIR_RESOURCE_CLASSES.get(rtype)
        if cls is None:
            LOG.debug("Skipping unknown resourceType '%s' in Bundle entry", rtype)
            continue
        try:
            validate = getattr(cls, "model_validate", None) or getattr(
                cls, "parse_obj", None
            )
            if callable(validate):
                resources.append(validate(res_dict))
            else:
                resources.append(cls(**res_dict))
        except Exception as e:
            LOG.warning("Failed to reconstruct %s from Bundle entry: %s", rtype, e)
    return resources


# ------------------------------------------------------------------------------
# hl7 parse helper
# ------------------------------------------------------------------------------


def _parse_hl7_for_cli(content: str) -> Message:
    """
    Parse HL7 v2 text, falling back to tolerant validation when strict mode
    rejects the message.

    hl7apy strict validation rejects some valid message/segment combinations
    (e.g., DG1 in ADT^A08) with "Cannot instantiate an unknown Element with
    strict validation". Tolerant mode accepts these without data loss.

    The fallback also enables find_groups=True for ORM^O01 and ORU^R01, which
    require group inference to avoid "PID is not a valid child" errors.

    Parameters
    ----------
    content : str
        Raw HL7 v2 message text.

    Returns
    -------
    Message
        Parsed hl7apy Message object.

    Raises
    ------
    HL7FHIRToolError
        If both strict and tolerant parsing fail.
    """
    try:
        return parse_hl7_v2(content)
    except Exception as strict_exc:
        LOG.debug(
            "Strict parse failed (%s), retrying with tolerant validation",
            strict_exc,
        )

    # Normalize line endings for hl7apy
    if "\r" not in content and "\n" in content:
        content = content.replace("\n", "\r")

    find_groups = any(k in content for k in ("ORM^O01", "ORU^R01"))

    try:
        return parse_message(
            content,
            validation_level=VALIDATION_LEVEL.TOLERANT,
            find_groups=find_groups,
        )
    except Exception as tolerant_exc:
        # Re-raise with full context so the caller gets a useful traceback
        raise HL7FHIRToolError(
            f"Failed to parse HL7 v2 message: {tolerant_exc}"
        ) from tolerant_exc


# ------------------------------------------------------------------------------
# command handlers
# ------------------------------------------------------------------------------


def _cmd_parse_hl7(path: Path) -> int:
    """
    Parse-hl7: pretty-print HL7 v2 segments.

    Parameters
    ----------
    path : Path
        File path, or "-" for stdin.

    Returns
    -------
    int
        EXIT_OK on success.

    Raises
    ------
    HL7FHIRToolError
        If input is invalid or unreadable.
    """
    _validate_existing_file(path, allow_stdin=True)
    content = _read_text_input(path)
    msg = _parse_hl7_for_cli(content)
    for line in to_pretty_segments(msg):
        print(line)
    return EXIT_OK


def _cmd_parse_fhir(path: Path) -> int:
    """
    Parse-fhir: parse a FHIR resource file and print JSON.

    Parameters
    ----------
    path : Path
        Path to a .json or .xml file.

    Returns
    -------
    int
        EXIT_OK on success.

    Raises
    ------
    HL7FHIRToolError
        If file missing, unreadable, or unsupported suffix.
    """
    _validate_existing_file(path, allow_stdin=False)
    fmt = _validate_fhir_suffix(path)
    if fmt == "json":
        res = load_fhir_json(path)
    else:
        res = load_fhir_xml(path)
    print(_resource_to_json_str(res, pretty=True))
    return EXIT_OK


def _cmd_transform(
    path: Path,
    list_only: bool,
    output_dir: Optional[Path],
    to_stdout: bool,
    pretty: bool,
) -> int:
    """
    Transform: convert an HL7 v2 message into FHIR resources.

    Parameters
    ----------
    path : Path
        Path to HL7 v2 message file, or "-" for stdin.
    list_only : bool
        If True, list available HL7 v2 event codes and exit.
    output_dir : Path or None
        Directory to write JSON resources when not writing to stdout.
    to_stdout : bool
        If True, write resources to stdout; otherwise to files.
    pretty : bool
        If True, pretty-print JSON output (stdout or files).

    Returns
    -------
    int
        EXIT_OK on success.

    Raises
    ------
    HL7FHIRToolError
        For invalid input, missing transformer, or unwritable output.
    """
    if list_only:
        print("Registered HL7 v2 -> FHIR events:")
        for evt in sorted(available_events()):
            print(f"    {evt}")
        return EXIT_OK

    _validate_existing_file(path, allow_stdin=True)
    _validate_output_mode(output_dir, to_stdout)

    content = _read_text_input(path)
    msg = _parse_hl7_for_cli(content)

    xform = get_transformer(msg)
    if not xform:
        raise HL7FHIRToolError("No transformer registered for this HL7 message type.")

    cfg = load_config(None)
    out_dir = output_dir or cfg.default_output_dir
    if not to_stdout:
        # validate resolved default, too
        _validate_output_mode(out_dir, to_stdout=False)

    resources = list(xform.transform(msg))  # evaluate once
    if to_stdout:
        _write_resources_to_stdout(resources, pretty)
    else:
        _write_resources_to_dir(resources, out_dir, pretty)

    return EXIT_OK


def _cmd_to_fhir(
    path: Path,
    output_dir: Optional[Path],
    to_stdout: bool,
    pretty: bool,
) -> int:
    """
    To-fhir: transform an HL7 v2 message into a FHIR Bundle JSON file.

    This is stage 1 of the two-stage pipeline:
        HL7 v2 -> FHIR Bundle JSON (to-fhir)
        FHIR Bundle JSON -> RDF/Turtle (to-rdf)

    The output is a FHIR Bundle (type: collection) containing one entry per
    resource produced by the transformer. The Bundle file is written to
    out_dir/<stem>.json where stem is derived from the input filename.

    Parameters
    ----------
    path : Path
        Path to HL7 v2 message file, or "-" for stdin.
    output_dir : Path or None
        Directory to write the .json Bundle file when not writing to stdout.
    to_stdout : bool
        If True, write Bundle JSON to stdout.
    pretty : bool
        If True, pretty-print the JSON output.

    Returns
    -------
    int
        EXIT_OK on success.

    Raises
    ------
    HL7FHIRToolError
        For invalid input, missing transformer, or unwritable output.
    """
    _validate_existing_file(path, allow_stdin=True)
    _validate_output_mode(output_dir, to_stdout)

    content = _read_text_input(path)
    msg = _parse_hl7_for_cli(content)

    xform = get_transformer(msg)
    if not xform:
        raise HL7FHIRToolError("No transformer registered for this HL7 message type.")

    resources = list(xform.transform(msg))
    bundle_json = _build_fhir_bundle_json(resources, pretty=pretty)

    if to_stdout:
        sys.stdout.write(bundle_json)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return EXIT_OK

    cfg = load_config(None)
    out_dir = output_dir or cfg.default_output_dir
    _validate_output_mode(out_dir, to_stdout=False)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = path.stem if str(path) != "-" else "output"
    out_path = out_dir / f"{stem}.json"
    try:
        out_path.write_text(bundle_json, encoding="utf-8")
    except OSError as e:
        raise HL7FHIRToolError(f"Failed to write {out_path}: {e}") from e

    LOG.info("Wrote %s (%d resources)", out_path, len(resources))
    print(f"Wrote {out_path} ({len(resources)} resources)")
    return EXIT_OK


def _cmd_to_rdf(
    path: Path,
    output_dir: Optional[Path],
    to_stdout: bool,
) -> int:
    """
    To-rdf: serialize to RDF/Turtle.

    Accepts either:
    - An HL7 v2 .hl7 file (single-stage: HL7 -> RDF)
    - A FHIR Bundle .json file produced by to-fhir (stage 2 of pipeline)

    Input type is detected by file suffix. When the input is a .json file,
    resources are loaded from the Bundle via _load_resources_from_bundle_json
    and passed directly to serialize_resources, bypassing HL7 parsing. This
    makes the two-stage pipeline explicit and auditable:
        HL7 v2 -> FHIR Bundle JSON (to-fhir)
        FHIR Bundle JSON -> RDF/Turtle (to-rdf)

    Stdin is always treated as HL7.

    Parameters
    ----------
    path : Path
        Path to an HL7 v2 .hl7 file or a FHIR Bundle .json file, or "-" for
        stdin (HL7 only).
    output_dir : Path or None
        Directory to write the .ttl file when not writing to stdout.
    to_stdout : bool
        If True, write Turtle to stdout.

    Returns
    -------
    int
        EXIT_OK on success.

    Raises
    ------
    HL7FHIRToolError
        For invalid input or unwritable output.
    """
    _validate_existing_file(path, allow_stdin=True)
    _validate_output_mode(output_dir, to_stdout)

    # Detect input type by suffix. Stdin is always treated as HL7.
    is_fhir_bundle = str(path) != "-" and path.suffix.lower() == ".json"

    if is_fhir_bundle:
        # Stage 2: load from FHIR Bundle JSON produced by to-fhir
        bundle_json_str = _read_text_input(path)
        resources = _load_resources_from_bundle_json(bundle_json_str)
    else:
        # Single-stage or stdin: parse HL7 directly
        content = _read_text_input(path)
        msg = _parse_hl7_for_cli(content)
        xform = get_transformer(msg)
        if not xform:
            raise HL7FHIRToolError(
                "No transformer registered for this HL7 message type."
            )
        resources = list(xform.transform(msg))

    graph = serialize_resources(resources)
    turtle = graph.serialize(format="turtle")

    if to_stdout:
        sys.stdout.write(turtle)
        sys.stdout.flush()
        return EXIT_OK

    cfg = load_config(None)
    out_dir = output_dir or cfg.default_output_dir
    _validate_output_mode(out_dir, to_stdout=False)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Derive filename from the source file; fall back to "output"
    stem = path.stem if str(path) != "-" else "output"
    out_path = out_dir / f"{stem}.ttl"
    try:
        out_path.write_text(turtle, encoding="utf-8")
    except OSError as e:
        raise HL7FHIRToolError(f"Failed to write {out_path}: {e}") from e

    LOG.info("Wrote %s (%d triples)", out_path, len(graph))
    print(f"Wrote {out_path} ({len(graph)} triples)")
    return EXIT_OK


# ------------------------------------------------------------------------------
# main
# ------------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """
    CLI entrypoint.

    Parameters
    ----------
    argv : list[str] or None, default None
        Argument list for testing; None uses sys.argv[1:].

    Returns
    -------
    int
        Process exit code (EXIT_OK, EXIT_ERR, or EXIT_CLI).

    Raises
    ------
    None
        All expected errors are caught and mapped to exit codes.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.verbose)

    try:
        if args.cmd == "parse-hl7":
            return _cmd_parse_hl7(args.path)
        if args.cmd == "parse-fhir":
            return _cmd_parse_fhir(args.path)
        if args.cmd == "transform":
            return _cmd_transform(
                path=args.path,
                list_only=bool(args.list),
                output_dir=args.output_dir,
                to_stdout=bool(args.stdout),
                pretty=bool(args.pretty),
            )
        if args.cmd == "to-fhir":
            return _cmd_to_fhir(
                path=args.path,
                output_dir=args.output_dir,
                to_stdout=bool(args.stdout),
                pretty=bool(args.pretty),
            )
        if args.cmd == "to-rdf":
            return _cmd_to_rdf(
                path=args.path,
                output_dir=args.output_dir,
                to_stdout=bool(args.stdout),
            )

        parser.error("Unknown command")  # defensive, should not happen
        return EXIT_CLI

    except HL7FHIRToolError as e:
        LOG.error("%s", e, exc_info=True)
        return EXIT_ERR
    except KeyboardInterrupt:
        LOG.error("Interrupted")
        return EXIT_ERR


if __name__ == "__main__":
    raise SystemExit(main())
