#!/bin/bash
# Scaffold one template port: generate the Node template, register it, verify the code
# survived byte-for-byte. The test is still written by hand — that is the part with
# judgement in it. Run tools/cdp_template_finish.sh once the test passes.
#
# Usage: tools/cdp_template_scaffold.sh <vendor_dir> [<node_slug>]
#   tools/cdp_template_scaffold.sh aws_kinesis
set -euo pipefail

VENDOR="$1"
SLUG="${2:-$VENDOR}"
# aws_kinesis -> awsKinesisTemplate, matching how index.ts names its imports.
ALIAS=$(echo "$SLUG" | .venv/bin/python -c "import sys; p=sys.stdin.read().strip().replace('-','_').split('_'); print(p[0]+''.join(w.capitalize() for w in p[1:])+'Template')")

PY_FILE=$(ls "posthog/cdp/templates/${VENDOR}"/template_*.py)
NODE_DIR="nodejs/src/cdp/templates/_destinations/${VENDOR}"

mkdir -p "$NODE_DIR"
.venv/bin/python tools/cdp_template_to_ts.py "$PY_FILE" | tail -n +2 > "${NODE_DIR}/${SLUG}.template.ts"

.venv/bin/python - "$VENDOR" "$SLUG" "$ALIAS" <<'PYEOF'
import re
import sys

vendor, slug, alias = sys.argv[1:4]
path = "nodejs/src/cdp/templates/index.ts"
src = open(path).read()

imp = f"import {{ template as {alias} }} from './_destinations/{vendor}/{slug}.template'"
if imp not in src:
    lines = src.split("\n")
    last = max(i for i, ln in enumerate(lines) if ln.startswith("import { template as") and "_destinations/" in ln)
    lines.insert(last + 1, imp)
    src = "\n".join(lines)

# Append to HOG_FUNCTION_TEMPLATES_DESTINATIONS, the list that ends just before the
# transformations list. Prettier re-sorts the imports afterwards.
if f"\n    {alias},\n" not in src:
    src = re.sub(
        r"(\n)(\]\n\nexport const HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS)", rf"\1    {alias},\n\2", src, count=1
    )
open(path, "w").write(src)
PYEOF

(cd nodejs && npx prettier --write src/cdp/templates/index.ts "src/cdp/templates/_destinations/${VENDOR}/" >/dev/null)
.venv/bin/python tools/cdp_template_verify.py "$PY_FILE" "${NODE_DIR}/${SLUG}.template.ts"

echo "registered ${ALIAS}; now write ${NODE_DIR}/${SLUG}.template.test.ts"
