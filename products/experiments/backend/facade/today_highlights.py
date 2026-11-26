"""Experiments' sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_experiment_highlights, find_experiment_number, name_experiment_numbers

HIGHLIGHT_SOURCES = (
    HighlightSource(name="experiments", find=find_experiment_highlights, scopes=("experiment:read",)),
    HighlightSource(
        name="experiment_numbers",
        find=find_experiment_number,
        scopes=("experiment:read",),
        pulse_order=-1,
        number_names=name_experiment_numbers,
    ),
)
