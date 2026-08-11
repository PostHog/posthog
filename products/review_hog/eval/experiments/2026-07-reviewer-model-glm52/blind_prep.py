"""Blind a run dump's findings section for judge agents.

Strips validator verdicts/argumentation and the model-identifying header prefix, keeping the
finder's own priority + location + body. Usage:

    python blind_prep.py <dump.md> <SET_LABEL> <out_dir>

Writes <out_dir>/set<SET_LABEL>.md with findings renumbered <SET_LABEL>1..N.
"""

import re
import sys


def blind(dump_path: str, label: str, out_dir: str) -> int:
    text = open(dump_path).read()
    section = text.split("## Findings (post-dedup) with validator verdict", 1)[1]
    blocks = re.split(r"\n(?=### )", section)
    out: list[str] = []
    n = 0
    for b in blocks:
        if not b.startswith("### "):
            continue
        n += 1
        header = b.split("\n", 1)[0]
        m = re.match(r"### \[[^\]]*\] (\S+)(?: \(validator→[^)]*\))?(?: · [^—]*)?— (.+)", header)
        prio, loc = (m.group(1), m.group(2)) if m else ("?", header)
        body = b.split("\n", 1)[1]
        body = re.sub(r"- \*\*Validator:\*\*.*(?:\n(?!- \*\*|### ).*)*", "", body)
        out.append(f"### {label}{n} — {prio} — {loc}\n{body.strip()}\n")
    with open(f"{out_dir}/set{label}.md", "w") as fh:
        fh.write(f"# Finding set {label} ({n} findings)\n\n" + "\n".join(out))
    return n


if __name__ == "__main__":
    print(f"set{sys.argv[2]} = {blind(sys.argv[1], sys.argv[2], sys.argv[3])} findings")  # noqa: T201
