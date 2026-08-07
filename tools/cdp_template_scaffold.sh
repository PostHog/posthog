#!/bin/bash
# Scaffold one template port: generate the Node template, register it, drop the Python side.
# The test still gets written by hand — that is the part with judgement in it.
#
# Usage: tools/cdp_template_scaffold.sh <vendor_dir> <node_slug> [<import_alias>]
#   tools/cdp_template_scaffold.sh activecampaign activecampaign activecampaignTemplate
set -euo pipefail

VENDOR="$1"
SLUG="$2"
ALIAS="${3:-${SLUG}Template}"

PY_DIR="posthog/cdp/templates/${VENDOR}"
PY_FILE=$(ls "${PY_DIR}"/template_*.py)
NODE_DIR="nodejs/src/cdp/templates/_destinations/${VENDOR}"

mkdir -p "$NODE_DIR"
.venv/bin/python tools/cdp_template_to_ts.py "$PY_FILE" | tail -n +2 > "${NODE_DIR}/${SLUG}.template.ts"

.venv/bin/python - "$VENDOR" "$SLUG" "$ALIAS" <<'PYEOF'
import re
import sys

vendor, slug, alias = sys.argv[1:4]
path = "nodejs/src/cdp/templates/index.ts"
src = open(path).read()

imp = f"import {{ template as {alias} }} from './_destinations/{vendor}/{slug}.template'\n"
if imp not in src:
    lines = src.split("\n")
    last = max(i for i, ln in enumerate(lines) if ln.startswith("import { template as") and "_destinations/" in ln)
    lines.insert(last + 1, imp.rstrip("\n"))
    src = "\n".join(lines)

src = re.sub(r"(\n)(\]\n\nexport const HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS)", rf"\1    {alias},\n\2", src, count=1)
open(path, "w").write(src)
PYEOF

echo "generated ${NODE_DIR}/${SLUG}.template.ts and registered ${ALIAS}"
echo "python template still at ${PY_FILE} — delete it once the test is written"
