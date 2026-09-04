"""Link between a warehouse source and the OAuth integration that authenticates it.

A source stores its connected account as an `<kind>_integration_id` entry in `job_inputs`. Two
paths need that link: the sync teardown, which marks the integration when the account can no
longer authenticate, and the reconnect path, which resumes the tables that failure turned off.
"""

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema, update_should_sync
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSchemaStatus, ExternalDataSourceType


def get_source_integration_ids(source: ExternalDataSource) -> set[int]:
    """The ids of the integrations a source authenticates with, empty when it uses none.

    A source can hold more than one, because a field set can offer OAuth alongside another auth
    method, so read every `_integration_id` entry rather than the first one.
    """
    job_inputs = source.job_inputs
    if not isinstance(job_inputs, dict):
        return set()
    integration_ids = set()
    for key, value in job_inputs.items():
        if not key.endswith("_integration_id"):
            continue
        try:
            integration_ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return integration_ids


def mark_integration_auth_error(source: ExternalDataSource) -> None:
    """Record on the connected integration that it can no longer authenticate.

    Only the token-refresh call used to write this, so an account the vendor rejects at request
    time kept reading as connected everywhere the integration is shown, with no way to reconnect.
    """
    integration_ids = get_source_integration_ids(source)
    if not integration_ids:
        return
    Integration.objects.filter(id__in=integration_ids, team_id=source.team_id).exclude(
        errors=ERROR_TOKEN_REFRESH_FAILED
    ).update(errors=ERROR_TOKEN_REFRESH_FAILED)


def _auth_error_markers(source: ExternalDataSource) -> set[str]:
    from products.warehouse_sources.backend.temporal.data_imports.sources import (  # noqa: PLC0415 — keeps the source registry off the import path
        SourceRegistry,
    )

    try:
        source_type = ExternalDataSourceType(source.source_type)
    except ValueError:
        return set()
    return SourceRegistry.get_source(source_type).get_auth_errors()


def resume_syncs_paused_by_auth_failure(*, integration_id: int, team_id: int) -> int:
    """Turn syncing back on for the tables an authentication failure stopped, and return how many.

    Reconnecting is what a customer does to repair an expired account, so the tables that stopped
    for that reason start again without a second trip through every table. A table the customer
    turned off, or one that failed for another reason, keeps its state.
    """
    resumed = 0
    for source in ExternalDataSource.objects.filter(team_id=team_id).exclude(deleted=True):
        if integration_id not in get_source_integration_ids(source):
            continue
        markers = _auth_error_markers(source)
        if not markers:
            continue
        schemas = ExternalDataSchema.objects.filter(
            team_id=team_id, source=source, should_sync=False, status=ExternalDataSchemaStatus.FAILED
        )
        for schema in schemas:
            latest_error = (schema.latest_error or "").lower()
            if not any(marker.lower() in latest_error for marker in markers):
                continue
            update_should_sync(schema_id=str(schema.id), team_id=team_id, should_sync=True)
            resumed += 1
    return resumed
