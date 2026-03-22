#!/usr/bin/env bash
# tools/run_pipeline.sh
#
# Full end-to-end pipeline:
#   1. Generate synthetic HL7 v2.5.1 messages
#   2. Transform each message to RDF/Turtle via the to-rdf CLI
#   3. Clear the GraphDB repository
#   4. Load all Turtle files into GraphDB
#
# Usage:
#   bash tools/run_pipeline.sh [--count N] [--seed N] [--message-type TYPE] [--repo NAME]
#
# Defaults:
#   --count        100
#   --seed         22
#   --message-type mixed_registered
#   --repo         hl7_fhir
#
# Requirements:
#   - conda environment hl7_fhir_env active
#   - GraphDB running at localhost:7200
#   - curl available

set -euo pipefail

# ------------------------------------------------------------------------------
# defaults
# ------------------------------------------------------------------------------

COUNT=100
SEED=22
MESSAGE_TYPE=mixed_registered
REPO=hl7_fhir
GRAPHDB_BASE=http://localhost:7200

# ------------------------------------------------------------------------------
# argument parsing
# ------------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --count)        COUNT="$2";        shift 2 ;;
        --seed)         SEED="$2";         shift 2 ;;
        --message-type) MESSAGE_TYPE="$2"; shift 2 ;;
        --repo)         REPO="$2";         shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ------------------------------------------------------------------------------
# paths
# ------------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HL7_DIR="$ROOT/out/hl7"
RDF_DIR="$ROOT/out/rdf"
STATEMENTS_URL="$GRAPHDB_BASE/repositories/$REPO/statements"

# ------------------------------------------------------------------------------
# step 1: generate HL7 messages
# ------------------------------------------------------------------------------

echo "==> Step 1: generating $COUNT HL7 messages (type=$MESSAGE_TYPE, seed=$SEED)"
mkdir -p "$HL7_DIR"
python "$ROOT/scripts/generate_hl7_adt_a01_bulk.py" \
    --count "$COUNT" \
    --message-type "$MESSAGE_TYPE" \
    --out "$HL7_DIR" \
    --line-endings cr \
    --seed "$SEED"

# ------------------------------------------------------------------------------
# step 2: transform each .hl7 file to RDF/Turtle
# ------------------------------------------------------------------------------

echo ""
echo "==> Step 2: transforming HL7 -> RDF/Turtle"
mkdir -p "$RDF_DIR"

success=0
skipped=0
for hl7_file in "$HL7_DIR"/*.hl7; do
    result=$(python -m src.hl7_fhir_tool.cli to-rdf "$hl7_file" --output-dir "$RDF_DIR" 2>&1) || true
    if echo "$result" | grep -q "Wrote"; then
        success=$((success + 1))
    else
        skipped=$((skipped + 1))
    fi
done
echo "    Transformed: $success  Skipped/failed: $skipped"

ttl_count=$(ls "$RDF_DIR"/*.ttl 2>/dev/null | wc -l)
if [[ "$ttl_count" -eq 0 ]]; then
    echo "ERROR: no Turtle files produced in $RDF_DIR -- aborting."
    exit 1
fi

# ------------------------------------------------------------------------------
# step 3: clear the GraphDB repository
# ------------------------------------------------------------------------------

echo ""
echo "==> Step 3: clearing GraphDB repository '$REPO' at $GRAPHDB_BASE"
http_status=$(curl -s -o /dev/null -w "%{http_code}" \
    -X DELETE \
    "$STATEMENTS_URL")

if [[ "$http_status" != "204" ]]; then
    echo "ERROR: DELETE $STATEMENTS_URL returned HTTP $http_status"
    echo "       Is GraphDB running? Is repository '$REPO' correct?"
    exit 1
fi
echo "    Repository cleared (HTTP 204)"

# ------------------------------------------------------------------------------
# step 4: load Turtle files into GraphDB
# ------------------------------------------------------------------------------

echo ""
echo "==> Step 4: loading $ttl_count Turtle files into GraphDB"

loaded=0
failed=0
for ttl_file in "$RDF_DIR"/*.ttl; do
    http_status=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "Content-Type: application/x-turtle" \
        --data-binary "@$ttl_file" \
        "$STATEMENTS_URL")

    if [[ "$http_status" == "204" ]]; then
        loaded=$((loaded + 1))
    else
        echo "    WARN: failed to load $(basename "$ttl_file") (HTTP $http_status)"
        failed=$((failed + 1))
    fi
done

echo "    Loaded: $loaded  Failed: $failed"

# ------------------------------------------------------------------------------
# summary
# ------------------------------------------------------------------------------

echo ""
echo "==> Pipeline complete"
echo "    HL7 messages : $COUNT"
echo "    TTL files    : $ttl_count"
echo "    Loaded       : $loaded"
echo "    Repository   : $REPO @ $GRAPHDB_BASE"
echo ""
echo "Open GraphDB Workbench to explore:"
echo "    $GRAPHDB_BASE/sparql"