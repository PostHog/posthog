"""Print a concise trace summary: metadata, tool calls, and final LLM output."""

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


def summarize(val, max_len=500):
    if val is None:
        return ""
    s = json.dumps(val, default=str) if not isinstance(val, str) else val
    return s[:max_len] + "..." if len(s) > max_len else s


def extract_final_output(choices):
    """Extract the text and thinking from the last generation's output choices."""
    if not isinstance(choices, list):
        return None, None
    parts_text = []
    parts_thinking = []
    for choice in choices:
        content = choice.get("content", "")
        if isinstance(content, str):
            parts_text.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "thinking":
                        parts_thinking.append(item.get("thinking", ""))
                    elif item.get("type") == "text":
                        parts_text.append(item.get("text", ""))
    return "\n".join(parts_text) or None, "\n".join(parts_thinking) or None


max_len = int(os.environ.get("MAX_LEN", "500"))

traces = load_trace_file(sys.argv[1])
for trace in traces:
    print(f"{'='*80}")
    print(f"TRACE SUMMARY")
    print(f"{'='*80}")
    print(f"  ID:        {trace.get('id', '?')}")
    print(f"  Name:      {trace.get('traceName', '?')}")
    print(f"  Created:   {trace.get('createdAt', '?')}")
    print(f"  Person:    {trace.get('distinctId', '?')}")
    print(f"  Latency:   {trace.get('totalLatency', '?')}s")
    print(f"  Cost:      ${trace.get('totalCost', '?')}")
    print(f"  Tokens in: {trace.get('inputTokens', '?')}")
    print(f"  Tokens out:{trace.get('outputTokens', '?')}")

    # Trace-level input/output state
    inp = trace.get("inputState")
    out = trace.get("outputState")
    if inp:
        print(f"\n--- Trace input state ---")
        print(f"  {summarize(inp, max_len)}")
    if out:
        print(f"\n--- Trace output state (first {max_len} chars) ---")
        print(f"  {summarize(out, max_len)}")

    events = sorted(trace.get("events", []), key=lambda e: e.get("createdAt", ""))

    # Collect models used
    models = set()
    for ev in events:
        if ev.get("event") == "$ai_generation":
            m = ev["properties"].get("$ai_model")
            if m:
                models.add(m)
    if models:
        print(f"\n  Models:    {', '.join(sorted(models))}")

    # Errors
    errors = [ev for ev in events if ev.get("properties", {}).get("$ai_is_error")]
    if errors:
        print(f"\n{'!' * 80}")
        print(f"  ERRORS: {len(errors)}")
        for ev in errors:
            p = ev["properties"]
            name = p.get("$ai_span_name", p.get("$ai_model", ev.get("event")))
            print(f"    - {name}: {summarize(p.get('$ai_output_state', p.get('$ai_error', '?')), max_len)}")
        print(f"{'!' * 80}")
    else:
        print("\n  Errors:    None")

    # Tool calls (spans with input/output state)
    spans = [ev for ev in events if ev.get("event") == "$ai_span" and ev.get("properties", {}).get("$ai_input_state")]
    if spans:
        print(f"\n{'=' * 80}")
        print(f"TOOL CALLS ({len(spans)} spans with I/O)")
        print(f"{'=' * 80}")
        for ev in spans:
            p = ev["properties"]
            name = p.get("$ai_span_name", "?")
            latency = p.get("$ai_latency", "?")
            error = " [ERROR]" if p.get("$ai_is_error") else ""
            print(f"\n  [{name}] ({latency}s){error}")
            print(f"    IN:  {summarize(p.get('$ai_input_state'), max_len)}")
            print(f"    OUT: {summarize(p.get('$ai_output_state'), max_len)}")

    # Final LLM output (last generation)
    generations = [ev for ev in events if ev.get("event") == "$ai_generation"]
    if generations:
        last_gen = generations[-1]
        p = last_gen["properties"]
        text, thinking = extract_final_output(p.get("$ai_output_choices", []))
        print(f"\n{'='*80}")
        print(f"FINAL LLM OUTPUT ({p.get('$ai_model', '?')})")
        print(f"{'='*80}")
        if thinking:
            print(f"\n  [thinking] {thinking[:max_len]}{'...' if len(thinking) > max_len else ''}")
        if text:
            print(f"\n  {text[:max_len * 2]}{'...' if len(text) > max_len * 2 else ''}")
