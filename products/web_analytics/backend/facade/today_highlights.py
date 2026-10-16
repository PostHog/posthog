"""Web analytics' sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_rage_page

HIGHLIGHT_SOURCES = (HighlightSource(name="rage", find=find_rage_page),)
