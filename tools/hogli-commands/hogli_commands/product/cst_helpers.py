"""libcst-based source rewriting for product isolation moves.

Kept separate from isolate.py's regex rewriting because the two solve different
problems. Fully qualified absolute paths (and the string references the regex
deliberately also rewrites, like ``@patch`` mock paths) are lexically
unambiguous, so a guarded literal substitution is the right tool. *Relative*
imports are not: ``from ..x import y`` only resolves once you know the importing
module's package, and the depth can be arbitrary — exactly the case a line regex
has to punt on. This resolves them with a real parse instead.

Mirrors the relative-import resolution proven in the product-model-migration
skill's ``import_rewriter.py`` rather than reinventing it.
"""

from __future__ import annotations

import libcst as cst


def dotted_name(node: cst.BaseExpression | None) -> str | None:
    """Dotted module name from a ``Name``/``Attribute`` expression, else None."""
    if node is None:
        return None
    parts: list[str] = []
    current: cst.BaseExpression | None = node
    while isinstance(current, cst.Attribute):
        parts.append(current.attr.value)
        current = current.value
    if not isinstance(current, cst.Name):
        return None
    parts.append(current.value)
    return ".".join(reversed(parts))


def resolve_relative(package: str, level: int, module: str | None) -> str | None:
    """Absolute dotted path for a relative import inside ``package``.

    ``package`` is the importing file's own package (the regex tool's contract):
    level 1 (``from .x``) resolves against ``package`` itself, and each extra dot
    climbs one parent. Returns None if the climb runs past the package root.
    """
    parts = package.split(".")
    climb = level - 1
    if climb > len(parts):
        return None
    base = parts[: len(parts) - climb] if climb else list(parts)
    if module:
        base += module.split(".")
    return ".".join(base) or None


class _RelativeImportAbsolutizer(cst.CSTTransformer):
    def __init__(self, package: str) -> None:
        self.package = package
        self.warnings: list[str] = []

    def leave_ImportFrom(self, _original_node: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.ImportFrom:
        if not updated_node.relative:
            return updated_node
        level = len(updated_node.relative)
        absolute = resolve_relative(self.package, level, dotted_name(updated_node.module))
        if absolute is None:
            self.warnings.append(f"could not resolve a level-{level} relative import against {self.package}")
            return updated_node
        return updated_node.with_changes(relative=[], module=cst.parse_expression(absolute))


def absolutize_relative_imports(text: str, package: str) -> tuple[str, list[str]]:
    """Rewrite every relative import in ``text`` to absolute, resolved against ``package``.

    Any depth of leading dots is handled (unlike a line regex), formatting is
    preserved, and a file libcst can't parse is returned unchanged with a warning.
    """
    try:
        module = cst.parse_module(text)
    except cst.ParserSyntaxError as exc:
        return text, [f"libcst could not parse the module, relative imports left untouched ({exc})"]
    transformer = _RelativeImportAbsolutizer(package)
    return module.visit(transformer).code, transformer.warnings
