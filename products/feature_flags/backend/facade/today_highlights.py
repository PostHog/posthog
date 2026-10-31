"""Feature flags' sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_flag_highlights

HIGHLIGHT_SOURCES = (HighlightSource(name="flags", find=find_flag_highlights, scopes=("feature_flag:read",)),)
