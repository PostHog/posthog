import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.neon.source import NeonSource
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource


@pytest.mark.parametrize(
    "host",
    [
        "ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech",
        "  EP-COOL-DARKNESS-123456-POOLER.US-EAST-2.AWS.NEON.TECH  ",
    ],
)
def test_cdc_prerequisites_reject_pooled_host_without_connecting(host):
    # The pooled endpoint accepts normal connections so the generic checks would pass,
    # but logical replication doesn't work through it — fail fast, no connection attempt.
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "check_cdc_prerequisites") as super_check:
        errors = NeonSource().check_cdc_prerequisites(config, management_mode="posthog", tables=["users"])

    super_check.assert_not_called()
    assert len(errors) == 1
    assert "-pooler" in errors[0]
    assert "logical replication" in errors[0].lower()


@pytest.mark.parametrize(
    "host",
    [
        "ep-cool-darkness-123456.us-east-2.aws.neon.tech",
        "my-pooler.example.com",  # non-Neon host: '-pooler' label must not trigger the guard
    ],
)
def test_cdc_prerequisites_delegate_for_direct_hosts(host):
    config = mock.MagicMock(host=host)

    with mock.patch.object(PostgresSource, "check_cdc_prerequisites", return_value=[]) as super_check:
        errors = NeonSource().check_cdc_prerequisites(config, management_mode="posthog", tables=["users"], team_id=7)

    super_check.assert_called_once()
    assert super_check.call_args.kwargs["team_id"] == 7
    assert errors == []
