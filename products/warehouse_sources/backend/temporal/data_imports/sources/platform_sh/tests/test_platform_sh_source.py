from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.platform_sh import AUTH_FAILED_MESSAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.source import PlatformShSource


class TestPlatformShSourceConfig:
    def test_platform_is_a_connection_host_field(self) -> None:
        # `platform` retargets which vendor host the stored token is sent to, so changing it must
        # force the editor to re-enter the secret.
        assert PlatformShSource().connection_host_fields == ["platform"]


class TestPlatformShGetSchemas:
    def test_only_activities_supports_incremental(self) -> None:
        schemas = {s.name: s for s in PlatformShSource().get_schemas(mock.Mock(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)

        activities = schemas["activities"]
        assert activities.supports_incremental is True
        assert activities.supports_append is True
        assert [f["field"] for f in activities.incremental_fields] == ["created_at"]
        # Activities mutate after creation; the lookback makes each sync re-read a trailing window
        # so completed states aren't frozen at first-imported values.
        assert activities.default_incremental_lookback_seconds == 86400

        for name, schema in schemas.items():
            if name == "activities":
                continue
            assert not schema.supports_incremental and not schema.supports_append
            assert schema.incremental_fields == []

    def test_names_filter(self) -> None:
        schemas = PlatformShSource().get_schemas(mock.Mock(), team_id=1, names=["projects", "activities"])
        assert {s.name for s in schemas} == {"projects", "activities"}


class TestPlatformShNonRetryableErrors:
    def test_covers_auth_failures_on_both_hosts(self) -> None:
        # Missing any of these means a permanently-bad credential retries forever.
        errors = PlatformShSource().get_non_retryable_errors()
        assert AUTH_FAILED_MESSAGE in errors
        for host in ("https://api.platform.sh", "https://api.upsun.com"):
            assert f"401 Client Error: Unauthorized for url: {host}" in errors
            assert f"403 Client Error: Forbidden for url: {host}" in errors
