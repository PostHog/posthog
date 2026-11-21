"""Wizard's sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_unconnected_sources

HIGHLIGHT_SOURCES = (
    HighlightSource(
        name="wizard_unconnected_sources",
        find=find_unconnected_sources,
        scopes=("wizard_session:read", "external_data_source:read"),
    ),
)
