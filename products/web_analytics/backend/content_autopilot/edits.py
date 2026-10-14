import re
from typing import Literal, cast, get_args

from posthog.dataclasses import frozen

EditAction = Literal["replace_intro", "replace_section", "insert_after_section", "append"]
EDIT_ACTIONS: tuple[EditAction, ...] = get_args(EditAction)

_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}(?=[^`]*$)|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
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


@frozen
class _Section:
    start: int
    end: int


def _heading(line: str) -> tuple[int, str] | None:
    match = _HEADING_RE.match(line)
    return (len(match.group(1)), match.group(2) or "") if match else None


def _normalize(heading: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", heading.lower()).split())


def _headings(lines: list[str]) -> dict[int, tuple[int, str]]:
    headings: dict[int, tuple[int, str]] = {}
    fence: str | None = None
    for index, line in enumerate(lines):
        if fence is not None:
            closer = _FENCE_CLOSE_RE.match(line)
            if closer and closer.group(1)[0] == fence[0] and len(closer.group(1)) >= len(fence):
                fence = None
            continue
        if opener := _FENCE_OPEN_RE.match(line):
            fence = opener.group(1)
            continue
        if parsed := _heading(line):
            headings[index] = parsed
    return headings


def page_headings(markdown: str) -> list[str]:
    return [parsed[1] for parsed in _headings(markdown.splitlines()).values() if parsed[0] >= 2]


def _section_end(lines: list[str], start: int, level: int) -> int:
    return next(
        (index for index, parsed in _headings(lines).items() if index > start and parsed[0] <= level),
        len(lines),
    )


def _find_section(lines: list[str], heading: str) -> _Section | None:
    wanted = _normalize(heading)
    for index, parsed in _headings(lines).items():
        if _normalize(parsed[1]) == wanted:
            return _Section(start=index, end=_section_end(lines, index, parsed[0]))
    return None


def _faq_start(lines: list[str]) -> int | None:
    return next(
        (
            index
            for index, parsed in _headings(lines).items()
            if parsed[0] == 2 and _FAQ_RE.search(_normalize(parsed[1]))
        ),
        None,
    )


def _splice(lines: list[str], start: int, end: int, markdown: str) -> list[str]:
    before = lines[:start]
    after = lines[end:]
    while before and not before[-1].strip():
        before.pop()
    while after and not after[0].strip():
        after.pop(0)
    return [*before, *([""] if before else []), *markdown.splitlines(), *([""] if after else []), *after]


def _append(lines: list[str], edit: PageEdit) -> list[str]:
    new_lines = edit.markdown.splitlines()
    first = _heading(new_lines[0]) if new_lines else None
    faq = _faq_start(lines)
    if first is not None and _FAQ_RE.search(_normalize(first[1])) and faq is not None:
        return _splice(lines, faq, _section_end(lines, faq, 2), edit.markdown)
    insert_at = faq if faq is not None else len(lines)
    return _splice(lines, insert_at, insert_at, edit.markdown)


def _replace_intro(lines: list[str], edit: PageEdit) -> list[str]:
    headings = _headings(lines)
    h1 = next((index for index, parsed in headings.items() if parsed[0] == 1), -1)
    new_lines = edit.markdown.splitlines()
    replaces_title = bool(new_lines) and (parsed := _heading(new_lines[0])) is not None and parsed[0] == 1
    start = h1 if replaces_title and h1 >= 0 else h1 + 1
    end = next((index for index, parsed in headings.items() if index > h1 and parsed[0] >= 2), len(lines))
    return _splice(lines, start, end, edit.markdown)


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
        if edit.action == "replace_section":
            replacement = (
                edit.markdown
                if _heading(edit.markdown.splitlines()[0])
                else f"{lines[section.start]}\n\n{edit.markdown}"
            )
            lines = _splice(lines, section.start, section.end, replacement)
        else:
            lines = _splice(lines, section.end, section.end, edit.markdown)
    return AppliedEdits(markdown="\n".join(lines).strip("\n") + "\n", unplaced=tuple(unplaced))
