from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vercel import VercelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel import source as vercel_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.source import VercelSource
from products.warehouse_sources.backend.types import IncrementalFieldType


def _source_inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
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


class TestVercelSource:
    def setup_method(self) -> None:
        self.source = VercelSource()
        self.config = VercelSourceConfig(access_token="token", team_id=None)

    def test_get_schemas_sync_capabilities_per_endpoint(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert set(schemas) == {
            "deployments",
            "events",
            "projects",
            "teams",
            "domains",
            "aliases",
            "check_runs",
            "billing_charges",
        }

        deployments = schemas["deployments"]
        assert deployments.supports_incremental is True
        assert deployments.supports_append is True
        assert [f["field"] for f in deployments.incremental_fields] == ["created"]
        assert deployments.incremental_fields[0]["field_type"] == IncrementalFieldType.Integer

        # The activity stream cursors on the event's own creation time, which never changes, and
        # supports append because events are immutable once emitted.
        events = schemas["events"]
        assert events.supports_incremental is True
        assert events.supports_append is True
        assert [f["field"] for f in events.incremental_fields] == ["createdAt"]
        assert events.incremental_fields[0]["field_type"] == IncrementalFieldType.Integer

        # Billing supports incremental merge but not append (append would duplicate restated charges),
        # cursors on the charge period, and carries a lookback so restatements get re-read and merged.
        billing = schemas["billing_charges"]
        assert billing.supports_incremental is True
        assert billing.supports_append is False
        assert [f["field"] for f in billing.incremental_fields] == ["charge_period_start"]
        assert billing.incremental_fields[0]["field_type"] == IncrementalFieldType.DateTime
        assert billing.default_incremental_lookback_seconds == 60 * 60 * 24 * 35

        # check_runs is a full-refresh fan-out over deployments: Vercel documents no server-side time
        # filter on the check-runs endpoint, so it re-fans every sync with no incremental cursor.
        for full_refresh in ("projects", "teams", "domains", "aliases", "check_runs"):
            assert schemas[full_refresh].supports_incremental is False
            assert schemas[full_refresh].supports_append is False
            assert schemas[full_refresh].incremental_fields == []

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        config = VercelSourceConfig(access_token="token", team_id="team_42")
        captured: dict[str, Any] = {}

        def fake_vercel_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock(name="source_response")

        manager = MagicMock()
        inputs = _source_inputs(
            "deployments",
            should_use_incremental_field=True,
            db_incremental_field_last_value=123,
            incremental_field="created",
        )

        with mock.patch.object(vercel_source_module, "vercel_source", fake_vercel_source):
            self.source.source_for_pipeline(config, manager, inputs)

        assert captured["access_token"] == "token"
        assert captured["team_id"] == "team_42"
        assert captured["endpoint"] == "deployments"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == 123
        assert captured["incremental_field"] == "created"
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        captured: dict[str, Any] = {}

        def fake_vercel_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock()

        inputs = _source_inputs("projects", should_use_incremental_field=False, db_incremental_field_last_value=999)
        with mock.patch.object(vercel_source_module, "vercel_source", fake_vercel_source):
            self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
