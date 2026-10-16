"""Product analytics' sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights.home import find_home
from ..today_highlights.routine import find_routine

HIGHLIGHT_SOURCES = (
    HighlightSource(name="home", find=find_home, scopes=("dashboard:read", "insight:read")),
    HighlightSource(name="routine", find=find_routine, scopes=("insight:read",), pulse_order=1),
)
