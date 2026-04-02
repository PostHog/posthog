"""Show JSON keys and types without values. Reads from stdin."""

import json
import sys


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


data = json.load(sys.stdin)
structure(data)
