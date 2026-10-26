"""Today's own sources for the "For you today" list: the pulse and the home dashboard. Today finds this module by name."""

from ..logic.today_highlights import home, key_metrics, routine

HIGHLIGHT_SOURCES = (home.SOURCE, key_metrics.SOURCE, routine.SOURCE)
