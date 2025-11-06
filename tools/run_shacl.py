# tools/run_shacl.py

"""
Professional SHACL validation runner with modular shapes support.

Examples
--------
    # Validate using top-level shapes file (which owl:imports modules/*)
    python tools/run_shacl.py --data tests/data/fhir_valid.ttl \
        --shapes src/hl7_fhir_tool/shacl/shapes.ttl

    # Directly pass multiple shapes files
    python tools/run_shacl.py --data tests/data/fhir_valid.ttl \
        --shapes src/hl7_fhir_tool/shacl/modules/20_core_shapes.ttl \
        src/hl7_fhir_tool/shacl/modules/30_profile_lab.ttl
"""
import argparse
import sys
from rdflib import Graph
from pyshacl import validate


def _load_graph(path, fmt=None):
    g = Graph()
    g.parse(path, format=fmt or "turtle")
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="Path to RDF data file")
    ap.add_argument(
        "--shapes",
        required=True,
        nargs="+",
        help="One or more SHACL shapes files (Turtle)",
    )
    ap.add_argument("--format", default="turtle", help="RDF format for data")
    ap.add_argument(
        "--inference",
        default="rdfs",
        choices=["none", "rdfs", "owlrl", "both"],
        help="Inference for validation",
    )
    ap.add_argument(
        "--report-out", default="", help="Optional TTL path for the SHACL report graph"
    )
    args = ap.parse_args()

    data_g = _load_graph(args.data, args.format)

    # Merge shapes into a single graph (supports owl:imports inside files too)
    shapes_g = Graph()
    for sh_path in args.shapes:
        sg = _load_graph(sh_path, "turtle")
        shapes_g += sg

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

    print(results_text)
    if args.report_out:
        results_graph.serialize(destination=args.report_out, format="turtle")
    sys.exit(0 if conforms else 1)


if __name__ == "__main__":
    main()
