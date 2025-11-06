#!/usr/bin/env python3
# tools/unique_owners.py
"""
Report “owner” tests (tests that uniquely cover at least one line)
vs “redundant” tests (touch the file but own nothing) for a target file
using coverage.py JSON with --show-contexts.

USAGE (run exactly in this order):
  coverage erase
  pytest --cov=src/hl7_fhir_tool --cov-branch --cov-report= --cov-context=test
  coverage json -o coverage.json --show-contexts
  python tools/unique_owners.py src/hl7_fhir_tool/transform/v2_to_fhir/oru_r01.py

Notes:
- Requires coverage.json to exist and include contexts (use --show-contexts).
- “Owners” are per-line unique; this does NOT compute unique branch owners.
- A test can still be valuable for behavior/branches even if it’s “redundant”
  by lines; review before deleting.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from textwrap import fill


def load_coverage(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"ERR: coverage JSON not found: {path}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERR: failed to read {path}: {e}", file=sys.stderr)
        sys.exit(2)


def normalize_target(target: str) -> str:
    # coverage JSON stores file keys as relative paths from project root.
    return target.replace("\\", "/")


def gather_contexts(file_meta: dict) -> dict:
    """
    Return a mapping: context_string -> set[int line_numbers]
    Filters out non-numeric entries that coverage can emit in some edge cases.
    """
    ctx_map = {}
    contexts = file_meta.get("contexts", {})
    for ctx, lines in contexts.items():
        out = set()
        for ln in lines:
            # Some coverage versions may leak non-numeric tokens; guard them.
            try:
                out.add(int(str(ln)))
            except Exception:
                # Ignore non-line tokens (e.g., accidental strings)
                continue
        if out:
            ctx_map[ctx] = out
    return ctx_map


def compute_unique_owners(ctx_map: dict) -> tuple[dict, dict, set]:
    """
    Build:
      - line_to_tests: line -> set(contexts)
      - test_to_lines: context -> set(lines)
      - unique_owners: set(contexts that uniquely own ≥1 line)
    """
    line_to_tests: dict[int, set] = defaultdict(set)
    test_to_lines: dict[str, set] = {}

    for ctx, lines in ctx_map.items():
        test_to_lines[ctx] = set(lines)
        for ln in lines:
            line_to_tests[ln].add(ctx)

    unique_owners = set()
    for ln, tests in line_to_tests.items():
        if len(tests) == 1:
            (only_ctx,) = tuple(tests)
            unique_owners.add(only_ctx)

    return line_to_tests, test_to_lines, unique_owners


def lines_by_owner(line_to_tests: dict) -> dict[str, list[int]]:
    """Inverse index: owner -> sorted list of unique lines they alone cover."""
    owners = defaultdict(list)
    for ln, tests in line_to_tests.items():
        if len(tests) == 1:
            (ctx,) = tuple(tests)
            owners[ctx].append(ln)
    for k in list(owners.keys()):
        owners[k].sort()
    return owners


def print_section(title: str):
    print("\n" + title)
    print("-" * len(title))


def main():
    ap = argparse.ArgumentParser(
        description="Identify unique test owners vs redundant tests for a given file."
    )
    ap.add_argument(
        "file",
        help="Target source file path as seen by coverage.json "
        "(e.g., src/hl7_fhir_tool/transform/v2_to_fhir/oru_r01.py)",
    )
    ap.add_argument(
        "--cov-json",
        default="coverage.json",
        help="Path to coverage.json (default: coverage.json)",
    )
    ap.add_argument(
        "--width",
        type=int,
        default=100,
        help="Wrap width for long lists (default: 100)",
    )
    args = ap.parse_args()

    cov = load_coverage(args.cov_json)
    files = cov.get("files", {})
    target = normalize_target(args.file)

    if target not in files:
        # help user find close matches
        print(f"ERR: '{target}' not found in coverage files.", file=sys.stderr)
        nearby = [
            k for k in files.keys() if os.path.basename(k) == os.path.basename(target)
        ]
        if nearby:
            print("Hint: did you mean one of:", file=sys.stderr)
            for k in nearby:
                print("  -", k, file=sys.stderr)
        sys.exit(2)

    meta = files[target]
    ctx_map = gather_contexts(meta)

    print(f"Analyzing file: {target}")
    print(
        f"[diag] contexts: {len(meta.get('contexts', {}))}, "
        f"usable: {len(ctx_map)}, "
        f"executed_lines: {len(meta.get('executed_lines', []))}, "
        f"executed_branches: {len(meta.get('executed_branches', []))}"
    )

    if not ctx_map:
        print(
            "No per-test context line data found. "
            "Re-run coverage JSON with '--show-contexts' on the 'coverage json' step.",
            file=sys.stderr,
        )
        sys.exit(1)

    line_to_tests, test_to_lines, unique_owners = compute_unique_owners(ctx_map)
    owners_to_lines = lines_by_owner(line_to_tests)

    # All tests that touched the file (by line)
    all_tests = set(test_to_lines.keys())

    # Redundant tests: touched the file but own zero unique lines
    redundant = sorted(all_tests - unique_owners)

    # Owners: tests that uniquely cover ≥1 line
    owners_sorted = sorted(unique_owners)

    # Summary
    print_section("SUMMARY")
    print(f"Total tests touching file: {len(all_tests)}")
    print(f"Owner tests (have ≥1 unique line): {len(owners_sorted)}")
    print(f"Redundant by lines (no unique lines): {len(redundant)}")

    # Owners with the lines they own
    print_section("OWNERS (keep these)")
    if not owners_sorted:
        print("None")
    else:
        for t in owners_sorted:
            lines = owners_to_lines.get(t, [])
            line_str = fill(", ".join(str(x) for x in lines), width=args.width)
            print(f"- {t}\n  owns: {line_str}")

    # Redundant tests (line-centric)
    print_section("REDUNDANT by lines (review/merge/drop)")
    if not redundant:
        print("None")
    else:
        print(fill(", ".join(redundant), width=args.width))

    # Optional: show a compact list of unique lines (useful sanity check)
    unique_lines = sorted([ln for ln, ts in line_to_tests.items() if len(ts) == 1])
    print_section("UNIQUE LINES (covered by exactly one test)")
    if not unique_lines:
        print("None")
    else:
        print(fill(", ".join(str(x) for x in unique_lines), width=args.width))

    # Gentle warning about branches
    if meta.get("executed_branches"):
        print_section("NOTE on branches")
        print(
            "This script is line-centric. If branch-uniqueness matters, "
            "consider keeping at least one E2E/smoke test and any tests "
            "explicitly written for branch edges."
        )


if __name__ == "__main__":
    main()
