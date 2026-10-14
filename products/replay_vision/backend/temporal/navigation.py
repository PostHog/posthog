from collections.abc import Sequence

from pydantic import BaseModel, Field

from posthog.temporal.session_replay.rasterize_recording.types import NavigationChange

# The timeline stays a skim-able digest: bounded per URL, per entry count, and in total URL characters, so a bouncy
# session with long URLs can't bloat the cached prompt.
_MAX_NAVIGATION_ENTRIES = 50
_MAX_NAVIGATION_URL_LEN = 200
_MAX_NAVIGATION_TOTAL_URL_CHARS = 5000


class NavigationEntry(BaseModel, frozen=True):
    """One change of the page or tab on screen, as the prompt's navigation timeline shows it."""

    vid_t: int = Field(ge=0)
    # The window number the frame footer shows, `WINDOW: <n> of ...`.
    tab: int
    url: str
    # The first entry for a tab other than the one the recording starts in (a tab or window opening).
    new_window: bool = False


def navigation_timeline(changes: Sequence[NavigationChange]) -> tuple[list[NavigationEntry], int]:
    entries: list[NavigationEntry] = []
    seen_tabs: set[int] = set()
    for change in changes:
        if not _is_navigable_url(change.url):
            continue
        url = change.url if len(change.url) <= _MAX_NAVIGATION_URL_LEN else change.url[:_MAX_NAVIGATION_URL_LEN] + "…"
        # A URL the gate drops can sit between two sightings of the same page, which would repeat it.
        if entries and entries[-1].tab == change.window_number and entries[-1].url == url:
            continue
        new_window = bool(seen_tabs) and change.window_number not in seen_tabs
        seen_tabs.add(change.window_number)
        entries.append(
            NavigationEntry(vid_t=int(change.video_s), tab=change.window_number, url=url, new_window=new_window)
        )

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
