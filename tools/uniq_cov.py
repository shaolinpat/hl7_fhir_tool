# tools/uniq_cov.py
"""
uniq_cov.py — show per-test coverage info from coverage.py JSON with contexts,
and (with --owners) compute KEEP vs REDUNDANT tests by actually running tests
one-by-one under coverage.

Existing features kept:
  - Line-centric view (default) using coverage.json + contexts
  - Context-centric view (--contexts)

New:
  - --owners mode: NO config changes, NO pytest-cov needed. It will:
      * collect pytest nodeids
      * run each test in isolation under: coverage run -m pytest <nodeid>
      * read executed_lines for the given --source file
      * mark a test as REDUNDANT if its lines ⊆ union(lines of all other tests)

Usage examples:

# (A) Use your existing JSON-with-contexts workflow:
coverage erase
coverage run -m pytest -q -o addopts="" -p no:pytest_cov
coverage json -o coverage.json --show-contexts
python tools/uniq_cov.py src/hl7_fhir_tool/transform/v2_to_fhir/oru_r01.py
python tools/uniq_cov.py --contexts src/hl7_fhir_tool/transform/v2_to_fhir/oru_r01.py

# (B) Find owners / redundant tests — no context JSON required:
python tools/uniq_cov.py --owners \
  --source src/hl7_fhir_tool/transform/v2_to_fhir/oru_r01.py \
  --only-file tests/test_oru_r01.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from textwrap import fill

DEFAULT_JSON = "coverage.json"

# -------------------------------
# helpers
# -------------------------------


def _run(cmd: list[str]) -> tuple[bool, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return (p.returncode == 0), p.stdout, p.stderr


def ensure_cov_json(path: str, regen: bool = False) -> bool:
    """Ensure a coverage JSON exists with per-test contexts included."""
    if not regen and os.path.exists(path):
        return True
    ok, out, err = _run(["coverage", "json", "-o", path, "--show-contexts"])
    if ok:
        print(f"Wrote JSON report to {path}")
    else:
        sys.stderr.write(err or out)
    return ok


def load_cov(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read {path}: {e}")
        return None


def normalize_paths(files_dict: dict[str, dict]) -> dict[str, str]:
    """Map normalized path -> original key for lookups."""
    return {os.path.normpath(k): k for k in files_dict.keys()}


def _to_int(x) -> int | None:
    try:
        return int(x)
    except Exception:
        try:
            return int(str(x).strip())
        except Exception:
            return None


def detect_context_shape(meta: dict) -> str:
    """
    Return 'ctx_to_lines' if contexts look like {context: [lines...]},
           'line_to_ctx'  if contexts look like {line: [contexts...]},
           'none' otherwise.
    """
    ctx_block = meta.get("contexts")
    if not isinstance(ctx_block, dict) or not ctx_block:
        return "none"
    sample_key = next(iter(ctx_block.keys()))
    if _to_int(sample_key) is not None:
        return "line_to_ctx"
    return "ctx_to_lines"


# -------------------------------
# core analyzers (contexts-based)
# -------------------------------


def summarize_contexts_for_file(meta: dict) -> tuple[dict[int, set[str]], int, int]:
    """
    Build an inverted index: line -> set(contexts).
    Return (line_to_contexts, nonempty_count, total_refs).
    Works for both shapes.
    """
    line_to_ctx: dict[int, set[str]] = defaultdict(set)
    ctx_block = meta.get("contexts")
    if not isinstance(ctx_block, dict):
        return line_to_ctx, 0, 0

    shape = detect_context_shape(meta)
    nonempty = 0
    refs = 0

    if shape == "ctx_to_lines":
        for ctx, lines in ctx_block.items():
            if not lines:
                continue
            nonempty += 1
            for ln in lines:
                ln_int = _to_int(ln)
                if ln_int is None:
                    continue
                line_to_ctx[ln_int].add(ctx)
                refs += 1
    elif shape == "line_to_ctx":
        for ln, contexts in ctx_block.items():
            ln_int = _to_int(ln)
            if ln_int is None:
                continue
            if not contexts:
                continue
            nonempty += 1
            for ctx in contexts:
                ctx_str = str(ctx).strip()
                if not ctx_str:
                    continue
                line_to_ctx[ln_int].add(ctx_str)
                refs += 1
    return line_to_ctx, nonempty, refs


def analyze_unique_lines(
    line_to_ctx: dict[int, set[str]],
) -> tuple[dict[int, list[str]], int]:
    """Return (unique_lines_map, redundant_line_count)."""
    unique: dict[int, list[str]] = {}
    redundant = 0
    for ln, ctxs in line_to_ctx.items():
        if len(ctxs) == 1:
            unique[ln] = sorted(ctxs)
        elif len(ctxs) >= 2:
            redundant += 1
    return unique, redundant


# -------------------------------
# printers (contexts-based)
# -------------------------------


def print_line_centric(file_key: str, meta: dict, width: int, limit: int) -> None:
    ctx_block = meta.get("contexts")
    contexts_count = len(ctx_block or {})
    line_to_ctx, nonempty, refs = summarize_contexts_for_file(meta)
    print(f"\n=== {file_key} ===")
    print(f"[diag] contexts: {contexts_count}, nonempty: {nonempty}, line refs: {refs}")

    if not line_to_ctx:
        print(
            "No contextual line data found (per-line). File may be fully covered but without line ->test attributions."
        )
        return

    unique, redundant_count = analyze_unique_lines(line_to_ctx)
    all_lines = sorted(line_to_ctx.keys())
    print(
        f"Total lines with context: {len(all_lines)} (unique: {len(unique)}, redundant: {redundant_count})"
    )

    if unique:
        print("-- Unique lines (covered by exactly one test) --")
        lines_str = ", ".join(str(ln) for ln in sorted(unique.keys()))
        print(fill(lines_str, width=width))
        print("   who covers them:")
        shown = 0
        for ln in sorted(unique.keys()):
            ctx = unique[ln][0]
            print(f"{ln}:{ctx}")
            shown += 1
            if limit and shown >= limit:
                print(f"... (limited to {limit} items)")
                break
    else:
        print("No uniquely covered lines in this file.")


def print_context_centric(file_key: str, meta: dict, width: int, limit: int) -> None:
    print(f"\n=== {file_key} (context-centric) ===")
    ctx_block = meta.get("contexts")
    if not isinstance(ctx_block, dict) or not ctx_block:
        print("No contextual line data found (did you run with --show-contexts?).")
        return

    shape = detect_context_shape(meta)

    if shape == "ctx_to_lines":
        items = sorted(ctx_block.items(), key=lambda kv: len(kv[1] or []), reverse=True)
        shown = 0
        for ctx, lines in items:
            lines_int = [
                x for x in (_to_int(l) for l in (lines or [])) if x is not None
            ]
            print(f"\n{ctx} — {len(lines_int)} line(s)")
            print("-" * 59)
            if lines_int:
                print(fill(", ".join(str(x) for x in sorted(lines_int)), width=width))
            shown += 1
            if limit and shown >= limit:
                print(f"... (limited to {limit} contexts)")
                break
    else:
        context_to_lines: dict[str, list[int]] = defaultdict(list)
        for ln, contexts in ctx_block.items():
            ln_int = _to_int(ln)
            if ln_int is None or not contexts:
                continue
            for ctx in contexts:
                context_to_lines[str(ctx)].append(ln_int)

        items = sorted(
            context_to_lines.items(), key=lambda kv: len(kv[1]), reverse=True
        )
        shown = 0
        for ctx, lines in items:
            uniq_sorted = sorted(set(lines))
            print(f"\n{ctx} — {len(uniq_sorted)} line(s)")
            print("-" * 59)
            if uniq_sorted:
                print(fill(", ".join(str(x) for x in uniq_sorted), width=width))
            shown += 1
            if limit and shown >= limit:
                print(f"... (limited to {limit} contexts)")
                break


# -------------------------------
# OWNERS MODE (no contexts required)
# -------------------------------


def collect_nodes(only_file: str | None, pytest_args: str) -> list[str]:
    base = ["pytest", "--collect-only", "-q"]
    if only_file:
        base.append(only_file)
    if pytest_args:
        base.extend(pytest_args.split())
    ok, out, err = _run(base)
    if not ok:
        sys.stderr.write(err or out)
        sys.exit(1)
    return [ln.strip() for ln in out.splitlines() if ln and "::" in ln]


def executed_lines_for_source_from_json(json_path: str, source: str) -> set[int]:
    data = load_cov(json_path)
    if not data:
        return set()
    files = data.get("files", {})
    if not files:
        return set()
    norm_source = os.path.normpath(source)
    key = None
    for k in files.keys():
        if os.path.normpath(k) == norm_source:
            key = k
            break
    if key is None:
        # basename fallback
        base = os.path.basename(norm_source)
        cand = [k for k in files if os.path.basename(os.path.normpath(k)) == base]
        if len(cand) == 1:
            key = cand[0]
        else:
            return set()
    lines = set(files.get(key, {}).get("executed_lines", []) or [])
    return {int(x) for x in lines}


def run_test_and_get_lines(nodeid: str, source: str, pytest_args: str) -> set[int]:
    _run(["coverage", "erase"])
    cmd = ["coverage", "run", "-m", "pytest"]
    if pytest_args:
        cmd.extend(pytest_args.split())
    cmd.append(nodeid)
    ok, out, err = _run(cmd)
    if not ok:
        sys.stderr.write(f"[warn] test failed: {nodeid}\n")
        sys.stderr.write(err or out)
        return set()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tf:
        tmp = tf.name
    _run(
        ["coverage", "json", "-o", tmp]
    )  # executed_lines is enough; no contexts needed
    try:
        return executed_lines_for_source_from_json(tmp, source)
    finally:
        try:
            os.remove(tmp)
        except:
            pass


def choose_redundant(
    per_test_lines: dict[str, set[int]],
) -> tuple[list[str], list[str]]:
    nodes = list(per_test_lines.keys())
    keepers: list[str] = []
    redundant: list[str] = []
    for i, nid in enumerate(nodes):
        covered = per_test_lines[nid]
        if not covered:
            redundant.append(nid)
            continue
        union_other = set()
        for j, other in enumerate(nodes):
            if i == j:
                continue
            union_other |= per_test_lines[other]
        if covered.issubset(union_other):
            redundant.append(nid)
        else:
            keepers.append(nid)
    return keepers, redundant


def run_owners_mode(
    source: str, only_file: str | None, pytest_args: str, max_n: int
) -> None:
    nodes = collect_nodes(only_file, pytest_args)
    if max_n and len(nodes) > max_n:
        nodes = nodes[:max_n]

    print(f"[owners] analyzing {len(nodes)} tests against {source} ...")
    per: dict[str, set[int]] = {}
    for i, nid in enumerate(nodes, 1):
        print(f"[{i}/{len(nodes)}] {nid}")
        per[nid] = run_test_and_get_lines(nid, source, pytest_args)

    keepers, redundant = choose_redundant(per)
    total_lines = len(set().union(*per.values())) if per else 0

    print("\n=== OWNERS RESULTS ===")
    print(f"source lines hit (union): {total_lines}")
    print(f"tests analyzed:          {len(nodes)}")
    print(f"unique keepers:          {len(keepers)}")
    print(f"redundant candidates:    {len(redundant)}")

    if keepers:
        print("\n-- KEEP (adds unique lines) --")
        for k in keepers:
            print(k)

    if redundant:
        print("\n-- REDUNDANT (subset of others) --")
        for r in redundant:
            print(r)


# -------------------------------
# main
# -------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Coverage utilities: line/context reports and per-test owners."
    )
    ap.add_argument(
        "paths",
        nargs="*",
        help="Source file paths for context reports (ignored in --owners).",
    )
    ap.add_argument(
        "--cov-json",
        default=DEFAULT_JSON,
        help="coverage JSON path (default: coverage.json)",
    )
    ap.add_argument(
        "--regen",
        action="store_true",
        help="Regenerate coverage JSON with --show-contexts",
    )
    ap.add_argument("--width", type=int, default=100, help="Wrap width")
    ap.add_argument(
        "--limit", type=int, default=0, help="Limit items shown (0 = no limit)"
    )
    ap.add_argument("--contexts", action="store_true", help="Show context-centric view")

    # owners mode
    ap.add_argument(
        "--owners",
        action="store_true",
        help="Compute keep vs redundant tests by running each test",
    )
    ap.add_argument("--source", help="(owners) Source file to analyze for line hits")
    ap.add_argument(
        "--only-file", help="(owners) Restrict collection to this test file"
    )
    ap.add_argument(
        "--pytest-args",
        default="-q",
        help='(owners) Extra args for pytest, e.g. "-q -k oru"',
    )
    ap.add_argument(
        "--max", type=int, default=0, help="(owners) Max tests to analyze (0=all)"
    )
    args = ap.parse_args()

    if args.owners:
        if not args.source:
            print("ERROR: --owners requires --source <file.py>")
            sys.exit(1)
        run_owners_mode(args.source, args.only_file, args.pytest_args, args.max)
        return

    if not args.paths:
        print(
            "ERROR: provide one or more source file paths for reporting, or use --owners."
        )
        sys.exit(1)

    if not ensure_cov_json(args.cov_json, regen=args.regen):
        sys.exit(1)

    data = load_cov(args.cov_json)
    if not data:
        sys.exit(1)

    files = data.get("files", {})
    if not files:
        print("No 'files' entries found in coverage JSON.")
        sys.exit(1)

    norm_map = normalize_paths(files)

    print(f"Analyzing {len(args.paths)} file(s)...")
    for req in args.paths:
        norm_req = os.path.normpath(req)
        key = norm_map.get(norm_req)
        if not key:
            candidates = [
                k
                for k in files.keys()
                if os.path.normpath(k).endswith(
                    os.path.sep + os.path.basename(norm_req)
                )
            ]
            if len(candidates) == 1:
                key = candidates[0]
            elif len(candidates) > 1:
                print(
                    f"\nAmbiguous match for {req}. Candidates:\n  "
                    + "\n  ".join(candidates)
                )
                continue
            else:
                print(f"\nFile not found in coverage JSON: {req}")
                continue

        meta = files[key]
        if args.contexts:
            print_context_centric(key, meta, args.width, args.limit)
        else:
            print_line_centric(key, meta, args.width, args.limit)


if __name__ == "__main__":
    main()
