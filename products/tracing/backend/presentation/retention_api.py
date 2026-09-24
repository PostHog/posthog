from __future__ import annotations

from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema, extend_schema_view

from posthog.scopes import APIScopeObjectOrNotSupported

from products.logs.backend.facade.retention_views import LogsRetentionRuleSerializer, LogsRetentionRuleViewSet
from products.tracing.backend.facade.retention import TracesRetentionRule


class TracesRetentionRuleSerializer(LogsRetentionRuleSerializer):
    retention_label = "span retention"

    class Meta(LogsRetentionRuleSerializer.Meta):
        model = TracesRetentionRule


@extend_schema_view(reorder=extend_schema(responses={200: TracesRetentionRuleSerializer(many=True)}))
class TracingRetentionRuleViewSet(LogsRetentionRuleViewSet):
    """Span retention rules.

    Shares the logs implementation over its own model. Only the model, the access-control scope and
    the feature flag differ.
    """

    scope_object: APIScopeObjectOrNotSupported = "tracing"
    # `objects` is environment-scoped and refuses an unscoped queryset, so the class-level queryset
    # uses the plain manager; every request goes through `team_rules` instead.
    queryset = TracesRetentionRule.all_teams.all().order_by("priority", "created_at")
    serializer_class = TracesRetentionRuleSerializer
    posthog_feature_flag = "tracing-settings-retention-rules"
    rule_source = "spans"

    def team_rules(self) -> QuerySet:
        return TracesRetentionRule.objects.for_team(self.team_id)
