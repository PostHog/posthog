import re
from typing import Literal, cast, get_args

from posthog.dataclasses import frozen

EditAction = Literal["replace_intro", "replace_section", "insert_after_section", "append"]
EDIT_ACTIONS: tuple[EditAction, ...] = get_args(EditAction)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FAQ_RE = re.compile(r"frequently asked questions|^faqs?$")


@frozen
class PageEdit:
    action: EditAction
    heading: str
    markdown: str

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "PageEdit | None":
        action = str(value.get("action", ""))
        if action not in EDIT_ACTIONS:
            return None
        return cls(
            action=cast(EditAction, action),
            heading=str(value.get("heading", "")),
            markdown=str(value.get("markdown", "")).strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return {"action": self.action, "heading": self.heading, "markdown": self.markdown}


@frozen
class AppliedEdits:
    markdown: str
    unplaced: tuple[str, ...]


def _heading(line: str) -> tuple[int, str] | None:
    match = _HEADING_RE.match(line)
    return (len(match.group(1)), match.group(2)) if match else None


def _normalize(heading: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", heading.lower()).split())


def page_headings(markdown: str) -> list[str]:
    return [parsed[1] for line in markdown.splitlines() if (parsed := _heading(line)) and parsed[0] >= 2]


def _section_end(lines: list[str], start: int, level: int) -> int:
    return next(
        (
            later
            for later in range(start + 1, len(lines))
            if (next_heading := _heading(lines[later])) and next_heading[0] <= level
        ),
        len(lines),
    )


def _find_section(lines: list[str], heading: str) -> tuple[int, int] | None:
    wanted = _normalize(heading)
    for index, line in enumerate(lines):
        parsed = _heading(line)
        if parsed is not None and _normalize(parsed[1]) == wanted:
            return index, _section_end(lines, index, parsed[0])
    return None


def _faq_start(lines: list[str]) -> int | None:
    return next(
        (
            index
            for index, line in enumerate(lines)
            if (parsed := _heading(line)) and parsed[0] == 2 and _FAQ_RE.search(_normalize(parsed[1]))
        ),
        None,
    )


def _block(markdown: str) -> list[str]:
    return ["", *markdown.splitlines(), ""]


def _append(lines: list[str], edit: PageEdit) -> list[str]:
    new_lines = edit.markdown.splitlines()
    first = _heading(new_lines[0]) if new_lines else None
    faq = _faq_start(lines)
    if first is not None and _FAQ_RE.search(_normalize(first[1])) and faq is not None:
        return [*lines[:faq], *_block(edit.markdown), *lines[_section_end(lines, faq, 2) :]]
    insert_at = faq if faq is not None else len(lines)
    return [*lines[:insert_at], *_block(edit.markdown), *lines[insert_at:]]


def _replace_intro(lines: list[str], edit: PageEdit) -> list[str]:
    h1 = next((index for index, line in enumerate(lines) if (parsed := _heading(line)) and parsed[0] == 1), -1)
    new_lines = edit.markdown.splitlines()
    replaces_title = bool(new_lines) and (parsed := _heading(new_lines[0])) is not None and parsed[0] == 1
    start = h1 if replaces_title and h1 >= 0 else h1 + 1
    end = next(
        (index for index in range(h1 + 1, len(lines)) if (parsed := _heading(lines[index])) and parsed[0] >= 2),
        len(lines),
    )
    return [*lines[:start], *_block(edit.markdown), *lines[end:]]


def apply_edits(original: str, edits: list[PageEdit]) -> AppliedEdits:
    lines = original.splitlines()
    unplaced: list[str] = []
    for edit in edits:
        if not edit.markdown:
            continue
        if edit.action == "replace_intro":
            lines = _replace_intro(lines, edit)
            continue
        if edit.action == "append":
            lines = _append(lines, edit)
            continue
        section = _find_section(lines, edit.heading)
        if section is None:
            unplaced.append(edit.heading)
            lines = _append(lines, edit)
            continue
        start, end = section
        if edit.action == "replace_section":
            replacement = (
                edit.markdown if _heading(edit.markdown.splitlines()[0]) else f"{lines[start]}\n\n{edit.markdown}"
            )
            lines = [*lines[:start], *_block(replacement), *lines[end:]]
        else:
            lines = [*lines[:end], *_block(edit.markdown), *lines[end:]]
    text = "\n".join(lines)
    return AppliedEdits(markdown=re.sub(r"\n{3,}", "\n\n", text).strip() + "\n", unplaced=tuple(unplaced))
