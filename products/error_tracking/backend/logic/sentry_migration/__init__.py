from django.db import transaction

from products.error_tracking.backend.facade.contracts import (
    SentryConnection,
    SentryMigrationItem,
    SentryMigrationRateLimit,
    SentryMigrationResult,
    SentryProject,
    SentryProjectRef,
)
from products.error_tracking.backend.logic import get_or_create_settings, update_settings
from products.error_tracking.backend.logic.built_in_filters import list_built_in_filters, set_built_in_filter_enabled
from products.error_tracking.backend.logic.rules import create_suppression_rule, list_suppression_rules
from products.error_tracking.backend.logic.sentry_migration.client import SentryApiClient
from products.error_tracking.backend.logic.sentry_migration.errors import SentryMigrationSelectionError
from products.error_tracking.backend.logic.sentry_migration.plan import SentryMigrationPlanner


def list_sentry_projects(connection: SentryConnection) -> list[SentryProject]:
    return SentryApiClient(connection).list_projects()


def preview_sentry_migration(
    team_id: int, connection: SentryConnection, project: SentryProjectRef
) -> list[SentryMigrationItem]:
    config = SentryApiClient(connection).get_project_config(project)
    settings = get_or_create_settings(team_id)
    project_rate_limit = (
        SentryMigrationRateLimit(
            value=settings.project_rate_limit_value,
            bucket_size_minutes=settings.project_rate_limit_bucket_size_minutes,
        )
        if settings.project_rate_limit_value is not None and settings.project_rate_limit_bucket_size_minutes is not None
        else None
    )
    # A rule that samples, or that cymbal disabled, doesn't drop every matching exception the way Sentry did.
    active_full_rules = list_suppression_rules(team_id).filter(
        disabled_data__isnull=True, bytecode__isnull=False, sampling_rate__gte=1.0
    )
    # An automatic rule that ingestion turned off drops nothing, so the import can turn it on again.
    enabled_built_in_filters = [
        state.definition.key
        for state in list_built_in_filters(team_id)
        if state.enabled and state.disabled_reason is None
    ]
    planner = SentryMigrationPlanner(
        existing_suppression_filters=active_full_rules.values_list("filters", flat=True),
        enabled_built_in_filters=enabled_built_in_filters,
        project_rate_limit=project_rate_limit,
    )
    return planner.build(config)


def apply_sentry_migration(
    team_id: int, connection: SentryConnection, project: SentryProjectRef, item_ids: list[str]
) -> SentryMigrationResult:
    """Build the plan again from Sentry and import the selected items.

    Rebuilding the plan on the server means a client can only import what the conversion
    produced, never an arbitrary payload.
    """
    items_by_id = {item.id: item for item in preview_sentry_migration(team_id, connection, project)}
    selected: list[SentryMigrationItem] = []
    for item_id in dict.fromkeys(item_ids):
        item = items_by_id.get(item_id)
        if item is None:
            raise SentryMigrationSelectionError(
                "Some selected settings changed in Sentry since the preview. Load the preview again."
            )
        if not item.importable:
            raise SentryMigrationSelectionError(f'"{item.sentry_setting}" has no PostHog equivalent to import.')
        selected.append(item)

    rate_limits = [item.rate_limit for item in selected if item.rate_limit is not None]
    if len(rate_limits) > 1:
        raise SentryMigrationSelectionError("PostHog has one rate limit per project. Select only one rate limit.")

    # The rebuilt plan reflects what this project has now, so a retried request doesn't create duplicates.
    pending = [item for item in selected if not item.already_in_posthog]
    new_rate_limits = [item.rate_limit for item in pending if item.rate_limit is not None]
    suppression_filters = [
        item.suppression_rule_filters for item in pending if item.suppression_rule_filters is not None
    ]
    built_in_keys = [item.built_in_filter.key for item in pending if item.built_in_filter is not None]
    with transaction.atomic():
        for filters in suppression_filters:
            create_suppression_rule(team_id, filters=filters, sampling_rate=1.0)
        for key in built_in_keys:
            set_built_in_filter_enabled(team_id, key, enabled=True)
        if new_rate_limits:
            update_settings(
                team_id,
                {
                    "project_rate_limit_value": new_rate_limits[0].value,
                    "project_rate_limit_bucket_size_minutes": new_rate_limits[0].bucket_size_minutes,
                },
            )

    return SentryMigrationResult(
        suppression_rules_created=len(suppression_filters),
        built_in_filters_enabled=len(built_in_keys),
        rate_limit_updated=bool(new_rate_limits),
    )
