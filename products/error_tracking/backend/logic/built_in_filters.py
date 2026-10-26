from collections.abc import Callable
from typing import Literal

from django.db import IntegrityError, transaction
from django.db.models import Q

import structlog

from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.built_in_filter_definitions import (
    BUILT_IN_FILTERS,
    BUILT_IN_FILTERS_BY_KEY,
    BuiltInFilter,
)
from products.error_tracking.backend.logic.rules import (
    compile_filter_bytecode,
    create_suppression_rule,
    get_client_safe_filters,
)
from products.error_tracking.backend.models import ErrorTrackingSuppressionRule

logger = structlog.get_logger(__name__)

BuiltInFilterEvaluation = Literal["client", "server"]


class UnknownBuiltInFilterError(Exception):
    pass


@frozen
class BuiltInFilterState:
    definition: BuiltInFilter
    enabled: bool
    # Set when ingestion turned the rule off because it failed on an event.
    disabled_reason: str | None


@frozen
class BuiltInFilterRefreshResult:
    rules_refreshed: int
    rules_failed: int


def built_in_filter_evaluation(definition: BuiltInFilter) -> BuiltInFilterEvaluation:
    return "client" if get_client_safe_filters(definition.filters) is not None else "server"


def _disabled_reason(rule: ErrorTrackingSuppressionRule | None) -> str | None:
    if rule is None or rule.disabled_data is None:
        return None
    message = rule.disabled_data.get("message") if isinstance(rule.disabled_data, dict) else None
    return message if isinstance(message, str) and message else "Unknown error"


def _state(definition: BuiltInFilter, rule: ErrorTrackingSuppressionRule | None) -> BuiltInFilterState:
    return BuiltInFilterState(definition=definition, enabled=rule is not None, disabled_reason=_disabled_reason(rule))


def _is_older_than(rule: ErrorTrackingSuppressionRule, definition: BuiltInFilter) -> bool:
    return rule.built_in_version is None or rule.built_in_version < definition.version


def _refresh_rule(rule: ErrorTrackingSuppressionRule, definition: BuiltInFilter) -> None:
    rule.filters = definition.filters
    rule.bytecode = compile_filter_bytecode(rule.team_id, definition.filters)
    rule.built_in_version = definition.version
    # A rewritten rule gets a fresh start, so a rule that ingestion turned off runs again.
    rule.disabled_data = None
    # update_fields makes the save fail rather than recreate a row that a user deleted in the meantime.
    rule.save(update_fields=["filters", "bytecode", "built_in_version", "disabled_data", "updated_at"])


def list_built_in_filters(team_id: int) -> list[BuiltInFilterState]:
    rules = {
        rule.built_in_key: rule
        for rule in ErrorTrackingSuppressionRule.objects.filter(team_id=team_id, built_in_key__isnull=False)
    }
    return [_state(definition, rules.get(definition.key)) for definition in BUILT_IN_FILTERS]


def set_built_in_filter_enabled(team_id: int, key: str, *, enabled: bool) -> BuiltInFilterState:
    definition = BUILT_IN_FILTERS_BY_KEY.get(key)
    if definition is None:
        raise UnknownBuiltInFilterError(key)

    existing = ErrorTrackingSuppressionRule.objects.filter(team_id=team_id, built_in_key=key).first()
    if not enabled:
        if existing is not None:
            existing.delete()
        return _state(definition, None)

    if existing is not None:
        if existing.disabled_data is not None or _is_older_than(existing, definition):
            _refresh_rule(existing, definition)
        return _state(definition, existing)

    try:
        with transaction.atomic():
            rule = create_suppression_rule(
                team_id,
                filters=definition.filters,
                sampling_rate=1.0,
                built_in_key=definition.key,
                built_in_version=definition.version,
            )
    except IntegrityError:
        # A concurrent request turned the same filter on first.
        rule = ErrorTrackingSuppressionRule.objects.get(team_id=team_id, built_in_key=key)
    return _state(definition, rule)


def _stale_rules_filter() -> Q:
    stale = Q()
    for definition in BUILT_IN_FILTERS:
        stale |= Q(built_in_key=definition.key) & (
            Q(built_in_version__isnull=True) | Q(built_in_version__lt=definition.version)
        )
    return stale


def refresh_stale_built_in_filter_rules(
    *, batch_size: int, on_progress: Callable[[], None] | None = None
) -> BuiltInFilterRefreshResult:
    """Rewrite every built-in rule whose version is older than its definition.

    It only upgrades. During a deploy, a worker that still runs older code leaves newer rows alone,
    and it skips a row whose key it doesn't know rather than delete it.
    """
    refreshed = 0
    failed = 0
    stale = _stale_rules_filter()
    cursor = None
    while True:
        queryset = ErrorTrackingSuppressionRule.objects.filter(stale).order_by("id")
        if cursor is not None:
            queryset = queryset.filter(id__gt=cursor)
        batch = list(queryset[:batch_size])
        if not batch:
            break
        for rule in batch:
            try:
                _refresh_rule(rule, BUILT_IN_FILTERS_BY_KEY[str(rule.built_in_key)])
                refreshed += 1
            except Exception:
                failed += 1
                logger.exception(
                    "error_tracking.built_in_filters.refresh_failed",
                    rule_id=str(rule.id),
                    team_id=rule.team_id,
                    built_in_key=rule.built_in_key,
                )
        cursor = batch[-1].id
        if on_progress is not None:
            on_progress()
    return BuiltInFilterRefreshResult(rules_refreshed=refreshed, rules_failed=failed)
