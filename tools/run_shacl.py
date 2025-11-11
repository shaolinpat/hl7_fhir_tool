#!/usr/bin/env python3

# tools/run_shacl.py

"""
Professional SHACL validation runner with modular shapes support.

Examples
--------

Validate a single data file
---------------------------
    python tools/run_shacl.py \
        --data \
            tests/data/fhir_valid.ttl \
        --shapes \
            src/hl7_fhir_tool/shacl/modules/*.ttl \
            rdf/shapes/data_checks/*.ttl \
            rdf/shapes/schema_checks/*.ttl

Validate multiple data files (each is run independently)
--------------------------------------------------------
    python tools/run_shacl.py \
        --data \
            tests/data/fhir_valid.ttl \
            tests/data/fhir_bad_closed.ttl \
            tests/data/fhir_bad_values.ttl \
        --shapes \
            src/hl7_fhir_tool/shacl/modules/*.ttl \
            rdf/shapes/data_checks/*.ttl \
            rdf/shapes/schema_checks/*.ttl

Mark some files as expected to violate
--------------------------------------
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

Notes
-----
- Use --details {none,fail,all} to control when full pySHACL reports are printed.
"""

import argparse
import sys

from pathlib import Path
from pyshacl import validate
from rdflib import Graph
from typing import Dict, List, Sequence


# ------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------


def _ensure_paths_exist(paths: Sequence[str], label: str) -> List[Path]:
    """
    Validate that all given filesystem paths exist.

    Parameters
    ----------
    paths : Sequence[str]
        File paths to verify (after shell glob expansion by the shell).
    label : str
        Human-friendly label for the set (e.g., "data", "shapes").

    Returns
    -------
    List[pathlib.Path]
        Paths converted to `Path` and verified to exist.

    Raises
    ------
    SystemExit
        If any path does not exist or if the sequence is empty.
    """
    if not paths:
        print(f"[ERROR] No {label} paths were provided.", file=sys.stderr)
        raise SystemExit(2)

    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        print(f"[ERROR] The following {label} path(s) do not exist:", file=sys.stderr)
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(2)

    return [Path(p) for p in paths]


def _load_graph(path: str | Path, fmt: str | None = None) -> Graph:
    """
    Load an RDF graph from a file path.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to an RDF file.
    fmt : str or None, optional
        RDF format hint for rdflib (e.g., "turtle"). If None, defaults to "turtle".

    Returns
    -------
    rdflib.Graph
        Parsed graph.

    Raises
    ------
    SystemExit
        If parsing fails.
    """
    g = Graph()
    try:
        g.parse(str(path), format=fmt or "turtle")
    except Exception as exc:
        print(f"[ERROR] Failed to parse RDF file: {path}", file=sys.stderr)
        print(f"        Reason: {exc}", file=sys.stderr)
        raise SystemExit(2)
    return g


def _count_results(results_graph: Graph) -> int:
    """
    Count SHACL ValidationResult instances in a results graph.

    Parameters
    ----------
    results_graph : rdflib.Graph
        The SHACL results graph returned by pySHACL.

    Returns
    -------
    int
        Number of `sh:ValidationResult` instances.
    """
    if not results_graph:
        return 0
    q = """
    SELECT (COUNT(?r) AS ?count)
    WHERE {
        ?r a <http://www.w3.org/ns/shacl#ValidationResult>
    }
    """
    res = list(results_graph.query(q))
    return int(res[0][0]) if res else 0


def _severity_tally(results_graph: Graph) -> Dict[str, int]:
    """
    Tally SHACL severities (Info/Warning/Violation) in a results graph.

    Parameters
    ----------
    results_graph : rdflib.Graph
        The SHACL results graph returned by pySHACL.

    Returns
    -------
    dict[str, int]
        Mapping of severity local names to counts, e.g., {'Warning': 2, 'Violation': 1}.
    """
    if not results_graph:
        return {}
    q = """
    SELECT ?severity (COUNT(?r) AS ?count)
    WHERE {
        ?r a <http://www.w3.org/ns/shacl#ValidationResult> ;
           <http://www.w3.org/ns/shacl#resultSeverity> ?severity .
    }
    GROUP BY ?severity
    """
    tallies: Dict[str, int] = {}
    for sev, c in results_graph.query(q):
        key = str(sev).split("#")[-1]
        tallies[key] = int(getattr(c, "toPython", lambda: c)())
    return tallies


def _serialize_report(
    results_graph: Graph, base_out: Path, index: int, total: int
) -> Path:
    """
    Serialize the SHACL results graph to Turtle with sensible filename logic.

    Parameters
    ----------
    results_graph : rdflib.Graph
        The SHACL results graph.
    base_out : pathlib.Path
        The requested output path (may be a filename or directory path).
    index : int
        1-based index of the current data file in the suite.
    total : int
        Total number of data files in the suite.

    Returns
    -------
    pathlib.Path
        The actual path written to.
    """
    # If base_out is a directory, place reports inside it.
    if base_out.exists() and base_out.is_dir():
        out_path = base_out / (
            f"shacl_report_{index}.ttl" if total > 1 else "shacl_report.ttl"
        )
    else:
        # If a single file, suffix for multiple inputs; preserve extension if present.
        out_path = (
            base_out
            if total == 1
            else base_out.with_name(
                f"{base_out.stem}_{index}{base_out.suffix or '.ttl'}"
            )
        )

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        results_graph.serialize(destination=str(out_path), format="turtle")
    except Exception as exc:
        print(f"[ERROR] Failed to write report to: {out_path}", file=sys.stderr)
        print(f"        Reason: {exc}", file=sys.stderr)
        raise SystemExit(2)

    return out_path


# ------------------------------------------------------------------------------
# main
# ------------------------------------------------------------------------------


def main() -> None:
    """
    Entry point for the SHACL validation runner.

    Parses CLI arguments, validates inputs, loads shapes once, and validates
    one or more data files independently. Produces a concise per-file status
    line and an overall suite footer. Detailed pySHACL report blocks are
    optionally printed based on --details.

    Exit code 0 when all expectations are met:
        - files NOT listed in --expected-fail must CONFORM
        - files listed in --expected-fail must have at least one VIOLATION
    """
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--data",
        required=True,
        nargs="+",
        help="One or more RDF data files (each validated independently).",
    )
    ap.add_argument(
        "--shapes",
        required=True,
        nargs="+",
        help="One or more SHACL shapes files (Turtle).",
    )
    ap.add_argument(
        "--expected-fail",
        nargs="*",
        default=[],
        help="File paths expected to VIOLATE (shell globs expanded by your shell).",
    )
    ap.add_argument("--format", default="turtle", help="RDF format for data.")
    ap.add_argument(
        "--inference",
        default="rdfs",
        choices=["none", "rdfs", "owlrl", "both"],
        help="Inference for validation.",
    )
    ap.add_argument(
        "--report-out",
        default="",
        help="Optional path or directory for SHACL report graph(s).",
    )
    ap.add_argument(
        "--details",
        choices=["none", "fail", "all"],
        default="none",
        help="When to print detailed pySHACL report blocks.",
    )
    args = ap.parse_args()

    data_paths = _ensure_paths_exist(args.data, "data")
    shape_paths = _ensure_paths_exist(args.shapes, "shapes")
    # expected-fail is optional; if provided, enforce existence
    xfail_list = (
        _ensure_paths_exist(args.expected_fail, "expected-fail")
        if args.expected_fail
        else []
    )
    xfail_set = {p.resolve() for p in xfail_list}

    # Merge shapes into a single graph (supports owl:imports too)
    shapes_g = Graph()
    for sh_path in shape_paths:
        sg = _load_graph(sh_path, "turtle")
        shapes_g += sg

    print("\n--- SHACL Validation Suite --------------------------------------------")
    print(f"Inference     : {args.inference}")
    print(f"Shapes Loaded : {len(shape_paths)}")
    if xfail_set:
        print(f"Expected-Fail : {len(xfail_set)}")
    print("-----------------------------------------------------------------------")

    suite_total = 0
    suite_bad = 0
    suite_warn_sum = 0

    report_base: Path | None = Path(args.report_out) if args.report_out else None

    for idx, data_path in enumerate(data_paths, start=1):
        suite_total += 1
        data_g = _load_graph(data_path, args.format)

        ontology_path = Path("rdf/ontology/hl7_fhir_tool_schema.ttl")
        if ontology_path.exists():
            try:
                data_g.parse(str(ontology_path), format="turtle")
            except Exception as exc:
                print(
                    f"[WARN] Could not parse ontology {ontology_path} ({exc})",
                    file=sys.stderr,
                )

        conforms, results_graph, results_text = validate(
            data_graph=data_g,
            shacl_graph=shapes_g,
            inference=args.inference,
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
            advanced=True,
            js=False,
            inplace=False,
            debug=False,
        )

        tallies = _severity_tally(results_graph)
        warns = tallies.get("Warning", 0)
        viols = tallies.get("Violation", 0)
        suite_warn_sum += warns

        # Expectation logic
        is_expected_violate = data_path.resolve() in xfail_set
        if is_expected_violate:
            ok = viols > 0  # must have violations
            status = "PASS (expected violations)" if ok else "FAIL (unexpected pass)"
        else:
            ok = bool(conforms)  # must conform
            status = "PASS" if ok else "FAIL"

        if not ok:
            suite_bad += 1

        print(f"[{idx:>3}/{len(data_paths)}] {status}  {data_path.as_posix()}")
        if warns or viols:
            parts: List[str] = []
            if warns:
                parts.append(f"Warnings={warns}")
            if viols:
                parts.append(f"Violations={viols}")
            print(f"      Details : " + ", ".join(parts))

        if report_base:
            out_path = _serialize_report(
                results_graph, report_base, idx, len(data_paths)
            )
            print(f"      Report  : {out_path.as_posix()}")

        # Decide whether to print detailed report text for this file
        print_details = args.details == "all" or (args.details == "fail" and not ok)
        if print_details:
            # Normalize the detailed block to avoid duplicate headers in README.
            print("      ----- Validation Report (pySHACL) -----")
            if results_text:
                # results_text already includes "Validation Report" and "Conforms: ..."
                # but we keep it for forensic completeness.
                print(results_text)
            else:
                print("      (no validation results text emitted by pySHACL)\n")
            count_value = _count_results(results_graph)
            print("      ---------------------------------------")
            print(f"      Total Results : {count_value}")
            print(f"      Data File     : {data_path.as_posix()}")
            print(f"      Inference     : {args.inference}")
            print("")

    # Suite footer
    print("-----------------------------------------------------------------------")
    print(f"Files Checked : {suite_total}")
    print(f"Failures      : {suite_bad}")
    print(f"Warnings (sum): {suite_warn_sum}")
    print(
        "Result        : "
        + ("ALL EXPECTATIONS MET\n" if suite_bad == 0 else "EXPECTATIONS NOT MET\n")
    )

    # Exit code mirrors expectation status
    raise SystemExit(0 if suite_bad == 0 else 1)


if __name__ == "__main__":
    main()
