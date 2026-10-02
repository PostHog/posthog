from posthog.models.team.logs_retention import DEFAULT_LOGS_RETENTION_DAYS

from products.tracing.backend.models import DEFAULT_TRACES_RETENTION_DAYS


def test_traces_retention_default_matches_logs_default() -> None:
    assert DEFAULT_TRACES_RETENTION_DAYS == DEFAULT_LOGS_RETENTION_DAYS
