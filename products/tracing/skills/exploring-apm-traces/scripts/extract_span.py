"""Extract spans matching a name (case-insensitive substring) with parent/children context.

Usage:
  SPAN="HTTP GET /api" python3 scripts/extract_span.py FILE
  SPAN="db.query" python3 scripts/extract_span.py FILE

Env vars:
  SPAN     — name substring to match (required)
  MAX_LEN  — truncation limit (default 0 = unlimited)
"""

import json
import os
import sys

from _common import SPAN_KIND, STATUS_CODE, fmt_duration, is_zero_id, load_trace_file, truncate


def format_span_line(span):
    name = span.get("name", "?")
    return f"[{span.get('service_name', '?')}] {name}  ({fmt_duration(span.get('duration_nano'))}) <{SPAN_KIND.get(span.get('kind'), span.get('kind'))}>"


span_filter = os.environ.get("SPAN", "").lower()
if not span_filter:
    print("Usage: SPAN='span_name' python3 extract_span.py FILE", file=sys.stderr)
    sys.exit(1)

max_len = int(os.environ.get("MAX_LEN", "0"))

spans = load_trace_file(sys.argv[1])
if not spans:
    print("No spans in payload.", file=sys.stderr)
    sys.exit(1)

by_id = {s.get("span_id"): s for s in spans if s.get("span_id")}
children = {}
for span in spans:
    pid = span.get("parent_span_id") or ""
    children.setdefault(pid, []).append(span)

matches = [s for s in spans if span_filter in (s.get("name", "") or "").lower()]

if not matches:
    print(f"No spans matching '{span_filter}' found ({len(spans)} spans scanned).", file=sys.stderr)
    sys.exit(1)

print(f"Matched {len(matches)} span(s) for '{span_filter}'.\n")

for span in matches:
    print("=" * 80)
    print(format_span_line(span))
    err = " [ERROR]" if span.get("status_code") == 2 else ""
    print(f"  status: {STATUS_CODE.get(span.get('status_code'), span.get('status_code'))}{err}")
    print(f"  span_id:        {span.get('span_id', '?')}")
    print(f"  parent_span_id: {span.get('parent_span_id', '?')}")
    print(f"  trace_id:       {span.get('trace_id', '?')}")
    print(f"  timestamp:      {span.get('timestamp', '?')}")
    print(f"  end_time:       {span.get('end_time', '?')}")
    print(f"  is_root_span:   {span.get('is_root_span', False)}")
    print("=" * 80)

    formatted = json.dumps(span, indent=2, default=str)
    print("\n--- FULL ROW ---")
    print(truncate(formatted, max_len, show_total=True))

    parent_id = span.get("parent_span_id") or ""
    parent = by_id.get(parent_id) if parent_id and not is_zero_id(parent_id) else None
    print("\n--- PARENT ---")
    if parent:
        print(f"  {format_span_line(parent)}")
        print(f"  span_id={parent.get('span_id', '?')}")
    elif is_zero_id(parent_id):
        print("  (this is a root span)")
    else:
        print(f"  (parent {parent_id} not in payload)")

    sid = span.get("span_id")
    kids = children.get(sid, []) if sid else []
    print(f"\n--- CHILDREN ({len(kids)}) ---")
    for kid in sorted(kids, key=lambda s: s.get("timestamp", "")):
        print(f"  {format_span_line(kid)}")
        print(f"    span_id={kid.get('span_id', '?')}")
    if not kids:
        print("  (none)")
    print()
