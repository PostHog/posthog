#!/bin/bash
# Finish one template port: drop the Python side, lint both, re-verify the code against
# the copy still in git, and run the new Node tests. Leaves everything staged.
#
# Usage: tools/cdp_template_finish.sh <vendor_dir> <python_symbol> [<python_symbol> ...]
#   tools/cdp_template_finish.sh brevo brevo
#   tools/cdp_template_finish.sh klaviyo klaviyo_event klaviyo_user
set -euo pipefail

VENDOR="$1"
shift
SYMBOLS=("$@")

PY_FILE=$(ls "posthog/cdp/templates/${VENDOR}"/template_*.py)
NODE_DIR="nodejs/src/cdp/templates/_destinations/${VENDOR}"

# Verify against the copy still in git, since the working tree one is about to go.
.venv/bin/python tools/cdp_template_verify.py --git HEAD "$PY_FILE" "${NODE_DIR}"/*.template.ts

git rm -r --quiet "posthog/cdp/templates/${VENDOR}/"
for sym in "${SYMBOLS[@]}"; do
    .venv/bin/python - "$sym" <<'PYEOF'
import re
import sys

sym = sys.argv[1]
path = "posthog/cdp/templates/__init__.py"
src = open(path).read()
src = re.sub(rf"^from \.[\w.]+ import (?:template|template_\w+) as {sym}\n", "", src, flags=re.M)
src = re.sub(rf"^    {sym},\n", "", src, flags=re.M)
open(path, "w").write(src)
PYEOF
done

.venv/bin/ruff check posthog/cdp/templates/__init__.py
(cd nodejs && npx prettier --write "src/cdp/templates/_destinations/${VENDOR}/" src/cdp/templates/index.ts >/dev/null)
(cd nodejs && npx eslint "src/cdp/templates/_destinations/${VENDOR}/" src/cdp/templates/index.ts)

export PATH="$PWD/.venv/bin:$PATH"
export SECRET_KEY="${SECRET_KEY:-0123456789abcdef0123456789abcdef0123456789abcdef}"
export DEBUG=1
(cd nodejs && npx jest "src/cdp/templates/_destinations/${VENDOR}")

git add -A "$NODE_DIR" nodejs/src/cdp/templates/index.ts posthog/cdp/templates
git status --short | grep -v '^??' || true
