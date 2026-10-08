import re
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from posthog.dataclasses import frozen

from ..facade import contracts
from .prose import concise_text, paragraphs
from .signal_text import RECORDING_SOURCES, SignalInput, code_file, detail, github_file_url, slack_thread, text_of

_PREVIEW_CHARS = 240
_MAX_EXCEPTIONS = 4
_MAX_SIBLING_FILES = 2
_FENCED_BLOCK = re.compile(r"```[^\n]*\n([\s\S]*?)(?:```|\Z)")
_FRAME_LINE = re.compile(r"^(\S+) in (\S+) line (\d+)$")
_IN_APP_PATH = re.compile(r"^(?:posthog|products|ee|common|services|frontend)/")
_SECTION_LABEL = re.compile(r"^\*\*([^*\n]+?):\*\*\s*")
_BARE_FILE_NAME = re.compile(r"`([\w-]+\.[a-z]{1,5})`", re.IGNORECASE | re.ASCII)
_CHANNELS = {"slack": "Slack", "email": "Email", "widget": "Chat widget"}
_CONVERSATION_MESSAGE = re.compile(r"(?:C|T|AI): ")

SourcePreview = Callable[[SignalInput, contracts.SignalPreview], contracts.SignalPreview | None]


def _sentence_case(value: str) -> str:
    words = value.replace("_", " ").strip().lower()
    return words[:1].upper() + words[1:]


def _readable(signal: SignalInput, content: str) -> str:
    found = detail(replace(signal, content=content))
    return " ".join(part for part in (found.lead, found.rest) if part)


@frozen
class _Frame:
    function: str
    path: str
    line: str


@frozen
class _Exception:
    header: str
    frames: list[_Frame]


def exception_chain(content: str) -> list[contracts.PreviewLine]:
    fenced = _FENCED_BLOCK.search(content)
    trace = fenced.group(1) if fenced else ""
    exceptions: list[_Exception] = []
    for raw in trace.split("\n"):
        line = raw.strip()
        if not line:
            continue
        frame = _FRAME_LINE.match(line)
        if frame and exceptions:
            exceptions[-1].frames.append(_Frame(function=frame.group(1), path=frame.group(2), line=frame.group(3)))
        elif not frame:
            exceptions.append(_Exception(header=line, frames=[]))
    if not any(exception.frames for exception in exceptions):
        return []
    prose = _FENCED_BLOCK.sub("", content, count=1)
    lines: list[contracts.PreviewLine] = []
    for index, exception in enumerate(exceptions):
        if 0 < index < len(exceptions) - _MAX_EXCEPTIONS + 1:
            continue
        own = [frame for frame in exception.frames if _IN_APP_PATH.match(frame.path)]
        candidates = own or exception.frames
        shown = candidates[-1] if candidates else None
        header = exception.header
        if not (index == 0 and header in prose):
            lines.append(contracts.PreviewLine(text=header if index == 0 else f"Caused by {header}", quiet=False))
        if shown:
            lines.append(
                contracts.PreviewLine(text=f"  {shown.path.split('/')[-1]}:{shown.line}  {shown.function}", quiet=True)
            )
    return lines


def _pganalyze_query(signal: SignalInput) -> str | None:
    references = signal.extra.get("references")
    if not isinstance(references, list):
        return None
    query = next((item for item in references if isinstance(item, dict) and item.get("kind") == "Query"), None)
    return text_of(query.get("queryText")) if isinstance(query, dict) else None


def body_paragraph(content: str, label: str | None = None, has_title: bool = True) -> str | None:
    trimmed = content.strip()
    title_end = trimmed.find("\n") if has_title else -1
    body = paragraphs(trimmed[title_end + 1 :]) if title_end >= 0 or not has_title else []

    def label_of(paragraph: str) -> str | None:
        match = _SECTION_LABEL.match(paragraph)
        return match.group(1).lower() if match else None

    labelled = next((paragraph for paragraph in body if label and label_of(paragraph) == label.lower()), None)
    chosen = labelled or next((paragraph for paragraph in body if not _SECTION_LABEL.match(paragraph)), None)
    return (_SECTION_LABEL.sub("", chosen, count=1).strip() or None) if chosen else None


def _github_state(extra: dict[str, Any]) -> str | None:
    if isinstance(extra.get("merged_at"), str):
        return "Merged"
    open_state = text_of(extra.get("state"))
    return _sentence_case(open_state) if open_state else None


def _github_facts(extra: dict[str, Any]) -> list[str]:
    state = _github_state(extra)
    author = text_of(extra.get("author_login"))
    raw_labels = extra.get("labels")
    labels = [
        text_of(label.get("name")) if isinstance(label, dict) else text_of(label)
        for label in (raw_labels if isinstance(raw_labels, list) else [])
    ]
    return [fact for fact in (state, f"by {author}" if author else None, *labels) if fact is not None]


def _ticket_facts(extra: dict[str, Any]) -> list[str]:
    channel = text_of(extra.get("channel_source"))
    priority = text_of(extra.get("priority"))
    status = text_of(extra.get("status"))
    return [
        fact
        for fact in (
            _CHANNELS.get(channel, _sentence_case(channel)) if channel else None,
            f"{_sentence_case(priority)} priority" if priority else None,
            _sentence_case(status) if status else None,
        )
        if fact is not None
    ]


def _anomaly_facts(extra: dict[str, Any]) -> list[str]:
    verdict = text_of(extra.get("verdict"))
    return [_sentence_case(verdict)] if verdict else []


def _finding_rest(signal: SignalInput) -> str:
    lead = detail(signal).lead
    lines = signal.content.split("\n")
    for index, line in enumerate(lines):
        found = detail(replace(signal, content=line))
        if lead and found.lead == lead:
            later = detail(replace(signal, content="\n".join(lines[index + 1 :])))
            return " ".join(part for part in (found.rest, later.lead, later.rest) if part)
    return ""


def code_sibling_files(file: contracts.CodeFile, content: str) -> list[contracts.CodeFile]:
    folder = file.path[: file.path.rfind("/") + 1]
    own = file.path[len(folder) :]
    names = [match.group(1) for match in _BARE_FILE_NAME.finditer(content) if match.group(1) != own]
    unique = list(dict.fromkeys(names))[:_MAX_SIBLING_FILES]
    return [contracts.CodeFile(repo=file.repo, path=f"{folder}{name}") for name in unique]


def _scout_preview(signal: SignalInput, preview: contracts.SignalPreview) -> contracts.SignalPreview:
    file = code_file(signal)
    if file:
        return replace(
            preview,
            hint="Show the code",
            code=[file, *code_sibling_files(file, signal.content)],
            facts=[fact for fact in preview.facts if fact != file.path.split("/")[-1]],
            link=contracts.PageLink(url=github_file_url(file), text="Open on GitHub"),
        )
    thread = slack_thread(signal)
    if thread:
        return replace(
            preview, hint="Show what the thread says", link=contracts.PageLink(url=thread, text="Open in Slack")
        )
    return preview


def _stack_trace_preview(signal: SignalInput, preview: contracts.SignalPreview) -> contracts.SignalPreview | None:
    block = exception_chain(signal.content)
    return replace(preview, hint="Show the stack trace", block=block, text="") if block else None


def _query_preview(signal: SignalInput, preview: contracts.SignalPreview) -> contracts.SignalPreview | None:
    query = _pganalyze_query(signal)
    if not query:
        return None
    return replace(preview, hint="Show the query", block=[contracts.PreviewLine(text=query, quiet=False)])


def _description_preview(signal: SignalInput, preview: contracts.SignalPreview) -> contracts.SignalPreview | None:
    body = body_paragraph(signal.content)
    if not body:
        return None
    return replace(
        preview,
        hint="Show the description",
        text=concise_text(_readable(signal, body), _PREVIEW_CHARS),
        facts=[*preview.facts, *_github_facts(signal.extra)],
        link_label="Open on GitHub",
    )


def _ticket_preview(signal: SignalInput, preview: contracts.SignalPreview) -> contracts.SignalPreview | None:
    body = body_paragraph(signal.content, "Issue", has_title=not _CONVERSATION_MESSAGE.match(signal.content.strip()))
    if not body:
        return None
    return replace(
        preview,
        hint="Show the ticket",
        text=concise_text(_readable(signal, body), _PREVIEW_CHARS),
        facts=[*preview.facts, *_ticket_facts(signal.extra)],
    )


def _finding_preview(signal: SignalInput, preview: contracts.SignalPreview) -> contracts.SignalPreview | None:
    rest = _finding_rest(signal)
    if not rest:
        return None
    return replace(
        preview,
        hint="Show the finding",
        text=concise_text(rest, _PREVIEW_CHARS),
        facts=[*preview.facts, *_anomaly_facts(signal.extra)],
    )


_SOURCE_PREVIEWS: dict[str, SourcePreview] = {
    "signals_scout": _scout_preview,
    "error_tracking": _stack_trace_preview,
    "pganalyze": _query_preview,
    "github": _description_preview,
    "conversations": _ticket_preview,
    "zendesk": _ticket_preview,
    "analytics": _finding_preview,
}


def plays_recording(signal: SignalInput) -> bool:
    return signal.source_product in RECORDING_SOURCES and text_of(signal.extra.get("session_id")) is not None


def preview(signal: SignalInput) -> contracts.SignalPreview | None:
    if plays_recording(signal):
        return None
    found = detail(signal)
    base = contracts.SignalPreview(
        hint="Read in full", code=[], block=[], text=found.rest, facts=found.facts, link=None, link_label=None
    )
    source_preview = _SOURCE_PREVIEWS.get(signal.source_product)
    return source_preview(signal, base) if source_preview else base
