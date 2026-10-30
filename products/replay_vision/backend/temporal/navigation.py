import math
from collections.abc import Sequence

from pydantic import BaseModel, Field

from posthog.temporal.session_replay.rasterize_recording.types import NavigationChange

# The timeline stays a skim-able digest: bounded per URL, per entry count, and in total URL characters, so a bouncy
# session with long URLs can't bloat the cached prompt.
_MAX_NAVIGATION_ENTRIES = 100
_MAX_NAVIGATION_URL_LEN = 200
_MAX_NAVIGATION_TOTAL_URL_CHARS = 10000


class NavigationEntry(BaseModel, frozen=True):
    """One change of the page or tab on screen, as the prompt's navigation timeline shows it."""

    vid_t: int = Field(ge=0)
    # The last video second the page is on screen, or None when it stays until the video ends.
    end_t: int | None = None
    # The window number the frame footer shows, `WINDOW: <n> of ...`.
    tab: int
    url: str
    # The first entry for a tab other than the one the recording starts in (a tab or window opening).
    new_window: bool = False


def navigation_timeline(changes: Sequence[NavigationChange]) -> tuple[list[NavigationEntry], int]:
    entries: list[NavigationEntry] = []
    ends: list[int | None] = []
    seen_tabs: set[int] = set()
    last_change: NavigationChange | None = None
    for change in changes:
        # Every change ends the visit on screen, including one to a URL the gate drops.
        if ends and ends[-1] is None:
            ends[-1] = max(entries[-1].vid_t, _first_whole_second(change.video_s) - 1)
        if not _is_navigable_url(change.url):
            continue
        # A URL the gate drops can sit between two sightings of the same page, which would repeat it.
        if last_change and last_change.window_number == change.window_number and last_change.url == change.url:
            ends[-1] = None
            continue
        last_change = change
        url = change.url if len(change.url) <= _MAX_NAVIGATION_URL_LEN else change.url[:_MAX_NAVIGATION_URL_LEN] + "…"
        new_window = bool(seen_tabs) and change.window_number not in seen_tabs
        seen_tabs.add(change.window_number)
        entries.append(
            NavigationEntry(
                vid_t=_first_whole_second(change.video_s), tab=change.window_number, url=url, new_window=new_window
            )
        )
        ends.append(None)
    entries = [entry.model_copy(update={"end_t": end}) for entry, end in zip(entries, ends)]

    # Over budget, the shortest visits go first, so late long visits outlast early bounces. Tab openings stay, since
    # they mark hand-offs, and a visit that lasts to the end has no known length.
    kept: set[int] = set()
    url_chars = 0
    for i in sorted(range(len(entries)), key=lambda i: (not entries[i].new_window, -_visit_length(entries[i]), i)):
        if len(kept) >= _MAX_NAVIGATION_ENTRIES:
            break
        if url_chars + len(entries[i].url) > _MAX_NAVIGATION_TOTAL_URL_CHARS:
            continue
        kept.add(i)
        url_chars += len(entries[i].url)
    return [entries[i] for i in sorted(kept)], len(entries) - len(kept)


def _visit_length(entry: NavigationEntry) -> float:
    return math.inf if entry.end_t is None else entry.end_t - entry.vid_t + 1


def _first_whole_second(video_s: float) -> int:
    # A citation seeks to the whole second it names, so a page that appears mid-second is on screen from the next one.
    return math.ceil(video_s - 1e-6)


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
