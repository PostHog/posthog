"""Print a chronological timeline of tool calls and generations in a trace."""

import json
import sys


def load_trace_file(path):
    with open(path) as f:
        raw = json.load(f)
    # Claude Code persists large MCP tool results as [{"type": "text", "text": "<json>"}] — unwrap to get the actual trace data.
    if isinstance(raw, list) and raw and raw[0].get("type") == "text":
        raw = json.loads(raw[0]["text"])
    # Both query-llm-trace and query-llm-traces-list return {"results": [...]}, but handle a bare trace object too.
    results = raw.get("results", raw)
    return [results] if isinstance(results, dict) else results


def summarize(val, max_len=200):
    if val is None:
        return ""
    s = json.dumps(val, default=str) if not isinstance(val, str) else val
    return s[:max_len] + "..." if len(s) > max_len else s


traces = load_trace_file(sys.argv[1])
for trace in traces:
    print(f"\n{'='*80}")
    print(f"Trace: {trace.get('id', '?')}  name={trace.get('traceName', '?')}  latency={trace.get('totalLatency', '?')}s  cost={trace.get('totalCost', '?')}")
    print(f"{'='*80}")
    # Trace-level input/output state (from $ai_trace event, not in events array)
    inp = trace.get("inputState")
    out = trace.get("outputState")
    if inp:
        print(f"  Trace input:  {summarize(inp)}")
    if out:
        print(f"  Trace output: {summarize(out)}")
    events = sorted(trace.get("events", []), key=lambda e: e.get("createdAt", ""))
    for i, ev in enumerate(events, 1):
        p = ev.get("properties", {})
        etype = ev.get("event", "?")
        name = p.get("$ai_span_name", p.get("$ai_model", etype))
        latency = p.get("$ai_latency", "?")
        error = " ERR" if p.get("$ai_is_error") else ""
        print(f"\n{i:>3}. [{etype}] {name}  ({latency}s){error}")
        if "$ai_input_state" in p:
            print(f"     IN:  {summarize(p['$ai_input_state'])}")
        if "$ai_output_state" in p:
            print(f"     OUT: {summarize(p['$ai_output_state'])}")
        if "$ai_input_tokens" in p:
            print(f"     tokens: {p.get('$ai_input_tokens', '?')} in / {p.get('$ai_output_tokens', '?')} out  cost=${p.get('$ai_total_cost_usd', '?')}")
