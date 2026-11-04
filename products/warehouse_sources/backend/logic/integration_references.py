"""Find the warehouse sources that point at a core ``Integration``.

A source points at its typed-in credentials row with its ``credentials_integration_id`` column, which
one indexed query reads. An OAuth source still stores its pointer as a ``*_integration_id`` field in its
inputs. The inputs are encrypted, so SQL cannot search them. That search loads the inputs of the
non-deleted sources of one team, which keeps the cost bounded by the size of that team.
"""

from collections.abc import Mapping
from typing import Any

from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX
from posthog.integrations import IntegrationManager, IntegrationNotFound, IntegrationReference

from products.warehouse_sources.backend.facade.contracts import SourceReferencingIntegration
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

POINTER_SUFFIX = "_integration_id"
# The name of the reference column. Inputs never hold the typed-in pointer, so the inputs search skips
# a stale key of this name.
_COLUMN_POINTER_KEY = "credentials_integration_id"


def list_sources_using_integration(team_id: int, integration_pk: int) -> list[SourceReferencingIntegration]:
    users = {source.id: source for source in _sources_by_column(team_id, integration_pk)}
    for source in _sources_by_inputs(team_id, integration_pk):
        users.setdefault(source.id, source)
    return list(users.values())


def _sources_by_column(team_id: int, integration_pk: int) -> list[SourceReferencingIntegration]:
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


def _sources_by_inputs(team_id: int, integration_pk: int) -> list[SourceReferencingIntegration]:
    sources = list(
        ExternalDataSource.objects.select_related(None)
        .filter(team_id=team_id)
        .exclude(deleted=True)
        .only("id", "team_id", "source_type", "prefix", "job_inputs", "credentials_integration_id")
    )
    inputs_by_source = {
        source_id: inputs
        for source_id, inputs in SourceInputsStore.load_many(sources).items()
        if not _has_ciphertext(inputs)
    }
    wanted = str(integration_pk)
    users = [
        SourceReferencingIntegration(id=source.id, source_type=str(source.source_type), prefix=source.prefix)
        for source in sources
        if source.id in inputs_by_source and _has_pointer(inputs_by_source[source.id], wanted)
    ]
    # A source whose inputs do not decode may hold an OAuth pointer to the row. When it can use the kind
    # of the row, it counts as a user, so a shared edit asks for a confirmation and a delete is refused.
    unreadable = [source for source in sources if source.id not in inputs_by_source]
    kind = _oauth_row_kind(team_id, integration_pk) if unreadable else None
    users += [
        SourceReferencingIntegration(
            id=source.id, source_type=str(source.source_type), prefix=source.prefix, unreadable=True
        )
        for source in unreadable
        if kind is not None and _can_use_kind(str(source.source_type), kind)
    ]
    return users


def _oauth_row_kind(team_id: int, integration_pk: int) -> str | None:
    # Inputs point only at rows that are not typed-in source rows, and `IntegrationManager.any` skips
    # typed-in rows. So an unreadable source never counts as a user of a typed-in row.
    try:
        return IntegrationManager.any.get(team_id, integration_pk).kind
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
        if key.endswith(POINTER_SUFFIX) and key != _COLUMN_POINTER_KEY and value is not None and str(value) == wanted:
            return True
        # Switch groups and select options nest their fields one level down.
        if isinstance(value, Mapping) and _has_pointer(value, wanted):
            return True
    return False


def _has_ciphertext(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_has_ciphertext(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_ciphertext(item) for item in value)
    return isinstance(value, str) and value.startswith(FERNET_TOKEN_PREFIX)
