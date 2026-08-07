import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.source import XmattersSource
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.xmatters import XmattersResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType

XMATTERS_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.xmatters"


class TestXmattersSource:
    def setup_method(self) -> None:
        self.source = XmattersSource()
        self.config = MagicMock(subdomain="acme", username="svc", password="secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.XMATTERS

    def test_source_config_is_visible_and_alpha(self) -> None:
        # A finished source must not carry `unreleasedSource` (which hides it) and marks
        # newness via releaseStatus instead.
        config = self.source.get_source_config
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/xmatters.png"

    def test_source_config_fields(self) -> None:
        fields = self.source.get_source_config.fields
        assert fields is not None
        by_name = {f.name: f for f in fields if isinstance(f, SourceFieldInputConfig)}
        assert set(by_name) == {"subdomain", "username", "password"}
        # Only the password is a secret; the subdomain is the connection host.
        assert by_name["password"].type == SourceFieldInputConfigType.PASSWORD
        assert by_name["password"].secret is True
        assert by_name["subdomain"].secret is not True

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Retargeting the subdomain must re-require the stored secret.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_only_events_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert set(schemas) == set(ENDPOINTS)

        assert schemas["events"].supports_incremental is True
        assert schemas["events"].incremental_fields[0]["field"] == "created"
        assert schemas["events"].incremental_fields[0]["field_type"] == IncrementalFieldType.DateTime

        for name in ENDPOINTS:
            if name == "events":
                continue
            assert schemas[name].supports_incremental is False, name
            assert schemas[name].incremental_fields == [], name

    def test_no_endpoint_supports_append(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)
        assert all(s.supports_append is False for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["events", "people"])
        assert {s.name for s in schemas} == {"events", "people"}

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog powers the public docs table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "pattern",
        [
            "401 Client Error: Unauthorized for url",
            "403 Client Error: Forbidden for url",
        ],
    )
    def test_non_retryable_errors_includes_pattern(self, pattern: str) -> None:
        assert pattern in self.source.get_non_retryable_errors()

    def test_validate_credentials_rejects_hostile_subdomain_without_probing(self) -> None:
        # SSRF guard: an invalid subdomain must be rejected before any request is sent.
        self.config.subdomain = "attacker.example/"
        with patch(f"{XMATTERS_MODULE}.source.validate_xmatters_credentials") as mock_validate:
            ok, error = self.source.validate_credentials(self.config, team_id=1)
        assert ok is False
        assert error == "xMatters subdomain is invalid"
        mock_validate.assert_not_called()

    def test_validate_credentials_success(self) -> None:
        with patch(f"{XMATTERS_MODULE}.source.validate_xmatters_credentials", return_value=(True, 200, None)):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    def test_validate_credentials_invalid(self) -> None:
        with patch(
            f"{XMATTERS_MODULE}.source.validate_xmatters_credentials",
            return_value=(False, 401, "Invalid xMatters credentials"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert error == "Invalid xMatters credentials"

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid account may only be scoped to a subset of resources; don't block connection.
        with patch(
            f"{XMATTERS_MODULE}.source.validate_xmatters_credentials",
            return_value=(False, 403, "no access"),
        ):
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with patch(
            f"{XMATTERS_MODULE}.source.validate_xmatters_credentials",
            return_value=(False, 403, "no access"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="events")
            assert ok is False
            assert error == "no access"

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock(team_id=1, job_id="job_1", logger=MagicMock())
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is XmattersResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock()
        inputs = MagicMock(
            schema_name="events",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00+00:00",
            logger=MagicMock(),
        )

        with patch(f"{XMATTERS_MODULE}.source.xmatters_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["username"] == "svc"
        assert kwargs["password"] == "secret"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00+00:00"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        manager = MagicMock()
        inputs = MagicMock(
            schema_name="people",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00+00:00",
            logger=MagicMock(),
        )

        with patch(f"{XMATTERS_MODULE}.source.xmatters_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
