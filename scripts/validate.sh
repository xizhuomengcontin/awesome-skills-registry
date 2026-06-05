#!/usr/bin/env bash
# Validate registry YAML files against schema.cue
# Usage: ./scripts/validate.sh [file.yaml ...] (no args = validate all)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA="$REPO_ROOT/schema.cue"

if ! command -v cue &>/dev/null; then
    echo "Error: cue is not installed."
    echo "Install with: brew install cue-lang/tap/cue"
    exit 1
fi

validate_file() {
    local file="$1"
    # Resolve relative paths against repo root
    [[ "$file" = /* ]] || file="$REPO_ROOT/$file"
    cat "$file" | cue vet "$SCHEMA" yaml: - -d "#Skill" 2>&1
}

if [ "$#" -gt 0 ]; then
    EXIT_CODE=0
    for file in "$@"; do
        if ! output=$(validate_file "$file"); then
            echo "FAIL $file"
            echo "$output"
            EXIT_CODE=1
        fi
    done
    exit $EXIT_CODE
else
    REGISTRY_DIR="$REPO_ROOT/registry"
    FAILED=0
    PASSED=0
    FAILED_FILES=()
    FAILED_ERRORS=()

    while IFS= read -r -d '' file; do
        if output=$(validate_file "$file") && [ -z "$output" ]; then
            PASSED=$((PASSED + 1))
        else
            FAILED=$((FAILED + 1))
            FAILED_FILES+=("$file")
            FAILED_ERRORS+=("$output")
        fi
    done < <(find "$REGISTRY_DIR" -name "*.yaml" -type f -print0 | sort -z)

    echo "Results: $PASSED passed, $FAILED failed"

    if [ "$FAILED" -gt 0 ]; then
        echo ""
        echo "Failed files:"
        for i in "${!FAILED_FILES[@]}"; do
            echo "  - ${FAILED_FILES[$i]}"
            if [ -n "${FAILED_ERRORS[$i]}" ]; then
                echo "${FAILED_ERRORS[$i]}" | sed 's/^/      /'
            fi
        done
        exit 1
    fi
fi
