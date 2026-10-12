import re

from .formats import replace_iso_dates
from .report_text import MARKDOWN, MONTHS, readable_date, rendered_text
from .sentences import split_markdown_sentences

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(*`])")
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z“\"(])")
_MIN_SENTENCE_CHARS = 40
_MONTH_DAY = re.compile(r"(?<=\bon )(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b", re.ASCII)
_BARE_INTEGER = re.compile(r"(?<![\w#.,/:-])(?:\d{5,7}|(?!19|20)\d{4}(?= [a-z]))(?![\w/:-]|[.,]\d)", re.ASCII)
_CODE_BLOCK = re.compile(r"```[\s\S]*?(?:```|\Z)")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_ENDS = (".", "!", "?", ":")
_PLAIN_LINE_STEPS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^C:\s*"), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"(?:slack (?:reply|thread|message)|thread|link):\s*https?://\S+", re.IGNORECASE), ""),
    (re.compile(r"\s*\(\s*https?://[^\s)]+\s*\)"), ""),
    (re.compile(r"https?://\S+"), ""),
]
_CODE_SPAN = re.compile(r"`([^`]+)`")
_MARKERS = re.compile(r"[`*]")
_ESCAPED = re.compile(r"\\([.#()\[\]_*-])")
_WHITESPACE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,;:])")


def split_prose(line: str) -> list[str]:
    return _SENTENCE_BREAK.split(line)


def _quoted_code(match: re.Match[str]) -> str:
    code = match.group(1)
    return f"“{code}”" if re.search(r"\s", code) else code


def plain_line(line: str) -> str:
    text = line
    for pattern, replacement in _PLAIN_LINE_STEPS:
        text = pattern.sub(replacement, text)
    text = _CODE_SPAN.sub(_quoted_code, text)
    text = _ESCAPED.sub(r"\1", _MARKERS.sub("", text))
    return _SPACE_BEFORE_PUNCTUATION.sub(r"\1", _WHITESPACE.sub(" ", text)).strip()


def _inside_quote(text: str) -> bool:
    opened = text.count("“") - text.count("”")
    return opened > 0 or text.count('"') % 2 == 1


def first_sentence(text: str) -> str:
    for match in _SENTENCE_END.finditer(text):
        end = match.start() + 1
        if end >= _MIN_SENTENCE_CHARS and not _inside_quote(text[:end]):
            return text[:end]
    return text


def _month_day(match: re.Match[str]) -> str:
    return f"{int(match.group(2))} {MONTHS[int(match.group(1)) - 1]}"


def readable_excerpt(text: str) -> str:
    dated = _MONTH_DAY.sub(_month_day, replace_iso_dates(text, readable_date))
    return _BARE_INTEGER.sub(lambda match: f"{int(match.group(0)):,}", dated)


def without_code_blocks(text: str) -> str:
    return _CODE_BLOCK.sub("\n", text)


def paragraphs(markdown: str) -> list[str]:
    return [paragraph.strip() for paragraph in _PARAGRAPH_BREAK.split(markdown) if paragraph.strip()]


def block_lines(markdown: str) -> list[str]:
    inline_blocks = [token.content for token in MARKDOWN.parse(markdown) if token.type == "inline"]
    return [line.strip() for block in inline_blocks for line in block.split("\n") if line.strip()]


def _balanced(text: str, marker: str) -> str:
    return f"{text}{marker}" if text.count(marker) % 2 == 1 else text


def concise_text(markdown: str | None, max_chars: int) -> str:
    lines = [line if line.endswith(_SENTENCE_ENDS) else f"{line}." for line in block_lines(markdown or "")]
    pieces = [sentence.strip() for line in lines for _, sentence in split_markdown_sentences(line) if sentence.strip()]
    text = ""
    for piece in pieces:
        candidate = f"{text} {piece}" if text else piece
        if text and len(rendered_text(candidate)) > max_chars:
            break
        text = candidate
    return _balanced(_balanced(text, "**"), "`")
