#!/bin/bash
# tools/run_sparql_checks.sh
# Run all SPARQL queries in a fixed order: schema_checks -> data_quality -> cohorts.

set -euo pipefail

ARQ=${ARQ:-arq}
TTL="rdf/ontology/hl7_fhir_tool_schema.ttl"
DATA="--data rdf/instances/cohort_diabetes_e11_9_hb1ac_over_8.ttl"

run_group() {
    local title="$1"
    local dir="$2"

    echo "== $title =="
    if [ -d "$dir" ] && compgen -G "$dir/*.rq" > /dev/null; then
        while IFS= read -r -d '' q; do
            echo ">>> $q"
            $ARQ --data "$TTL" $DATA --query "$q"
            echo
        done < <(find "$dir" -type f -name '*.rq' -print0 | sort -z)
    else
        echo "(no .rq files in $dir)"
        echo
    fi
}

echo "Ontology : $TTL"
echo "Instances: rdf/instances/demo.ttl"
echo

run_group "Schema_checks (empty = PASS)" "rdf/queries/schema_checks"
run_group "Data quality checks (rows = problems)" "rdf/queries/data_quality"
run_group "Cohorts (expect rows)" "rdf/queries/cohorts"

echo "== DONE =="