"""Print a DFS-indented tree of spans, reconstructed from parent_span_id.

Usage:
  python3 scripts/print_timeline.py FILE

Env vars:
  MAX_LEN  — truncation limit for span names (default 120, 0 = unlimited)
"""

import json
import os
import sys


SPAN_KIND = {0: "Unspecified", 1: "Internal", 2: "Server", 3: "Client", 4: "Producer", 5: "Consumer"}
ZERO_PARENT = "00000000000000000000000000000000"


def load_trace_file(path):
    with open(path) as f:
        raw = json.load(f)
    if isinstance(raw, list) and raw and raw[0].get("type") == "text":
        raw = json.loads(raw[0]["text"])
    results = raw.get("results", raw)
    return results if isinstance(results, list) else [results]


def fmt_duration(nanos):
    if nanos is None:
        return "?"
    try:
        n = int(nanos)
    except (TypeError, ValueError):
        return str(nanos)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}s"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}ms"
    if n >= 1_000:
        return f"{n / 1_000:.1f}\u00b5s"
    return f"{n}ns"


def truncate(s, max_len):
    if max_len <= 0 or len(s) <= max_len:
        return s
    return s[:max_len] + "..."


def is_root(span):
    if span.get("is_root_span"):
        return True
    parent = span.get("parent_span_id") or ""
    return not parent or parent == ZERO_PARENT


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

# Detect orphans (parent_span_id points to a span not in the payload).
seen_parents = set()
for span in spans:
    pid = span.get("parent_span_id") or ""
    if pid and pid != ZERO_PARENT and pid not in by_id:
        seen_parents.add(pid)


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
