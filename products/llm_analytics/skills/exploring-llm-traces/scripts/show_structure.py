"""Show JSON keys and types without values. Reads from stdin or a file argument."""

import json
import sys


def load_trace_data(source):
    raw = json.load(source)
    # Claude Code persists large MCP tool results as [{"type": "text", "text": "<json>"}] — unwrap to get the actual trace data.
    if isinstance(raw, list) and raw and isinstance(raw[0], dict) and raw[0].get("type") == "text":
        raw = json.loads(raw[0]["text"])
    return raw


def structure(obj, depth=0, max_depth=3):
    indent = "  " * depth
    if depth > max_depth:
        print(f"{indent}...")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                print(f"{indent}{k}: {{...}} ({len(v)} keys)")
                structure(v, depth + 1, max_depth)
            elif isinstance(v, list):
                print(f"{indent}{k}: [...] ({len(v)} items)")
                if v:
                    structure(v[0], depth + 1, max_depth)
            elif isinstance(v, str):
                print(f"{indent}{k}: str[{len(v)}]")
            else:
                print(f"{indent}{k}: {v}")
    elif isinstance(obj, list):
        print(f"{indent}[{len(obj)} items]")
        if obj:
            structure(obj[0], depth + 1, max_depth)


if len(sys.argv) > 1:
    with open(sys.argv[1]) as f:
        data = load_trace_data(f)
else:
    data = load_trace_data(sys.stdin)
structure(data)
