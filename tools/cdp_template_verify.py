"""Check that a ported Node template carries the same `code` as its Python original.

Existing hog functions copy the template code into their `hog` field, and the UI diffs
the two to decide whether a function is modified. A port that changes the string by even
one character flags every live function using that template.

Usage: python tools/cdp_template_verify.py <python_template.py> <node_template.ts> [<node_template.ts> ...]
       python tools/cdp_template_verify.py --git <rev> <python_path> <node_template.ts>
"""

from __future__ import annotations

import re
import sys
import subprocess

sys.path.insert(0, "tools")
from cdp_template_to_ts import extract_templates  # noqa: E402


def node_codes(path: str) -> dict[str, str]:
    src = open(path, encoding="utf-8").read()
    ids = re.findall(r"^\s*id: '([^']+)',", src, re.M)
    codes = []
    for m in re.finditer(r"code: `(.*?)`\.trim\(\)", src, re.S):
        raw = m.group(1)
        codes.append(raw.replace("\\`", "`").replace("\\${", "${").replace("\\\\", "\\").strip())
    if len(ids) != len(codes):
        raise SystemExit(f"{path}: found {len(ids)} ids but {len(codes)} `.trim()` code blocks")
    return dict(zip(ids, codes))


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--git":
        rev, py_path = args[1], args[2]
        py_src = subprocess.run(["git", "show", f"{rev}:{py_path}"], capture_output=True, text=True, check=True).stdout
        tmp = "/tmp/_cdp_verify_src.py"
        open(tmp, "w", encoding="utf-8").write(py_src)
        py_path, ts_paths = tmp, args[3:]
    else:
        py_path, ts_paths = args[0], args[1:]

    expected = {fields["id"]: fields["code"] for _, fields in extract_templates(py_path)}
    actual: dict[str, str] = {}
    for p in ts_paths:
        actual.update(node_codes(p))

    failed = False
    for tid, want in expected.items():
        got = actual.get(tid)
        if got is None:
            sys.stdout.write(f"MISSING  {tid}: not found in {', '.join(ts_paths)}" + "\n")
            failed = True
        elif got != want:
            failed = True
            idx = next((i for i in range(max(len(got), len(want))) if got[i : i + 1] != want[i : i + 1]), 0)
            sys.stdout.write(f"DIFFERS  {tid}: first difference at index {idx}" + "\n")
            sys.stdout.write(f"    node: {got[max(0, idx - 40) : idx + 20]!r}" + "\n")
            sys.stdout.write(f"    py  : {want[max(0, idx - 40) : idx + 20]!r}" + "\n")
            sys.stdout.write(f"    node char {got[idx : idx + 1]!r} vs py char {want[idx : idx + 1]!r}" + "\n")
        else:
            sys.stdout.write(f"OK       {tid}: code identical ({len(want)} chars)" + "\n")

    extra = set(actual) - set(expected)
    if extra:
        sys.stdout.write(f"note: node file also defines {sorted(extra)}" + "\n")

    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
