"""Extract comments from source files and scan them for sensitive data.

Two entry points:
- `scan_files(paths)` — full-file scan for any file in the changed set.
- `scan_diff_added_lines(diff_text)` — scans only newly-added lines from a
  unified diff. This is what the pre-push hook uses, so previously-existing
  comments don't surface as new findings.

We focus on comments rather than code because:
1. Strings and identifiers are subject to other linters / semgrep rules.
2. Comments are where agents most commonly drop verbatim context (slack
   threads, customer emails, ticket links) when explaining "why" they made
   a change.
3. Comments inside source files survive into shipped artifacts — JS/TS
   builds especially.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from patterns import (
    Finding,
    find as find_in_text,
)


# Comment syntax for the languages we care about.
# `line` is the tuple of single-line comment markers (e.g. ("#",) for python).
# `block` is the tuple of (open, close) pairs (e.g. (("/*", "*/"),) for js).
@dataclass(frozen=True)
class _CommentSyntax:
    line: tuple[str, ...]
    block: tuple[tuple[str, str], ...]


_BY_EXTENSION: dict[str, _CommentSyntax] = {
    ".py": _CommentSyntax(line=("#",), block=(('"""', '"""'), ("'''", "'''"))),
    ".pyi": _CommentSyntax(line=("#",), block=(('"""', '"""'),)),
    ".js": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".jsx": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".ts": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".tsx": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".mjs": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".cjs": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".go": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".rs": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".java": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".c": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".cpp": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".h": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".rb": _CommentSyntax(line=("#",), block=(("=begin", "=end"),)),
    ".sh": _CommentSyntax(line=("#",), block=()),
    ".bash": _CommentSyntax(line=("#",), block=()),
    ".yaml": _CommentSyntax(line=("#",), block=()),
    ".yml": _CommentSyntax(line=("#",), block=()),
    ".toml": _CommentSyntax(line=("#",), block=()),
    ".sql": _CommentSyntax(line=("--",), block=(("/*", "*/"),)),
    ".html": _CommentSyntax(line=(), block=(("<!--", "-->"),)),
    ".css": _CommentSyntax(line=(), block=(("/*", "*/"),)),
    ".scss": _CommentSyntax(line=("//",), block=(("/*", "*/"),)),
    ".md": _CommentSyntax(line=(), block=(("<!--", "-->"),)),
    ".mdx": _CommentSyntax(line=(), block=(("<!--", "-->"),)),
}


@dataclass(frozen=True)
class CommentHit:
    path: str
    line: int  # 1-indexed line number where the comment starts
    finding: Finding


def _comment_spans_for(path: Path | str, source: str) -> list[tuple[int, str]]:
    """Return `(line_no, comment_text)` for every comment in `source`.

    Naive but pragmatic: we scan line by line, tracking whether we're inside
    a block comment, and skip string literals only well enough to not
    catch obvious '#'-in-quotes false positives. The scanner exists to spot
    sensitive *content* — false positives that include code text are still
    fine because the pattern matchers are narrow.
    """
    ext = Path(path).suffix.lower()
    syntax = _BY_EXTENSION.get(ext)
    if syntax is None:
        return []

    line_markers = syntax.line
    block_pairs = syntax.block

    out: list[tuple[int, str]] = []
    in_block: tuple[str, str] | None = None
    block_buf: list[str] = []
    block_start_line = 0

    for lineno, line in enumerate(source.splitlines(), start=1):
        if in_block:
            close = in_block[1]
            idx = line.find(close)
            if idx == -1:
                block_buf.append(line)
                continue
            block_buf.append(line[:idx])
            out.append((block_start_line, "\n".join(block_buf)))
            block_buf = []
            in_block = None
            line = line[idx + len(close) :]

        # Inline / line-style comments — find the first occurrence outside
        # of a string literal. Quick-and-dirty: walk the line tracking
        # whether we're in a single/double-quoted string.
        for marker in line_markers:
            comment = _extract_line_comment(line, marker)
            if comment is not None:
                out.append((lineno, comment))
                line = line[: line.find(marker)]
                break

        for open_, close_ in block_pairs:
            idx = line.find(open_)
            if idx == -1:
                continue
            after_open = line[idx + len(open_) :]
            close_idx = after_open.find(close_)
            if close_idx != -1:
                out.append((lineno, after_open[:close_idx]))
                line = line[:idx] + after_open[close_idx + len(close_) :]
            else:
                in_block = (open_, close_)
                block_start_line = lineno
                block_buf = [after_open]
                break

    if in_block and block_buf:
        out.append((block_start_line, "\n".join(block_buf)))

    return out


_QUOTE_CHARS = ("'", '"', "`")


def _extract_line_comment(line: str, marker: str) -> str | None:
    """Return the portion of `line` after `marker`, ignoring markers inside strings."""
    in_quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_quote:
            if ch == "\\":
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
        elif ch in _QUOTE_CHARS:
            in_quote = ch
        elif line.startswith(marker, i):
            return line[i + len(marker) :]
        i += 1
    return None


def scan_text(path: str, source: str) -> list[CommentHit]:
    hits: list[CommentHit] = []
    for line_no, comment in _comment_spans_for(path, source):
        for f in find_in_text(comment):
            hits.append(CommentHit(path=path, line=line_no, finding=f))
    return hits


def scan_files(paths: list[str], *, root: Path | None = None) -> list[CommentHit]:
    """Read each file under `root` and return CommentHits for sensitive content."""
    base = root or Path.cwd()
    hits: list[CommentHit] = []
    for rel in paths:
        full = base / rel
        try:
            source = full.read_text(encoding="utf-8", errors="ignore")
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            continue
        hits.extend(scan_text(rel, source))
    return hits


# ── Diff-based scanning (pre-push fast path) ───────────────────────────


_DIFF_FILE_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_DIFF_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _parse_unified_diff(diff_text: str) -> list[tuple[str, list[tuple[int, str]]]]:
    """Parse a unified diff into `(path, [(line_no, added_line)])`.

    `line_no` is the post-image line number from the `+` side. We only emit
    `+`-prefixed lines (additions); context and deletions are filtered out.
    """
    out: list[tuple[str, list[tuple[int, str]]]] = []
    current_path: str | None = None
    current_lines: list[tuple[int, str]] = []
    plus_line = 0

    for raw in diff_text.splitlines():
        m = _DIFF_FILE_HEADER.match(raw)
        if m:
            if current_path is not None:
                out.append((current_path, current_lines))
            current_path = m.group(2)
            current_lines = []
            plus_line = 0
            continue
        if raw.startswith("+++ ") or raw.startswith("--- "):
            continue
        m = _DIFF_HUNK.match(raw)
        if m:
            plus_line = int(m.group(1))
            continue
        if not current_path:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            current_lines.append((plus_line, raw[1:]))
            plus_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        else:
            plus_line += 1

    if current_path is not None:
        out.append((current_path, current_lines))
    return out


def scan_diff_added_lines(diff_text: str) -> list[CommentHit]:
    """Scan only newly-added lines from a unified diff for sensitive content in comments.

    The pre-push hook uses this to avoid flagging comments that were already
    on master — only new content authored in this push gets reviewed. We
    reconstruct just the added lines per file, run the same comment
    extractor, and report findings.

    A trade-off: we don't have surrounding context for block-comment
    continuation across hunks. In practice the pattern matchers operate on
    individual lines so this rarely matters; we still pass the joined
    lines to the comment extractor so multi-line block comments inside a
    single hunk are handled.
    """
    hits: list[CommentHit] = []
    for path, lines in _parse_unified_diff(diff_text):
        if not lines:
            continue
        # Reconstruct the added text as a contiguous block. Line numbers
        # are preserved per-line so we report the actual destination line.
        # We feed the synthetic source through the language-specific
        # extractor so block comments group together.
        added_text = "\n".join(line for _, line in lines)
        for line_offset, comment in _comment_spans_for(path, added_text):
            actual_line = lines[line_offset - 1][0] if line_offset - 1 < len(lines) else line_offset
            for f in find_in_text(comment):
                hits.append(CommentHit(path=path, line=actual_line, finding=f))
    return hits


def format_hits_table(hits: list[CommentHit]) -> str:
    """Render hits as a human-readable table for terminal output."""
    if not hits:
        return ""
    lines = []
    for h in hits:
        snippet = h.finding.snippet.strip()
        if len(snippet) > 60:
            snippet = snippet[:57] + "..."
        lines.append(f"  {h.path}:{h.line}  [{h.finding.severity}/{h.finding.category}]  {snippet}")
    return "\n".join(lines)
