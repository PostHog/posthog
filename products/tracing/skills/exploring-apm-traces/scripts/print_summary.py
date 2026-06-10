"""Print a concise APM trace summary: services, slowest spans, errors.

Usage:
  python3 scripts/print_summary.py FILE

Env vars:
  MAX_LEN  — truncation limit for span names (default 100, 0 = unlimited)
"""

import os
import sys

from _common import SPAN_KIND, fmt_duration, is_root, load_trace_file, truncate


max_len = int(os.environ.get("MAX_LEN", "100"))

spans = load_trace_file(sys.argv[1])
if not spans:
    print("No spans in payload.", file=sys.stderr)
    sys.exit(1)

trace_id = spans[0].get("trace_id", "?")

# Bucket spans by service and kind, find roots, slowest, errors.
services = {}  # name -> count
kinds = {}  # int -> count
roots = []
errors = []
for span in spans:
    svc = span.get("service_name", "?")
    services[svc] = services.get(svc, 0) + 1
    k = span.get("kind")
    kinds[k] = kinds.get(k, 0) + 1
    if is_root(span):
        roots.append(span)
    if span.get("status_code") == 2:
        errors.append(span)

slowest = sorted(spans, key=lambda s: int(s.get("duration_nano") or 0), reverse=True)[:5]

print("=" * 80)
print("APM TRACE SUMMARY")
print("=" * 80)
print(f"  Trace ID:    {trace_id}")
print(f"  Span count:  {len(spans)}")
print(f"  Services:    {', '.join(f'{n} ({c})' for n, c in sorted(services.items(), key=lambda x: -x[1]))}")
print(f"  Span kinds:  {', '.join(f'{SPAN_KIND.get(k, k)}={c}' for k, c in sorted(kinds.items()))}")
print(f"  Root spans:  {len(roots)}")
print(f"  Errors:      {len(errors)}")

if roots:
    print()
    print("--- ROOT SPAN(S) ---")
    for r in roots:
        name = truncate(r.get("name", "?"), max_len)
        print(f"  [{r.get('service_name', '?')}] {name}  ({fmt_duration(r.get('duration_nano'))})")
        print(f"    span_id={r.get('span_id', '?')}  ts={r.get('timestamp', '?')}")

print()
print("--- TOP-5 SLOWEST SPANS ---")
for span in slowest:
    name = truncate(span.get("name", "?"), max_len)
    err = " [ERROR]" if span.get("status_code") == 2 else ""
    print(f"  [{span.get('service_name', '?')}] {name}  ({fmt_duration(span.get('duration_nano'))}){err}")
    print(f"    kind={SPAN_KIND.get(span.get('kind'), span.get('kind'))}  span_id={span.get('span_id', '?')}")

if errors:
    print()
    print("!" * 80)
    print(f"ERROR SPANS ({len(errors)})")
    print("!" * 80)
    for span in errors:
        name = truncate(span.get("name", "?"), max_len)
        print(f"  [{span.get('service_name', '?')}] {name}  ({fmt_duration(span.get('duration_nano'))})")
        print(f"    kind={SPAN_KIND.get(span.get('kind'), span.get('kind'))}  span_id={span.get('span_id', '?')}  parent={span.get('parent_span_id', '?')}")
    print()
    print("Error detail (exception.message/type) is in each span's `attributes` map in the payload — read it off the error span.")
