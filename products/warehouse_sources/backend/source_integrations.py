"""Link between a warehouse source and the OAuth integration that authenticates it.

A source stores its connected account as an `<kind>_integration_id` entry in `job_inputs`. Two
paths need that link: the sync teardown, which marks the integration when the account can no
longer authenticate, and the reconnect path, which resumes the tables that failure turned off.
"""

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
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


def mark_integration_auth_error(source: ExternalDataSource, *, job_id: str) -> None:
    """Record on the connected integration that it can no longer authenticate.

    Only the token-refresh call used to write this, so an account the vendor rejects at request
    time kept reading as connected everywhere the integration is shown, with no way to reconnect.

    A run reads its access token once and holds it for the rest of the run, so a run that outlives
    a reconnect would report a credential that no longer exists and undo the repair. An integration
    re-authorized after this run started is therefore left alone: the credential it holds now was
    never the one that failed. OAuth stamps `config["refreshed_at"]` on every reconnect and token
    refresh, which is the only credential version both sides can see.
    """
    integration_ids = get_source_integration_ids(source)
    if not integration_ids:
        return
    run_started_at = (
        ExternalDataJob.objects.filter(pk=job_id, team_id=source.team_id).values_list("created_at", flat=True).first()
    )
    if run_started_at is not None:
        # Only a stamp we can read and compare skips the write. An integration with no
        # `refreshed_at` is still marked, so an older row without the stamp keeps the old behavior.
        integration_ids -= set(
            Integration.objects.filter(
                id__in=integration_ids,
                team_id=source.team_id,
                config__refreshed_at__gt=int(run_started_at.timestamp()),
            ).values_list("id", flat=True)
        )
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
    source_cls = SourceRegistry.get_source(source_type)
    auth_errors = source_cls.get_auth_errors()
    # A stopped table stores the friendly message written for the error that stopped it, not the
    # raw failure. For a key whose friendly message shares no wording with the key, matching the
    # key alone would never fire, so carry both spellings of every authentication error.
    friendly_messages = {
        friendly
        for error, friendly in source_cls.get_non_retryable_errors().items()
        if friendly and error in auth_errors
    }
    return auth_errors | friendly_messages


def resume_syncs_paused_by_auth_failure(*, integration_id: int, team_id: int) -> int:
    """Turn syncing back on for the tables an authentication failure stopped, and return how many.

    Reconnecting is what a customer does to repair an expired account, so the tables that stopped
    for that reason start again without a second trip through every table. A table the customer
    turned off, or one that failed for another reason, keeps its state.
    """
    resumed = 0
    failures: list[Exception] = []
    for source in ExternalDataSource.objects.filter(team_id=team_id).exclude(deleted=True):
        if integration_id not in get_source_integration_ids(source):
            continue
        markers = _auth_error_markers(source)
        if not markers:
            continue
        schemas = ExternalDataSchema.objects.filter(
            team_id=team_id, source=source, should_sync=False, status=ExternalDataSchemaStatus.FAILED
        ).exclude(deleted=True)
        for schema in schemas:
            latest_error = (schema.latest_error or "").lower()
            if not any(marker.lower() in latest_error for marker in markers):
                continue
            try:
                update_should_sync(schema_id=str(schema.id), team_id=team_id, should_sync=True)
            except Exception as error:
                # Restarting a table reaches Temporal, so one unreachable schedule must not strand
                # every table after it. Carry on, then raise so the caller retries what failed. A
                # table that did start is skipped next time, because this reads only stopped ones.
                failures.append(error)
                continue
            resumed += 1
    if failures:
        raise failures[0]
    return resumed
