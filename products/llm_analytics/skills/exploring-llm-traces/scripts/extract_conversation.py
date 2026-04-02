"""Extract user/assistant messages from LLM generation events in a trace."""

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


def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", p.get("type", "")) for p in content if isinstance(p, dict))
    return str(content)


traces = load_trace_file(sys.argv[1])
for trace in traces:
    for ev in sorted(trace.get("events", []), key=lambda e: e.get("createdAt", "")):
        if ev.get("event") != "$ai_generation":
            continue
        p = ev.get("properties", {})
        messages = p.get("$ai_input")
        if not isinstance(messages, list):
            continue
        model = p.get("$ai_model", "?")
        print(f"\n{'='*80}")
        print(f"Generation: {model}  ({ev.get('createdAt', '?')})")
        print(f"{'='*80}")
        for msg in messages:
            role = msg.get("role", "?")
            text = extract_text(msg.get("content", ""))
            if len(text) > 500:
                text = text[:250] + f"\n  ... [{len(text)} chars] ...\n  " + text[-250:]
            print(f"\n[{role.upper()}]\n  {text}")
