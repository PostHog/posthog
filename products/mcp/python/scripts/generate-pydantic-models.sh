#!/usr/bin/env bash

set -e

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Input and output paths
INPUT_PATH="$PROJECT_ROOT/schema/tool-inputs.json"
OUTPUT_PATH="$PYTHON_ROOT/schema/tool_inputs.py"

# Ensure output directory exists
mkdir -p "$(dirname "$OUTPUT_PATH")"

# Check if input file exists
if [ ! -f "$INPUT_PATH" ]; then
    echo "❌ Error: JSON schema not found at $INPUT_PATH"
    echo "Please run 'pnpm run schema:build:json' first to generate the JSON schema"
    exit 1
fi

echo "🔧 Generating Pydantic models from $INPUT_PATH"

# Ensure uv environment is synced with dev dependencies
echo "🐍 Setting up uv environment..."
cd "$PYTHON_ROOT"
uv sync --dev

# Generate schema.py from schema.json
uv run datamodel-codegen \
    --class-name='ToolInputs' \
    --collapse-root-models \
    --target-python-version 3.11 \
    --disable-timestamp \
    --use-one-literal-as-default \
    --use-default \
    --use-default-kwarg \
    --use-subclass-enum \
    --input "$INPUT_PATH" \
    --input-file-type jsonschema \
    --output "$OUTPUT_PATH" \
    --output-model-type pydantic_v2.BaseModel \
    --custom-file-header "# mypy: disable-error-code=\"assignment\"" \
    --set-default-enum-member \
    --capitalise-enum-members \
    --wrap-string-literal \
    --use-field-description \
    --use-schema-description \
    --field-constraints \
    --use-annotated

echo "✅ Generated Pydantic models at $OUTPUT_PATH"

# Format with ruff
echo "📝 Formatting with ruff..."
uv run ruff format "$OUTPUT_PATH"

# Check and autofix with ruff
echo "🔍 Checking with ruff..."
uv run ruff check --fix "$OUTPUT_PATH"

# Replace class Foo(str, Enum) with class Foo(StrEnum) for proper handling in format strings in python 3.11
# Remove this when https://github.com/koxudaxi/datamodel-code-generator/issues/1313 is resolved
echo "🔄 Updating enum imports for Python 3.11+..."
if sed --version 2>&1 | grep -q GNU; then
    # GNU sed
    sed -i -e 's/str, Enum/StrEnum/g' "$OUTPUT_PATH"
    sed -i 's/from enum import Enum/from enum import Enum, StrEnum/g' "$OUTPUT_PATH"
else
    # BSD/macOS sed
    sed -i '' -e 's/str, Enum/StrEnum/g' "$OUTPUT_PATH"
    sed -i '' 's/from enum import Enum/from enum import Enum, StrEnum/g' "$OUTPUT_PATH"
fi

echo "🎉 Successfully generated Pydantic models!"
echo "📋 Output file: $OUTPUT_PATH"
