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
from hl7apy.core import Message
from hl7apy.parser import parse_message
from hl7apy.validation import VALIDATION_LEVEL
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import UUID as _UUID

from .config import load_config
from .exceptions import HL7FHIRToolError
from .fhir_parser import load_fhir_json, load_fhir_xml
from .hl7_parser import parse_hl7_v2, to_pretty_segments
from .logging_utils import configure_logging
from .transform.registry import available_events, get_transformer

# import hl7_fhir_tool.transform

# ------------------------------------------------------------------------------
# globals
# ------------------------------------------------------------------------------

LOG = logging.getLogger("hl7_fhir_tool")

EXIT_OK = 0
EXIT_ERR = 1
EXIT_CLI = 2

# ------------------------------------------------------------------------------
# Parser construction
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
        Configured parser with subcommands: parse-hl7, parse-fhir, transform.

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

    # parse-hl7
    s1 = sub.add_parser("parse-hl7", help="Parse an HL7 v2 message file.")
    s1.add_argument(
        "path",
        type=Path,
        help='Path to HL7 v2 message file. Use "-" to read from stdin.',
    )

    # parse-fhir
    s2 = sub.add_parser("parse-fhir", help="Parse a FHIR JSON or XML file.")
    s2.add_argument(
        "path",
        type=Path,
        help="Path to FHIR resource file (.json or .xml).",
    )

    # transform
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

    return parser


# ------------------------------------------------------------------------------
# Validation helpers
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
# JSON helpers
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

    # ---- Pydantic v2 (preferred) ---------------------------------------------
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

    # ---- Pydantic v1 (avoid deprecated .json()) ------------------------------
    try:
        dmethod = getattr(resource, "dict", None)
        if callable(dmethod):
            return json.dumps(dmethod(by_alias=True), indent=indent)
    except Exception:
        pass

    # ---- Generic fallback ----------------------------------------------------
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
# HL7 parse helper
# ------------------------------------------------------------------------------


def _parse_hl7_for_cli(content: str) -> Message:
    """
    Parse HL7 v2 text with project default, and fall back to hl7apy group
    inference for messages that otherwise fail with "PID is not a valid child
    for <Message ...>".

    This currently ony happens with ORM^O01 messages but there may be others.
    """
    try:
        return parse_hl7_v2(content)
    except Exception:
        # if "ORM^O01" not in content:
        if not any(k in content for k in ("ORM^O01", "ORU^R01")):
            raise

        # Try hl7apy with find_groups=True
        if "\r" not in content and "\n" in content:
            content = content.replace("\n", "\r")

        msg = parse_message(
            content,
            validation_level=VALIDATION_LEVEL.STRICT,
            find_groups=True,
        )
        return msg


# ------------------------------------------------------------------------------
# Command handlers
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
        print("Registered HL7 v2 → FHIR events:")
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


# ------------------------------------------------------------------------------
# Entrypoint
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
        parser.error("Unknown command")  # defensive, should not happen
        return EXIT_CLI

    except HL7FHIRToolError as e:
        LOG.error("%s", e)
        return EXIT_ERR
    except KeyboardInterrupt:
        LOG.error("Interrupted")
        return EXIT_ERR


if __name__ == "__main__":
    raise SystemExit(main())
