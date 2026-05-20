"""Print a DFS-indented tree of spans, reconstructed from parent_span_id.

Usage:
  python3 scripts/print_timeline.py FILE

Env vars:
  MAX_LEN  — truncation limit for span names (default 120, 0 = unlimited)
"""

import os
import sys

from _common import SPAN_KIND, fmt_duration, is_root, load_trace_file, truncate


max_len = int(os.environ.get("MAX_LEN", "120"))

spans = load_trace_file(sys.argv[1])
if not spans:
    print("No spans in payload.", file=sys.stderr)
    sys.exit(1)

# Build span_id -> span and parent_span_id -> [children] indexes.
# Sort children by timestamp so DFS prints chronologically within each branch.
by_id = {}
children = {}
for span in spans:
    sid = span.get("span_id")
    if sid:
        by_id[sid] = span
    pid = span.get("parent_span_id") or ""
    children.setdefault(pid, []).append(span)

for kids in children.values():
    kids.sort(key=lambda s: s.get("timestamp", ""))

roots = [s for s in spans if is_root(s)]
roots.sort(key=lambda s: s.get("timestamp", ""))

trace_id = spans[0].get("trace_id", "?")
print("=" * 80)
print(f"TIMELINE — trace {trace_id}  ({len(spans)} spans, {len(roots)} root(s))")
print("=" * 80)


def render(span, depth):
    indent = "  " * depth
    name = truncate(span.get("name", "?"), max_len)
    err = " [ERR]" if span.get("status_code") == 2 else ""
    kind = SPAN_KIND.get(span.get("kind"), span.get("kind"))
    print(f"{indent}- [{span.get('service_name', '?')}] {name}  ({fmt_duration(span.get('duration_nano'))}) <{kind}>{err}")
    print(f"{indent}  span_id={span.get('span_id', '?')}")
    sid = span.get("span_id")
    for kid in children.get(sid, []):
        render(kid, depth + 1)


for root in roots:
    render(root, 0)

# Render orphan subtrees (their parent isn't in the payload, but the span itself is).
orphan_roots = []
for span in spans:
    if is_root(span):
        continue
    pid = span.get("parent_span_id") or ""
    if pid not in by_id:
        orphan_roots.append(span)

if orphan_roots:
    print()
    print(f"--- ORPHAN SUBTREES ({len(orphan_roots)} — parent_span_id not in payload) ---")
    orphan_roots.sort(key=lambda s: s.get("timestamp", ""))
    for span in orphan_roots:
        render(span, 0)
