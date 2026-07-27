import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.dub import DubResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.source import DubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dub import DubSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

EVENT_ENDPOINTS = ("click_events", "lead_events", "sale_events")


def _make_inputs(**overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": "links",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestDubSource:
    def setup_method(self):
        self.source = DubSource()
        self.config = DubSourceConfig(api_key="dub_test_key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DUB

    def test_source_is_released(self) -> None:
        # unreleasedSource=True hides the connector from every user; a finished source
        # must never regain it.
        assert not self.source.get_source_config.unreleasedSource

    def test_source_config_has_secret_api_key_field(self) -> None:
        fields = self.source.get_source_config.fields
        assert [f.name for f in fields] == ["api_key"]
        assert isinstance(fields[0], SourceFieldInputConfig)
        assert fields[0].secret is True

    def test_get_schemas_only_event_streams_are_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)

        assert [s.name for s in schemas] == list(ENDPOINTS)
        incremental = {s.name for s in schemas if s.supports_incremental}
        assert incremental == set(EVENT_ENDPOINTS)
        for schema in schemas:
            if schema.name in EVENT_ENDPOINTS:
                assert [f["field"] for f in schema.incremental_fields] == ["timestamp"]

    def test_get_schemas_names_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["links", "tags"])

        assert [s.name for s in schemas] == ["links", "tags"]

    @pytest.mark.parametrize(
        ("valid", "message"),
        [
            (True, None),
            (False, "Invalid Dub API key. Please check your key and try again."),
        ],
    )
    def test_validate_credentials_probes_token(self, valid: bool, message: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.source.validate_dub_credentials",
            return_value=(valid, message),
        ) as mock_validate:
            assert self.source.validate_credentials(self.config, team_id=1) == (valid, message)

        mock_validate.assert_called_once_with("dub_test_key")

    @pytest.mark.parametrize(
        ("reason", "expected"),
        [
            (None, (True, None)),
            ("Requires a Business plan or higher.", (False, "Requires a Business plan or higher.")),
        ],
    )
    def test_validate_credentials_with_schema_name_checks_endpoint_access(
        self, reason: str | None, expected: tuple[bool, str | None]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.source.check_endpoint_access",
            return_value=reason,
        ) as mock_check:
            assert self.source.validate_credentials(self.config, team_id=1, schema_name="click_events") == expected

        mock_check.assert_called_once_with("dub_test_key", "click_events")

    def test_get_endpoint_permissions_probes_events_once(self) -> None:
        # All three event tables share /events, so one probe must cover them; ungated
        # endpoints are reported reachable without any request.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.source.check_endpoint_access",
            return_value="Business plan required",
        ) as mock_check:
            permissions = self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=list(ENDPOINTS))

        probed = [call.args[1] for call in mock_check.call_args_list]
        assert len([e for e in probed if e in EVENT_ENDPOINTS]) == 1
        assert set(probed) - set(EVENT_ENDPOINTS) == {"partners", "commissions", "payouts"}
        for endpoint in EVENT_ENDPOINTS:
            assert permissions[endpoint] == "Business plan required"
        assert permissions["links"] is None
        assert permissions["tags"] is None

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DubResumeConfig

    def test_source_for_pipeline_plumbs_inputs(self) -> None:
        inputs = _make_inputs(
            schema_name="click_events",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-05-01T00:00:00",
        )
        manager = MagicMock(spec=ResumableSourceManager)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.source.dub_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="dub_test_key",
            endpoint="click_events",
            team_id=1,
            job_id="job-id",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-05-01T00:00:00",
        )

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = _make_inputs(
            schema_name="links",
            should_use_incremental_field=False,
            db_incremental_field_last_value="stale-watermark",
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.source.dub_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, MagicMock(spec=ResumableSourceManager), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
