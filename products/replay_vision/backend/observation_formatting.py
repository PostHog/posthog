import re
from typing import TYPE_CHECKING, Any

from products.replay_vision.backend.models.replay_scanner import ScannerType

if TYPE_CHECKING:
    from products.replay_vision.backend.models.replay_observation import ReplayObservation

EVENT_ID_CITATION_RE = re.compile(r"\(event_id [0-9a-f]{16}\)", re.IGNORECASE)

SEARCH_SNIPPET_LIMIT = 600

_FENCE_RE = re.compile(r"^ {0,3}(?:```|~~~)")
_RULE_RE = re.compile(r"^ {0,3}(?:[-*_]\s*){3,}$")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}\s+")
_QUOTE_RE = re.compile(r"^ {0,3}>\s?")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_LINK_DEFINITION_RE = re.compile(r"^ {0,3}\[[^\]]+\]:\s*\S+(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*$")
_REFERENCE_RE = re.compile(r"!?\[([^\]]*)\]\[[^\]]*\]")
_CODE_SPAN_RE = re.compile(r"`+([^`]*)`+")
_STRONG_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_EMPHASIS_RE = re.compile(r"(?<![\w*_])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*_])")
_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>~|])")
_SENTENCE_ENDINGS = ".!?:;,"


def flatten_markdown(text: str) -> str:
    """Markdown-bearing model text as plain prose, keeping the line structure.

    Scanner reasoning can carry a bold lead-in, a heading, or bullets. Every consumer outside the UI reads
    it as prose, where the syntax is noise at best (`**` and `##` inside a search snippet) and a forged list
    row at worst. Flattening here rather than at each consumer keeps the stored field the one canonical
    copy. `plain_snippet` is what folds the result onto a single line.

    The regexes above read a line the way a markdown parser does: block markers only at the start of a
    line and only space-indented, inline markers anywhere. Three carry a reason worth knowing:
    `_LINK_DEFINITION_RE` has to match a whole line, or it eats a sentence that merely opens the same way
    ("[Save]: clicked twice before it took"); bare `[text]` is deliberately left alone, being far more
    often a real bracket in prose than a shortcut reference; and `_EMPHASIS_RE`'s lookarounds keep
    `snake_case` and `2 * 3 * 4` intact. The frontend's `flattenMarkdownToLine`
    (products/replay_vision/frontend/utils/markdown.ts) is the same table and has to stay in step, or a
    snippet flattens differently in a search result and on the seekbar.
    """
    lines: list[str] = []
    for raw in text.split("\n"):
        if _FENCE_RE.match(raw) or _RULE_RE.match(raw) or _LINK_DEFINITION_RE.match(raw):
            continue
        line = _BULLET_RE.sub("", _QUOTE_RE.sub("", _HEADING_RE.sub("", raw)))
        line = _IMAGE_RE.sub(r"\1", line)
        line = _LINK_RE.sub(r"\1", line)
        line = _REFERENCE_RE.sub(r"\1", line)
        line = _CODE_SPAN_RE.sub(r"\1", line)
        line = _STRONG_RE.sub(r"\2", line)
        line = _STRIKE_RE.sub(r"\1", line)
        line = _EMPHASIS_RE.sub(r"\2", line)
        lines.append(_ESCAPE_RE.sub(r"\1", line).rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def plain_snippet(text: str, *, limit: int | None = SEARCH_SNIPPET_LIMIT) -> str:
    """One line of readable plain text from a model's free-text field.

    The single line is a safety property, not tidiness. These snippets go into markdown someone else reads
    as structure — the search-result bullet list inside a Max tool's untrusted-data fence — where a newline
    lets recording-derived text forge a row or a header. Flattening runs first so a markdown bullet cannot
    survive as a literal `-` at the start of the folded line either. Blocks are joined with a sentence
    break so a flattened list still reads as prose rather than one run-on clause.
    """
    flat = flatten_markdown(EVENT_ID_CITATION_RE.sub("", text))
    out = ""
    for block in (b for line in flat.split("\n") if (b := " ".join(line.split()))):
        if out:
            out += " " if out[-1] in _SENTENCE_ENDINGS else ". "
        out += block
    return out if limit is None else out[:limit]


def read_output(obs: "ReplayObservation") -> dict[str, Any] | None:
    scanner_result = obs.scanner_result if isinstance(obs.scanner_result, dict) else None
    output = scanner_result.get("model_output") if scanner_result is not None else None
    return output if isinstance(output, dict) else None


def describe_output(output: dict[str, Any]) -> str | None:
    """Short type-specific descriptor (verdict / score / tags / title) prepended to each result line."""
    scanner_type = output.get("scanner_type")
    if scanner_type == ScannerType.MONITOR and output.get("verdict") is not None:
        return f"verdict={output['verdict']}"
    if scanner_type == ScannerType.SCORER and output.get("score") is not None:
        label = output.get("label")
        return f"score={output['score']}{f' ({label})' if label else ''}"
    if scanner_type == ScannerType.CLASSIFIER:
        tags = [*(output.get("tags") or []), *(output.get("tags_freeform") or [])]
        return f"tags={', '.join(str(t) for t in tags)}" if tags else None
    if scanner_type == ScannerType.SUMMARIZER:
        title = output.get("title")
        return str(title) if isinstance(title, str) and title.strip() else None
    return None


def explanation_text(output: dict[str, Any]) -> str:
    """The free text a scanner wrote about the session: monitors, scorers and classifiers reason, summarizers
    summarize. Event-id citations are for the UI, so they are stripped here, and any markdown the model wrote
    is flattened: every caller reads this as one line of prose."""
    explanation = output.get("reasoning") or output.get("summary")
    if not isinstance(explanation, str):
        return ""
    return plain_snippet(explanation, limit=None)


def format_line(obs: "ReplayObservation", output: dict[str, Any], *, show_scanner: bool) -> str:
    descriptor = describe_output(output)
    clean = explanation_text(output)[:SEARCH_SNIPPET_LIMIT]

    prefix = f"{obs.created_at:%Y-%m-%d}"
    session = str(obs.session_id)
    # `scanner_name` is annotated by the search hydration so no scanner row is joined; fall back to the relation.
    scanner_name = getattr(obs, "scanner_name", None) or (obs.scanner.name if show_scanner and obs.scanner else "")
    scanner_part = f" {scanner_name}" if show_scanner and scanner_name else ""
    descriptor_part = f" [{descriptor}]" if descriptor else ""
    return f"- (session {session}, {prefix}){scanner_part}{descriptor_part} {clean}".rstrip()
