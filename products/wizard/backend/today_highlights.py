from urllib.parse import urlencode

from products.today.backend.facade.contracts import HighlightCandidate, HighlightContext, HighlightFindings
from products.today.backend.facade.enums import HighlightLabel
from products.warehouse_sources.backend.facade.api import list_sources
from products.wizard.backend.logic.scans import list_detected_warehouse_sources
from products.wizard.backend.tool_catalog.catalog import tool_label

ONE_TITLE = "Connect {source}, found in your codebase"
ONE_DETAIL = "Sync its data into PostHog to query it next to your product data."
MANY_TITLE = "Connect {count} data sources found in your codebase"
MANY_DETAIL = "{names}. Sync their data into PostHog to query it next to your product data."
NEW_SOURCE_URL = "/data-warehouse/new-source"
LISTED_NAMES = 3


def _names(labels: list[str]) -> str:
    if len(labels) > LISTED_NAMES:
        return f"{', '.join(labels[:LISTED_NAMES])} and {len(labels) - LISTED_NAMES} more"
    return labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} and {labels[-1]}"


def find_unconnected_sources(context: HighlightContext) -> HighlightFindings:
    connected = {str(source.source_type) for source in list_sources(context.team.id)}
    source_types = [
        source.warehouse_source_type
        for source in list_detected_warehouse_sources(context.team.id)
        if source.warehouse_source_type not in connected
    ]
    if not source_types:
        return HighlightFindings()
    labels = [tool_label(source_type) for source_type in source_types]
    one = len(source_types) == 1
    return HighlightFindings(
        items=(
            HighlightCandidate(
                key="wizard_unconnected_sources",
                label=HighlightLabel.OPPORTUNITY,
                family="wizard",
                importance=0.4,
                relevance=1.0,
                title=ONE_TITLE.format(source=labels[0]) if one else MANY_TITLE.format(count=len(labels)),
                detail=ONE_DETAIL if one else MANY_DETAIL.format(names=_names(labels)),
                url=f"{NEW_SOURCE_URL}?{urlencode({'kind': source_types[0]})}" if one else NEW_SOURCE_URL,
            ),
        )
    )
