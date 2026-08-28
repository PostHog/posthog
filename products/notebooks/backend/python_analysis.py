import ast
import hashlib
import builtins
from dataclasses import dataclass
from typing import Any

from products.notebooks.backend.globals_scope import GlobalAnalyzer, collect_scope_locals
from products.notebooks.backend.type_inference import collect_exported_types


@dataclass(frozen=True)
class PythonGlobalsAnalysis:
    used: list[str]
    exported_with_types: list[dict[str, str]]


def analyze_python_globals(code: str) -> PythonGlobalsAnalysis:
    if not code or not code.strip():
        return PythonGlobalsAnalysis(used=[], exported_with_types=[])

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return PythonGlobalsAnalysis(used=[], exported_with_types=[])

    module_locals = collect_scope_locals(tree.body)
    builtins_names = set(dir(builtins))
    analyzer = GlobalAnalyzer(module_locals, builtins_names)
    analyzer.visit(tree)
    exported_types = collect_exported_types(tree.body)
    exported_with_types = [
        {"name": name, "type": exported_types.get(name, "unknown")} for name in sorted(module_locals)
    ]

    return PythonGlobalsAnalysis(
        used=sorted(analyzer.used),
        exported_with_types=exported_with_types,
    )


def compute_globals_analysis_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def annotate_python_nodes(content: Any) -> Any:
    if not isinstance(content, dict):
        return content

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node

        node_type = node.get("type")
        if node_type == "ph-python":
            attrs = node.get("attrs")
            if isinstance(attrs, dict):
                code = attrs.get("code", "")
                if isinstance(code, str):
                    code_hash = compute_globals_analysis_hash(code)
                    existing_hash = attrs.get("globalsAnalysisHash")
                    has_cached_analysis = (
                        isinstance(existing_hash, str)
                        and existing_hash == code_hash
                        and "globalsUsed" in attrs
                        and "globalsExportedWithTypes" in attrs
                    )
                    if not has_cached_analysis:
                        analysis = analyze_python_globals(code)
                        attrs = {
                            **attrs,
                            "globalsUsed": analysis.used,
                            "globalsExportedWithTypes": analysis.exported_with_types,
                            "globalsAnalysisHash": code_hash,
                        }
                        node = {**node, "attrs": attrs}

        content_nodes = node.get("content")
        if isinstance(content_nodes, list):
            node = {**node, "content": [walk(child) for child in content_nodes]}

        return node

    return walk(content)
