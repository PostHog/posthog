"""Saving recording rules. The evaluation lives in `evaluation.py`."""

import re
from typing import Final

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from products.metrics.backend.facade.contracts import (
    MAX_PROMQL_LENGTH,
    MAX_RECORDING_RULES_PER_TEAM,
    RecordingRule,
    RecordingRuleError,
    RecordingRuleNotFound,
)
from products.metrics.backend.models import MetricRecordingRule

# The Prometheus `level:metric:operations` convention. The colon keeps a recorded name apart from every
# name OpenTelemetry ingestion writes, so a rule never writes into a series that a service sends.
_METRIC_NAME: Final = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*:[a-zA-Z0-9_:]*$")
_NAME_CHARACTERS: Final = r"[a-zA-Z0-9_:]"


def validate_rule(metric_name: str, query: str) -> None:
    if not _METRIC_NAME.match(metric_name):
        raise RecordingRuleError(
            "The metric name must look like level:metric:operations, for example job:http_errors:rate5m. "
            "Use letters, digits, underscores and colons, with at least one colon."
        )
    if not query.strip():
        raise RecordingRuleError("The query cannot be empty.")
    if len(query) > MAX_PROMQL_LENGTH:
        raise RecordingRuleError(f"The query cannot be longer than {MAX_PROMQL_LENGTH} characters.")
    # A rule that reads its own output adds its last result into every new one.
    if re.search(rf"(?<!{_NAME_CHARACTERS}){re.escape(metric_name)}(?!{_NAME_CHARACTERS})", query):
        raise RecordingRuleError("The query cannot read the metric that the rule writes.")


def to_contract(rule: MetricRecordingRule) -> RecordingRule:
    return RecordingRule(
        id=str(rule.id),
        metric_name=rule.metric_name,
        query=rule.query,
        description=rule.description,
        enabled=rule.enabled,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        last_evaluated_at=rule.last_evaluated_at,
        last_series_count=rule.last_series_count,
        last_error=rule.last_error,
    )


def list_rules(team_id: int) -> list[RecordingRule]:
    return [to_contract(rule) for rule in MetricRecordingRule.objects.filter(team_id=team_id).order_by("metric_name")]


def _get(team_id: int, rule_id: str) -> MetricRecordingRule:
    try:
        return MetricRecordingRule.objects.get(team_id=team_id, id=rule_id)
    except (MetricRecordingRule.DoesNotExist, ValueError, ValidationError):
        raise RecordingRuleNotFound("Recording rule not found.")


def get_rule(team_id: int, rule_id: str) -> RecordingRule:
    return to_contract(_get(team_id, rule_id))


def create_rule(
    team_id: int, *, created_by_id: int | None, metric_name: str, query: str, description: str, enabled: bool
) -> RecordingRule:
    validate_rule(metric_name, query)
    with transaction.atomic():
        # The count and the insert are two statements, and the name constraint does not see a concurrent create
        # of another name, so creates for one project wait for each other here.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"metrics-recording-rules:{team_id}"])
        if MetricRecordingRule.objects.filter(team_id=team_id).count() >= MAX_RECORDING_RULES_PER_TEAM:
            raise RecordingRuleError(f"A project can have at most {MAX_RECORDING_RULES_PER_TEAM} recording rules.")
        try:
            with transaction.atomic():
                rule = MetricRecordingRule.objects.create(
                    team_id=team_id,
                    created_by_id=created_by_id,
                    metric_name=metric_name,
                    query=query,
                    description=description,
                    enabled=enabled,
                )
        except IntegrityError:
            raise RecordingRuleError(f"Another recording rule in this project already writes {metric_name}.")
    return to_contract(rule)


def update_rule(
    team_id: int,
    rule_id: str,
    *,
    query: str | None = None,
    description: str | None = None,
    enabled: bool | None = None,
) -> RecordingRule:
    rule = _get(team_id, rule_id)
    fields = ["updated_at"]
    if query is not None:
        validate_rule(rule.metric_name, query)
        rule.query = query
        # The last error belongs to the old query.
        rule.last_error = None
        fields += ["query", "last_error"]
    if description is not None:
        rule.description = description
        fields.append("description")
    if enabled is not None:
        rule.enabled = enabled
        fields.append("enabled")
    # Only the edited fields, so an evaluation that finished meanwhile keeps the minute it recorded.
    rule.save(update_fields=fields)
    rule.refresh_from_db()
    return to_contract(rule)


def delete_rule(team_id: int, rule_id: str) -> None:
    _get(team_id, rule_id).delete()
