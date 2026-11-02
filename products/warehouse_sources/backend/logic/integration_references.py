"""Find the warehouse sources that point at a core ``Integration``.

A source points at the one row it uses with its ``credentials_integration_id`` column: its typed-in
credentials row, or the OAuth row of its in-use ``*_integration_id`` pointer. One indexed query reads it.
"""

from posthog.integrations import IntegrationReference

from products.warehouse_sources.backend.facade.contracts import SourceReferencingIntegration
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


def list_sources_using_integration(team_id: int, integration_pk: int) -> list[SourceReferencingIntegration]:
    sources = (
        ExternalDataSource.objects.select_related(None)
        .filter(
            team_id=team_id,
            credentials_integration_id=str(IntegrationReference.from_legacy_id(integration_pk)),
        )
        .exclude(deleted=True)
        .only("id", "source_type", "prefix")
    )
    return [
        SourceReferencingIntegration(id=source.id, source_type=str(source.source_type), prefix=source.prefix)
        for source in sources
    ]
