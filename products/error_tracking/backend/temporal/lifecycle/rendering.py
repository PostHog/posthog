from typing import cast

import tiktoken

from posthog.helpers.tiktoken_encoding import TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model

SIGNAL_MAX_TOKENS = 8000


def _as_dict(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _as_list(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _string(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _render_frame(value: object) -> str:
    frame = _as_dict(value)
    if frame is None:
        return ""

    resolved_name = frame.get("resolved_name")
    function = resolved_name if isinstance(resolved_name, str) else _string(frame.get("mangled_name"))
    source = frame.get("source")
    line = frame.get("line")
    column = frame.get("column")

    rendered = function
    if isinstance(source, str):
        rendered += f" in {source}"
    if isinstance(line, int):
        rendered += f" line {line}"
    if isinstance(column, int):
        rendered += f" column {column}"
    return f"{rendered}\n"


def _render_stacktrace_unbounded(event_properties: dict[str, object], truncate_frames: bool) -> str:
    rendered: list[str] = []
    for value in _as_list(event_properties.get("$exception_list")):
        exception = _as_dict(value)
        if exception is None:
            continue

        exception_type = _string(exception.get("type"), "Unknown")
        exception_value = _string(exception.get("value"))[:300]
        rendered.append(f"{exception_type}: {exception_value}\n")

        stacktrace = _as_dict(exception.get("stacktrace"))
        frames = _as_list(stacktrace.get("frames")) if stacktrace and stacktrace.get("type") == "resolved" else []
        if truncate_frames and len(frames) > 2:
            rendered.extend((_render_frame(frames[0]), "...\n", _render_frame(frames[-1])))
        else:
            rendered.extend(_render_frame(frame) for frame in frames)

    return "".join(rendered)


def decode_token_prefix(encoding: tiktoken.Encoding, tokens: list[int], max_tokens: int) -> str:
    prefix = tokens[:max_tokens]
    while prefix:
        try:
            return encoding.decode(prefix, errors="strict")
        except UnicodeDecodeError:
            prefix.pop()
    return ""


def render_stacktrace(event_properties: dict[str, object], max_tokens: int) -> str:
    encoding = get_tiktoken_encoding_for_model(TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL)
    rendered = _render_stacktrace_unbounded(event_properties, truncate_frames=False)
    tokens = encoding.encode(rendered, allowed_special="all")
    if len(tokens) <= max_tokens:
        return rendered

    rendered = _render_stacktrace_unbounded(event_properties, truncate_frames=True)
    tokens = encoding.encode(rendered, allowed_special="all")
    if len(tokens) <= max_tokens:
        return rendered

    return decode_token_prefix(encoding, tokens, max_tokens)
