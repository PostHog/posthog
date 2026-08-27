import ipaddress
from typing import cast
from urllib.parse import urlparse

import tiktoken

from posthog.dataclasses import frozen
from posthog.helpers.tiktoken_encoding import TEXT_EMBEDDING_3_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model

SIGNAL_MAX_TOKENS = 8000

_DEV_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


@frozen
class Origin:
    host: str | None
    is_dev_host: bool
    lib: str | None
    lib_version: str | None


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


def _is_dev_hostname(hostname: str) -> bool:
    hostname = hostname.lower()
    if hostname in _DEV_HOSTNAMES:
        return True
    if hostname.endswith(".local") or hostname.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _authority(value: str, *, is_url: bool) -> tuple[str | None, int | None]:
    # Parse a URL or a bare host[:port] into hostname and port. A malformed
    # authority (an unbalanced bracket, an out-of-range port) parses to nothing
    # instead of raising, so one crafted event can't abort the lifecycle signal.
    try:
        parsed = urlparse(value if is_url else f"//{value}")
        return parsed.hostname, parsed.port
    except ValueError:
        return None, None


def _format_host(hostname: str, port: int | None) -> str:
    display = f"[{hostname}]" if ":" in hostname else hostname
    return f"{display}:{port}" if port is not None else display


def parse_origin(event_properties: dict[str, object]) -> Origin:
    current_url = _string(event_properties.get("$current_url"))
    hostname, port = _authority(current_url, is_url=True) if current_url else (None, None)
    if hostname is None:
        # $host is a bare authority. Rebuild host:port from the parsed hostname, so any
        # userinfo, path, or query in a non-browser-supplied value never reaches the origin.
        hostname, port = _authority(_string(event_properties.get("$host")), is_url=False)
    return Origin(
        host=_format_host(hostname, port) if hostname else None,
        is_dev_host=_is_dev_hostname(hostname) if hostname else False,
        lib=_string(event_properties.get("$lib")) or None,
        lib_version=_string(event_properties.get("$lib_version")) or None,
    )


def render_origin(origin: Origin) -> str:
    parts: list[str] = []
    if origin.host:
        host_part = f"host {origin.host}"
        if origin.is_dev_host:
            host_part += " (local development host)"
        parts.append(host_part)
    if origin.lib:
        lib_part = f"lib {origin.lib}"
        if origin.lib_version:
            lib_part += f" {origin.lib_version}"
        parts.append(lib_part)
    if not parts:
        return ""
    return "Origin: " + ", ".join(parts) + "\n"


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
