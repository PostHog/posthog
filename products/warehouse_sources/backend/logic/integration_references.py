"""Find the warehouse sources that point at a core ``Integration``.

An OAuth source stores the pointer as a ``*_integration_id`` field in its inputs. The inputs are
encrypted, so SQL cannot search them. The search loads the inputs of the non-deleted sources of one
team, which keeps the cost bounded by the size of that team.
"""

from collections.abc import Mapping
from typing import Any

from posthog.integrations import IntegrationManager, IntegrationNotFound

from products.warehouse_sources.backend.facade.contracts import SourceReferencingIntegration
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

POINTER_SUFFIX = "_integration_id"


def list_sources_using_integration(team_id: int, integration_pk: int) -> list[SourceReferencingIntegration]:
    sources = list(
        ExternalDataSource.objects.select_related(None)
        .filter(team_id=team_id)
        .exclude(deleted=True)
        .only("id", "team_id", "source_type", "prefix", "job_inputs")
    )
    inputs_by_source = SourceInputsStore.load_many(sources)
    wanted = str(integration_pk)
    users = [
        SourceReferencingIntegration(id=source.id, source_type=str(source.source_type), prefix=source.prefix)
        for source in sources
        if source.id in inputs_by_source and _has_pointer(inputs_by_source[source.id], wanted)
    ]
    # A source whose inputs do not decode may point at the row. When it can use the kind of the row, it
    # counts as a user, so a shared edit asks for a confirmation and a delete is refused.
    unreadable = [source for source in sources if source.id not in inputs_by_source]
    kind = _row_kind(team_id, integration_pk) if unreadable else None
    users += [
        SourceReferencingIntegration(
            id=source.id, source_type=str(source.source_type), prefix=source.prefix, unreadable=True
        )
        for source in unreadable
        if kind is not None and _can_use_kind(str(source.source_type), kind)
    ]
    return users


def _row_kind(team_id: int, integration_pk: int) -> str | None:
    try:
        return IntegrationManager.any.with_source_rows().get(team_id, integration_pk).kind
    except IntegrationNotFound:
        return None


def _can_use_kind(source_type: str, kind: str) -> bool:
    # The registry loads every source, so keep it off this module's import path.
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415 — heavy import
        SourceRegistry,
    )

    try:
        return SourceRegistry.get_source(ExternalDataSourceType(source_type)).credential_kind == kind
    except ValueError:
        return True


def _has_pointer(inputs: Mapping[str, Any], wanted: str) -> bool:
    for key, value in inputs.items():
        if key.endswith(POINTER_SUFFIX) and value is not None and str(value) == wanted:
            return True
        # Switch groups and select options nest their fields one level down.
        if isinstance(value, Mapping) and _has_pointer(value, wanted):
            return True
    return False
