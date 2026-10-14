from collections.abc import Sequence
from typing import Any

from posthog.temporal.session_replay.rasterize_recording.types import NavigationChange

from products.replay_vision.backend.temporal.types import NavigationEntry

# The timeline stays a skim-able digest: bounded per URL, per entry count, and in total URL characters, so a bouncy
# session with long URLs can't bloat the cached prompt.
_MAX_NAVIGATION_ENTRIES = 50
_MAX_NAVIGATION_URL_LEN = 200
_MAX_NAVIGATION_TOTAL_URL_CHARS = 5000
_WINDOW_PREFIX = "window"


def navigation_from_export_context(export_context: dict[str, Any] | None) -> list[NavigationChange]:
    return [NavigationChange.model_validate(change) for change in (export_context or {}).get("navigation") or []]


def navigation_timeline(
    changes: Sequence[NavigationChange], window_mapping: dict[str, str]
) -> tuple[list[NavigationEntry], int]:
    # Tokens come from the event lookups so one tab reads the same in both; a tab no event names gets the next one.
    tokens = {window_id: token for token, window_id in window_mapping.items()}
    entries: list[NavigationEntry] = []
    seen_windows: set[str] = set()
    for change in changes:
        if not _is_navigable_url(change.url):
            continue
        token = tokens.setdefault(change.window_id, f"{_WINDOW_PREFIX}_{len(tokens) + 1}")
        url = change.url if len(change.url) <= _MAX_NAVIGATION_URL_LEN else change.url[:_MAX_NAVIGATION_URL_LEN] + "…"
        # A URL the gate drops can sit between two sightings of the same page, which would repeat it.
        if entries and entries[-1].window == token and entries[-1].url == url:
            continue
        new_window = bool(seen_windows) and token not in seen_windows
        seen_windows.add(token)
        entries.append(NavigationEntry(vid_t=int(change.video_s), window=token, url=url, new_window=new_window))

    kept: list[NavigationEntry] = []
    url_chars = 0
    for entry in entries:
        if len(kept) >= _MAX_NAVIGATION_ENTRIES or url_chars + len(entry.url) > _MAX_NAVIGATION_TOTAL_URL_CHARS:
            break
        kept.append(entry)
        url_chars += len(entry.url)
    return kept, len(entries) - len(kept)


def _is_navigable_url(url: str) -> bool:
    """Gate for the prompt timeline. The URL comes from the recording, which the client controls, and lands in the
    trusted preamble, so only values shaped like real web URLs get in: http scheme, printable, no whitespace, and no
    backtick (a raw backtick would escape the prompt's inline-code fencing, and real URLs percent-encode it).
    Anything else is dropped rather than escaped."""
    return (
        url.startswith(("http://", "https://"))
        and url.isprintable()
        and "`" not in url
        and not any(c.isspace() for c in url)
    )
