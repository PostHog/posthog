from __future__ import annotations

from posthog.scopes import APIScopeObjectOrNotSupported

from products.logs.backend.facade.retention import RETENTION_RULE_SOURCE_SPANS
from products.logs.backend.facade.retention_views import LogsRetentionRuleViewSet


class TracingRetentionRuleViewSet(LogsRetentionRuleViewSet):
    """Span retention rules.

    Shares the logs implementation — only the record source, the access-control scope and the
    feature flag differ. The source is pinned here rather than taken from the payload, so a
    client can never move a rule between logs and spans.
    """

    scope_object: APIScopeObjectOrNotSupported = "tracing"
    posthog_feature_flag = "tracing-settings-retention-rules"
    rule_source = RETENTION_RULE_SOURCE_SPANS
