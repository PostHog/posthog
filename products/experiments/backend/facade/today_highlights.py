"""Experiments' sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_experiment_highlights

HIGHLIGHT_SOURCES = (HighlightSource(name="experiments", find=find_experiment_highlights, scopes=("experiment:read",)),)
