"""Convert a Python CDP hog function template into its Node equivalent.

Reads the template with `ast` rather than importing it, so it runs without Django.
Emits TypeScript that preserves `code` byte-for-byte, which is what keeps existing
functions from showing as modified after a port.

Usage: python tools/cdp_template_to_ts.py posthog/cdp/templates/slack/template_slack.py
"""

from __future__ import annotations

import ast
import sys
from typing import Any

# Node templates order their keys this way; keep ports consistent with the existing files.
KEY_ORDER = [
    "status",
    "free",
    "type",
    "id",
    "name",
    "description",
    "icon_url",
    "category",
    "code_language",
    "code",
    "inputs_schema",
    "filters",
    "mapping_templates",
    "masking",
]

MAPPING_KEY_ORDER = ["name", "include_by_default", "use_all_events_by_default", "filters", "inputs", "inputs_schema"]


class Unsupported(Exception):
    pass


def _literal(node: ast.AST, scope: dict[str, Any] | None = None) -> Any:
    """Evaluate a node against module-level names, tolerating the idioms templates use.

    Templates build inputs from shared module variables and nest
    HogFunctionMappingTemplate calls, neither of which ast.literal_eval accepts.
    """
    scope = scope or {}
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "strip" and not node.args:
            return _literal(func.value, scope).strip()
        if isinstance(func, ast.Name) and func.id == "HogFunctionMappingTemplate":
            return {kw.arg: _literal(kw.value, scope) for kw in node.keywords}
        raise Unsupported(f"call to {ast.dump(func)[:80]}")
    if isinstance(node, ast.Name):
        if node.id in scope:
            return scope[node.id]
        raise Unsupported(f"unresolved name {node.id!r}")
    if isinstance(node, ast.Subscript):
        return _literal(node.value, scope)[_literal(node.slice, scope)]
    if isinstance(node, (ast.List, ast.Tuple)):
        out: list[Any] = []
        for elt in node.elts:
            if isinstance(elt, ast.Starred):
                out.extend(_literal(elt.value, scope))
            else:
                out.append(_literal(elt, scope))
        return out
    if isinstance(node, ast.Dict):
        result: dict[Any, Any] = {}
        for k, v in zip(node.keys, node.values):
            if k is None:
                result.update(_literal(v, scope))
            else:
                result[_literal(k, scope)] = _literal(v, scope)
        return result
    try:
        return ast.literal_eval(node)
    except ValueError as e:
        raise Unsupported(f"non-literal node: {ast.dump(node)[:120]}") from e


def extract_templates(path: str) -> list[tuple[str, dict[str, Any]]]:
    tree = ast.parse(open(path, encoding="utf-8").read())
    out: list[tuple[str, dict[str, Any]]] = []
    scope: dict[str, Any] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        else:
            continue
        if not targets or value is None:
            continue
        name = targets[0].id if isinstance(targets[0], ast.Name) else "template"
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "HogFunctionTemplateDC"
        ):
            out.append((name, {kw.arg: _literal(kw.value, scope) for kw in value.keywords}))
            continue
        # Templates share input blocks via module-level variables; keep them resolvable.
        try:
            scope[name] = _literal(value, scope)
        except Unsupported:
            pass
    return out


def ts_key(key: str) -> str:
    return key if key.replace("_", "a").isalnum() and not key[0].isdigit() else f"'{key}'"


def ts_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


def ts_value(v: Any, indent: int = 4) -> str:
    pad = " " * indent
    inner = " " * (indent + 4)
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return ts_str(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        items = ",\n".join(inner + ts_value(x, indent + 4) for x in v)
        return "[\n" + items + ",\n" + pad + "]"
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = ",\n".join(f"{inner}{ts_key(k)}: {ts_value(val, indent + 4)}" for k, val in v.items())
        return "{\n" + items + ",\n" + pad + "}"
    raise Unsupported(f"value of type {type(v)}")


def render(fields: dict[str, Any]) -> str:
    lines = ["import { HogFunctionTemplate } from '~/cdp/types'", "", "export const template: HogFunctionTemplate = {"]
    for key in KEY_ORDER:
        if key not in fields:
            continue
        v = fields[key]
        if key == "code":
            # Trimmed so the stored code matches what existing functions copied into
            # their `hog`, which is what the UI diffs to decide if a function is modified.
            body = v.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            lines.append(f"    code: `\n{body}\n`.trim(),")
        elif key == "mapping_templates":
            entries = []
            for m in v:
                ordered = {k: m[k] for k in MAPPING_KEY_ORDER if k in m and m[k] is not None}
                entries.append(" " * 8 + ts_value(ordered, 8))
            lines.append("    mapping_templates: [\n" + ",\n".join(entries) + ",\n    ],")
        else:
            lines.append(f"    {ts_key(key)}: {ts_value(v, 4)},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    path = sys.argv[1]
    templates = extract_templates(path)
    if not templates:
        raise SystemExit(f"no HogFunctionTemplateDC found in {path}")
    for name, fields in templates:
        sys.stdout.write(f"// ===== {name} ({fields.get('id')}) =====" + "\n")
        sys.stdout.write(render(fields) + "\n")


if __name__ == "__main__":
    main()
