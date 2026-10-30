"""The warehouse sources that use an integration row. The integrations SDK loads this module."""

from posthog.integrations import IntegrationUsage

from products.warehouse_sources.backend.facade.contracts import (
    WAREHOUSE_SOURCE_USAGE_TYPE,
    SourceReferencingIntegration,
)
from products.warehouse_sources.backend.logic.integration_references import list_sources_using_integration


def integration_usages(team_id: int, integration_id: int) -> list[IntegrationUsage]:
    return [
        IntegrationUsage(
            type=WAREHOUSE_SOURCE_USAGE_TYPE,
            id=str(source.id),
            name=_name(source),
        )
        for source in list_sources_using_integration(team_id=team_id, integration_pk=integration_id)
    ]


def _name(source: SourceReferencingIntegration) -> str:
    name = f"{source.source_type} ({source.prefix})" if source.prefix else source.source_type
    return f"unreadable source: {name}" if source.unreadable else name
