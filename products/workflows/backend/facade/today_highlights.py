"""Workflows' sources for the "For you today" list. Today finds this module by name."""

from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights.health import find_workflow_health
from ..today_highlights.ideas import find_workflow_ideas

HIGHLIGHT_SOURCES = (
    HighlightSource(name="workflows", find=find_workflow_health, scopes=("hog_flow:read",)),
    HighlightSource(name="workflow_ideas", find=find_workflow_ideas, scopes=("hog_flow:read",)),
)
