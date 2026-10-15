"""The shape of a PR's diff: whether any changed file can alter production behavior.

A file is one of five shapes. `docs` and `test` come from the path, through the same
`classify_path` the tier gate uses. `comment` and `docstring` come from parsing both sides of a
modified Python file: the two syntax trees must match once docstrings are removed, so a string
literal dressed up as a comment still counts as code. Every other file is `logic`, including
TypeScript and JavaScript, because the engine ships no parser for them.

A comment can still change behavior when a tool reads it: `# noqa`, `# nosemgrep`, `# type:`,
an encoding cookie, a PEP 723 script metadata block. Any change to such a directive, to its order,
to whether it sits inline or on its own line, or to the statement it applies to, makes the file
`logic`. So does a file mode change.

Markdown and docstrings pass the size gate, but never waive the assurance rule, because both can
ship: prompt templates, LLM tool descriptions and schema descriptions are read at runtime.
"""

import io
import re
import ast
import bisect
import tokenize
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from gates import classify_path

FileShape = Literal["comment", "docstring", "docs", "test", "logic"]

_STATUSES_WITH_PATH_SHAPE = ("A", "M", "D")

_DIRECTIVE_COMMENT_RE = re.compile(
    r"^#!|coding[:=]|\b(?:noqa|nosemgrep|nosec|pragma|type:|ty:|pyright:|mypy:|pylint:|ruff:|fmt:|isort:)",
    re.IGNORECASE,
)
_POSITIONAL_DIRECTIVE_RE = re.compile(r"^#!|coding[:=]", re.IGNORECASE)
_SCRIPT_METADATA_RE = re.compile(r"^#\s*///")

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

_SHAPES_THAT_MAY_SHIP: frozenset[FileShape] = frozenset({"docs", "docstring"})

BlobReader = Callable[[str], bytes | None]


@dataclass(frozen=True, kw_only=True)
class DiffShape:
    file_shapes: tuple[tuple[str, FileShape], ...]

    @property
    def approvable(self) -> bool:
        return bool(self.file_shapes) and all(shape != "logic" for _, shape in self.file_shapes)

    @property
    def waives_assurance(self) -> bool:
        return self.approvable and all(shape not in _SHAPES_THAT_MAY_SHIP for _, shape in self.file_shapes)

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


@dataclass(frozen=True, kw_only=True)
class _DirectiveAnchor:
    comment: str
    inline: bool
    code_line_index: int | None
    position: tuple[int, int] | None


def _directive_anchors(source: bytes) -> tuple[_DirectiveAnchor, ...]:
    """Each directive comment, in order, with where it sits and which code line it applies to.

    The code line is its index among the lines that hold code, which a comment-only edit leaves
    unchanged, so it identifies the statement even when two statements read the same.
    """
    code_lines: set[int] = set()
    directives: list[tuple[tuple[int, int], str]] = []
    in_script_metadata = False
    for token in tokenize.tokenize(io.BytesIO(source).readline):
        if token.type == tokenize.COMMENT:
            text = token.string.strip()
            opens_or_closes_metadata = bool(_SCRIPT_METADATA_RE.match(text))
            if opens_or_closes_metadata or in_script_metadata or _DIRECTIVE_COMMENT_RE.search(text):
                directives.append((token.start, text))
            if opens_or_closes_metadata:
                in_script_metadata = not in_script_metadata
        elif token.type not in _LAYOUT_TOKENS:
            code_lines.add(token.start[0])
    ordered_code_lines = sorted(code_lines)
    anchors: list[_DirectiveAnchor] = []
    for (line, column), comment in directives:
        anchor_index = bisect.bisect_left(ordered_code_lines, line)
        anchors.append(
            _DirectiveAnchor(
                comment=comment,
                inline=line in code_lines,
                code_line_index=anchor_index if anchor_index < len(ordered_code_lines) else None,
                position=(line, column) if _POSITIONAL_DIRECTIVE_RE.search(comment) else None,
            )
        )
    return tuple(anchors)


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
        if _directive_anchors(base) != _directive_anchors(head):
            return "logic"
        base_tree = ast.parse(base)
        head_tree = ast.parse(head)
        if ast.dump(base_tree) == ast.dump(head_tree):
            return "comment"
        if ast.dump(_without_docstrings(base_tree)) == ast.dump(_without_docstrings(head_tree)):
            return "docstring"
    except (SyntaxError, ValueError, tokenize.TokenError, RecursionError, MemoryError):
        return "logic"
    return "logic"


def classify_diff_shape(
    files: Iterable[Mapping[str, object]],
    *,
    read_base: BlobReader,
    read_head: BlobReader,
    mode_changed_paths: Collection[str] | None,
) -> DiffShape:
    """Shape every changed file, stopping at the first `logic` file, since one decides the PR.

    ``mode_changed_paths`` is None when git could not report file modes, and every file is then `logic`.
    """
    shapes: list[tuple[str, FileShape]] = []
    for file in files:
        path = str(file["filename"])
        shape = _path_shape(file)
        if mode_changed_paths is None or path in mode_changed_paths:
            shape = "logic"
        elif shape is None:
            base = read_base(path)
            head = read_head(path)
            shape = "logic" if base is None or head is None else python_change_shape(base, head)
        shapes.append((path, shape))
        if shape == "logic":
            break
    return DiffShape(file_shapes=tuple(shapes))
