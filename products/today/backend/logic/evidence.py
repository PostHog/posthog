from collections.abc import Callable
from datetime import datetime, timedelta

from ..facade import contracts
from .formats import colon_duration_seconds
from .signal_previews import plays_recording, preview
from .signal_text import (
    SignalInput as SignalInput,
    cited_source,
    code_file,
    detail,
    github_file_url,
    headline,
    is_pull_request,
    meta,
    safe_http_url,
    slack_thread,
    text_of,
)

_SHOWN_EVIDENCE = 3
_PLAYER_LEAD_IN_SECONDS = 5
_SHORT_FINDING_CHARS = 240


def newest_first(signals: list[SignalInput]) -> list[SignalInput]:
    return sorted(signals, key=lambda signal: signal.timestamp, reverse=True)


def _evidence_item(signal: SignalInput) -> str:
    alert = text_of(signal.extra.get("alert_id")) if signal.source_product == "analytics" else None
    return f"analytics:alert:{alert}" if alert else f"{signal.source_product}:{signal.source_id}"


def distinct_evidence_count(signals: list[SignalInput]) -> int:
    return len({_evidence_item(signal) for signal in signals})


def _unique_by(signals: list[SignalInput], key: Callable[[SignalInput], str]) -> list[SignalInput]:
    seen: set[str] = set()
    unique = []
    for signal in signals:
        if key(signal) not in seen:
            seen.add(key(signal))
            unique.append(signal)
    return unique


def pick_evidence(signals: list[SignalInput], count: int = _SHOWN_EVIDENCE) -> list[SignalInput]:
    unique = _unique_by(newest_first(signals), _evidence_item)
    leads = _unique_by(unique, lambda signal: signal.source_product)
    rest = [signal for signal in unique if signal not in leads]
    return newest_first([*leads, *rest][:count])


def _offset_seconds(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return colon_duration_seconds(value) if isinstance(value, str) else None


def _offset_label(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{int(seconds - minutes * 60):02d}"


def _recording_start(extra: dict[str, object]) -> datetime | None:
    start = text_of(extra.get("recording_start_time")) or text_of(extra.get("session_start_time"))
    try:
        return datetime.fromisoformat(start) if start else None
    except ValueError:
        return None


def _recording(signal: SignalInput) -> contracts.RecordingTarget | None:
    session_id = text_of(signal.extra.get("session_id"))
    if not plays_recording(signal) or session_id is None:
        return None
    offset = _offset_seconds(signal.extra.get("start_time"))
    start = _recording_start(signal.extra)
    seek = max(offset - _PLAYER_LEAD_IN_SECONDS, 0) if offset is not None else None
    return contracts.RecordingTarget(
        session_id=session_id,
        start_at=start + timedelta(seconds=seek) if start and seek is not None else None,
        offset=_offset_label(offset) if offset is not None else None,
        seek_seconds=int(seek) if seek is not None else None,
    )


def _scout_link(signal: SignalInput) -> contracts.PageLink | None:
    thread = slack_thread(signal)
    if thread:
        return contracts.PageLink(url=thread, text="Open thread")
    file = code_file(signal)
    short_finding = len(signal.content) <= _SHORT_FINDING_CHARS
    return contracts.PageLink(url=github_file_url(file), text="Open file") if file and short_finding else None


def _github_link(signal: SignalInput) -> contracts.PageLink | None:
    url = safe_http_url(text_of(signal.extra.get("html_url")) or "")
    label = "Open pull request" if is_pull_request(signal) else "Open issue"
    return contracts.PageLink(url=url, text=label) if url else None


_EXTERNAL_LINKS: dict[str, Callable[[SignalInput], contracts.PageLink | None]] = {
    "signals_scout": _scout_link,
    "github": _github_link,
}


def _external_link(signal: SignalInput) -> contracts.PageLink | None:
    link = _EXTERNAL_LINKS.get(signal.source_product)
    return link(signal) if link else None


def signal_view(signal: SignalInput) -> contracts.SignalView:
    return contracts.SignalView(
        signal_id=signal.signal_id,
        source_product=signal.source_product,
        source_type=signal.source_type,
        source_id=signal.source_id,
        content=signal.content,
        timestamp=signal.timestamp,
        extra=signal.extra,
        headline=headline(signal),
        lead=detail(signal).lead,
        meta=meta(signal),
        cited=cited_source(signal),
        recording=_recording(signal),
        link=_external_link(signal),
        preview=preview(signal),
    )
