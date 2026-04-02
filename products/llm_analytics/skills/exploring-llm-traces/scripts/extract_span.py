"""Extract a specific span's full input/output state by name.

Usage:
  SPAN="upsert_dashboard" python3 scripts/extract_span.py FILE
  SPAN="router" python3 scripts/extract_span.py FILE

Env vars:
  SPAN     — span name to match (case-insensitive substring match)
  MAX_LEN  — truncation limit (default 0 = unlimited)
"""

import json
import os
import sys


def load_trace_file(path):
    with open(path) as f:
        raw = json.load(f)
    if isinstance(raw, list) and raw and raw[0].get("type") == "text":
        raw = json.loads(raw[0]["text"])
    results = raw.get("results", raw)
    return [results] if isinstance(results, dict) else results


def truncate(text, max_len):
    if max_len <= 0 or len(text) <= max_len:
        return text
    return text[:max_len] + f"... [{len(text)} chars total]"


span_filter = os.environ.get("SPAN", "").lower()
if not span_filter:
    print("Usage: SPAN='span_name' python3 extract_span.py file.json", file=sys.stderr)
    sys.exit(1)

max_len = int(os.environ.get("MAX_LEN", "0"))

traces = load_trace_file(sys.argv[1])
found = 0
for trace in traces:
    events = sorted(trace.get("events", []), key=lambda e: e.get("createdAt", ""))
    for ev in events:
        if ev.get("event") != "$ai_span":
            continue
        p = ev.get("properties", {})
        name = p.get("$ai_span_name", "")
        if span_filter not in name.lower():
            continue
        found += 1
        error = " [ERROR]" if p.get("$ai_is_error") else ""
        print(f"\n{'='*80}")
        print(f"SPAN: {name}  ({p.get('$ai_latency', '?')}s){error}")
        print(f"Created: {ev.get('createdAt', '?')}")
        print(f"Parent: {p.get('$ai_parent_id', '(root)')}")
        print(f"{'='*80}")

        inp = p.get("$ai_input_state")
        out = p.get("$ai_output_state")

        if inp is not None:
            formatted = json.dumps(inp, indent=2, default=str) if not isinstance(inp, str) else inp
            print(f"\n--- INPUT STATE ---")
            print(truncate(formatted, max_len))

        if out is not None:
            formatted = json.dumps(out, indent=2, default=str) if not isinstance(out, str) else out
            print(f"\n--- OUTPUT STATE ---")
            print(truncate(formatted, max_len))

        if not inp and not out:
            print("\n  (no input_state or output_state)")

if found == 0:
    print(f"No spans matching '{span_filter}' found.", file=sys.stderr)
    sys.exit(1)
