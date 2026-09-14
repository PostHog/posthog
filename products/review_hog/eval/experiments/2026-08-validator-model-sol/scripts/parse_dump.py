"""Parse a reviewer-quality dump's 'Findings (post-dedup) with validator verdict' section into JSON.

    python parse_dump.py <dump.md> <set_letter> <out.json>

Finding ids are <set_letter><n> in dump order — the same convention the old judge files use
(blind set S = I1 dump order, W = I2, ...).
"""

import re
import sys
import json
from pathlib import Path
from typing import Any

text = Path(sys.argv[1]).read_text()
letter = sys.argv[2]
section = text.split("## Findings (post-dedup) with validator verdict", 1)[1]
blocks = re.split(r"\n### ", section)[1:]
out: list[dict[str, Any]] = []
for i, b in enumerate(blocks, 1):
    head, _, body = b.partition("\n")
    m = re.match(r"\[(.+?)\] (\w+)(?: \(validator→(\w+)\))?(?: · (\S+))? — (.+?):([\d,\-]+):?\s*$", head.strip())
    verdict, priority, vprio, category, path, lines = m.groups() if m else ("?", "?", None, "?", head, "")
    category = category or "-"
    title = re.search(r"\*\*(.+?)\*\*", body)
    problem = re.search(r"\*\*Problem:\*\* (.+)", body)
    suggestion = re.search(r"\*\*Suggestion:\*\* (.+)", body)
    # The validator block starts at "- **Validator:**" and runs to the end of the finding; its bullets
    # may carry labels ("- **Found (no tenant leak):**") and blank lines between them.
    vlines: list[str] = []
    in_validator = False
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- **Validator:**"):
            in_validator = True
        if in_validator and stripped:
            vlines.append(stripped.lstrip("- ").strip())
    validator = "\n".join(vlines)
    out.append(
        {
            "id": f"{letter}{i}",
            "is_valid": "VALID" in verdict,
            "priority": priority,
            "validator_priority": vprio,
            "category": category,
            "file": path.strip(),
            "lines": lines,
            "title": title.group(1) if title else "",
            "problem": problem.group(1).strip() if problem else "",
            "suggestion": suggestion.group(1).strip() if suggestion else "",
            "validator": validator,
        }
    )
Path(sys.argv[3]).write_text(json.dumps(out, indent=1))
print(f"{sys.argv[1]}: {len(out)} findings, valid={sum(o['is_valid'] for o in out)}")
for o in out:
    print(
        f"  {o['id']:<4} {'VALID' if o['is_valid'] else 'drop ':<5} {o['priority']:<10} {o['file']}:{o['lines']}  {o['title'][:70]}"
    )
