from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_unwatched_saved_filters

HIGHLIGHT_SOURCES = (
    HighlightSource(
        name="replay_saved_filters",
        find=find_unwatched_saved_filters,
        scopes=("session_recording:read", "session_recording_playlist:read"),
    ),
)
