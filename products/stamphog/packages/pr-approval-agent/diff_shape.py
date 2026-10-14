"""The shape of a PR's diff: whether any changed file can alter production behavior.

A file is one of five shapes. `docs` and `test` come from the path, through the same
`classify_path` the tier gate uses. `comment` and `docstring` come from parsing both sides of a
modified Python file: the two syntax trees must match once docstrings are removed, so a string
literal dressed up as a comment still counts as code. Every other file is `logic`, including
TypeScript and JavaScript, because the engine ships no parser for them.

A comment can still change behavior when a tool reads it: `# noqa`, `# nosemgrep`, `# type:`,
an encoding cookie. Any change to such a directive, or to the code it sits on, makes the file
`logic`.
"""

import io
import re
import ast
import tokenize
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from gates import classify_path

FileShape = Literal["comment", "docstring", "docs", "test", "logic"]

_STATUSES_WITH_PATH_SHAPE = ("A", "M", "D")

_DIRECTIVE_COMMENT_RE = re.compile(
    r"^#!|coding[:=]|\b(?:noqa|nosemgrep|nosec|pragma|type:|ty:|pyright:|mypy:|pylint:|ruff:|fmt:|isort:)",
    re.IGNORECASE,
)

_LAYOUT_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
)

_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

BlobReader = Callable[[str], bytes | None]


@dataclass(frozen=True, kw_only=True)
class DiffShape:
    file_shapes: tuple[tuple[str, FileShape], ...]

    @property
    def approvable(self) -> bool:
        return bool(self.file_shapes) and all(shape != "logic" for _, shape in self.file_shapes)

    @property
    def label(self) -> str:
        if not self.approvable:
            return "logic"
        return "+".join(sorted({shape for _, shape in self.file_shapes})) + "-only"


def _path_shape(file: Mapping[str, object]) -> FileShape | None:
    """The shape the path alone decides, or None for a modified Python file that needs parsing."""
    status = str(file.get("status", "M"))[:1]
    if file.get("binary") or status not in _STATUSES_WITH_PATH_SHAPE:
        return "logic"
    path = str(file["filename"])
    kind = classify_path(path)
    if kind == "test":
        return "test"
    if kind == "docs":
        return "docs"
    if status == "M" and path.lower().endswith(".py"):
        return None
    return "logic"


def could_be_approvable(files: Iterable[Mapping[str, object]]) -> bool:
    """Whether the diff could have an approvable shape, judged from paths alone, without reading a blob."""
    files = list(files)
    return bool(files) and all(_path_shape(f) != "logic" for f in files)


def _directive_anchors(source: bytes) -> Counter[tuple[str, str]]:
    """Each directive comment with the code it applies to: its own line, or the next code line."""
    code_by_line: dict[int, list[str]] = {}
    comments: list[tuple[int, str]] = []
    for token in tokenize.tokenize(io.BytesIO(source).readline):
        if token.type == tokenize.COMMENT:
            if _DIRECTIVE_COMMENT_RE.search(token.string):
                comments.append((token.start[0], token.string.strip()))
        elif token.type not in _LAYOUT_TOKENS:
            code_by_line.setdefault(token.start[0], []).append(token.string)
    code_lines = sorted(code_by_line)
    anchors: Counter[tuple[str, str]] = Counter()
    for line, comment in comments:
        anchor_line = line if line in code_by_line else next((n for n in code_lines if n > line), None)
        anchors[(comment, " ".join(code_by_line.get(anchor_line, [])) if anchor_line is not None else "")] += 1
    return anchors


def _without_docstrings(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_OWNERS) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            node.body = node.body[1:]
    return tree


def python_change_shape(base: bytes, head: bytes) -> FileShape:
    """`comment` when only comments or layout changed, `docstring` when docstrings did too, else `logic`."""
    try:
        base_tree = ast.parse(base)
        head_tree = ast.parse(head)
        directives_changed = _directive_anchors(base) != _directive_anchors(head)
    except (SyntaxError, ValueError, tokenize.TokenError):
        return "logic"
    if directives_changed:
        return "logic"
    if ast.dump(base_tree) == ast.dump(head_tree):
        return "comment"
    if ast.dump(_without_docstrings(base_tree)) == ast.dump(_without_docstrings(head_tree)):
        return "docstring"
    return "logic"


def classify_diff_shape(
    files: Iterable[Mapping[str, object]], read_base: BlobReader, read_head: BlobReader
) -> DiffShape:
    """Shape every changed file, stopping at the first `logic` file, since one decides the PR."""
    shapes: list[tuple[str, FileShape]] = []
    for file in files:
        path = str(file["filename"])
        shape = _path_shape(file)
        if shape is None:
            base = read_base(path)
            head = read_head(path)
            shape = "logic" if base is None or head is None else python_change_shape(base, head)
        shapes.append((path, shape))
        if shape == "logic":
            break
    return DiffShape(file_shapes=tuple(shapes))
