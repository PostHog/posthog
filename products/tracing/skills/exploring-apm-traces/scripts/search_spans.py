"""Search spans by keyword across name, service_name, span_id, trace_id, parent_span_id.

Usage:
  SEARCH="db.query" python3 scripts/search_spans.py FILE
  SEARCH="payment-service" python3 scripts/search_spans.py FILE

NOTE: This script scans only name/service/ID fields, not the span `attributes` map (which
IS in the payload). To search the whole dataset by an attribute (e.g. http.method,
http.status_code) or by a resource attribute (k8s labels), use the MCP tools
posthog:apm-attributes-list and posthog:apm-attribute-values-list, then re-issue
posthog:query-apm-spans with a filterGroup of type 'span_attribute' or
'span_resource_attribute'.

Env vars:
  SEARCH   — keyword to match (case-insensitive substring)
  MAX_LEN  — truncation limit per match snippet (default 200, 0 = unlimited)
"""

import os
import sys

from _common import SPAN_KIND, fmt_duration, load_trace_file


# Span fields scanned for the keyword. Excludes timestamp/duration/kind/status_code —
# numeric/structural fields that are better matched via filterGroup, not free text.
SEARCH_FIELDS = ("name", "service_name", "span_id", "trace_id", "parent_span_id", "uuid")


def snippet(value, term, max_len):
    s = str(value)
    lower = s.lower()
    idx = lower.index(term)
    if max_len <= 0:
        return s
    pad = 80
    start = max(0, idx - pad)
    end = min(len(s), idx + len(term) + pad)
    out = s[start:end]
    if len(out) > max_len:
        out = out[:max_len] + "..."
    return out


term = os.environ.get("SEARCH", "").lower()
if not term:
    print("Usage: SEARCH='keyword' python3 search_spans.py FILE", file=sys.stderr)
    sys.exit(1)

max_len = int(os.environ.get("MAX_LEN", "200"))

spans = load_trace_file(sys.argv[1])
if not spans:
    print("No spans in payload.", file=sys.stderr)
    sys.exit(1)

hits = 0
for span in spans:
    matched_fields = []
    for field in SEARCH_FIELDS:
        value = span.get(field)
        if value is None:
            continue
        if term in str(value).lower():
            matched_fields.append((field, value))

    if not matched_fields:
        continue
    hits += 1

    err = " [ERROR]" if span.get("status_code") == 2 else ""
    name = span.get("name", "?")
    print(f"\n[{span.get('service_name', '?')}] {name}  ({fmt_duration(span.get('duration_nano'))}) <{SPAN_KIND.get(span.get('kind'), span.get('kind'))}>{err}")
    print(f"  span_id={span.get('span_id', '?')}  ts={span.get('timestamp', '?')}")
    for field, value in matched_fields:
        print(f"    {field}: ...{snippet(value, term, max_len)}...")

print(f"\nMatched {hits} span(s) for '{term}' across {len(spans)} scanned.")
if hits == 0:
    print("\nReminder: this script scans name/service/IDs only. Span attributes (http.method, etc.) ARE")
    print("in each span's `attributes` map — or filter the dataset via posthog:query-apm-spans filterGroup.")
