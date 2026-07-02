from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.source import TrelloSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.trello import TrelloResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> Any:
    return TrelloSource().parse_config({"api_key": "key", "api_token": "token"})


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "actions",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": True,
        "db_incremental_field_last_value": "2026-01-01T00:00:00Z",
        "db_incremental_field_earliest_value": None,
        "incremental_field": "date",
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": mock.Mock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSourceType:
    def test_source_type(self) -> None:
        assert TrelloSource().source_type == ExternalDataSourceType.TRELLO


class TestSourceConfig:
    def test_config_fields(self) -> None:
        config = TrelloSource().get_source_config
        assert config.label == "Trello"
        assert not config.unreleasedSource
        assert config.releaseStatus == "alpha"
        assert [f.name for f in config.fields] == ["api_key", "api_token"]
        # Both credentials must be stored as secrets.
        assert all(getattr(f, "secret", False) for f in config.fields)


class TestGetSchemas:
    def test_only_actions_supports_incremental(self) -> None:
        schemas = {s.name: s for s in TrelloSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS)
        assert schemas["actions"].supports_incremental is True
        assert [f["field"] for f in schemas["actions"].incremental_fields] == ["date"]
        for name in ("boards", "cards", "lists", "organizations", "checklists", "labels", "members"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_names_filter(self) -> None:
        schemas = TrelloSource().get_schemas(_config(), team_id=1, names=["cards", "actions"])
        assert {s.name for s in schemas} == {"cards", "actions"}


class TestValidateCredentials:
    @parameterized.expand([("valid", (True, None)), ("invalid", (False, "Invalid Trello API key or token"))])
    def test_delegates_to_transport(self, _name: str, transport_result: tuple[bool, str | None]) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trello.source.validate_trello_credentials",
            return_value=transport_result,
        ) as validate:
            result = TrelloSource().validate_credentials(_config(), team_id=1)

        assert result == transport_result
        validate.assert_called_once_with("key", "token")


class TestGetNonRetryableErrors:
    def test_covers_auth_failures(self) -> None:
        errors = TrelloSource().get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors
        assert "invalid key" in errors
        assert "invalid token" in errors


class TestResumableSourceManager:
    def test_manager_bound_to_resume_config(self) -> None:
        manager = TrelloSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TrelloResumeConfig


class TestSourceForPipeline:
    @parameterized.expand(
        [
            ("incremental", "actions", True, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            # The cursor value is dropped when the schema is not synced incrementally.
            ("full_refresh", "boards", False, "2026-01-01T00:00:00Z", None),
        ]
    )
    def test_plumbs_arguments(
        self,
        _name: str,
        schema_name: str,
        incremental: bool,
        last_value: str,
        expected_last_value: str | None,
    ) -> None:
        manager = mock.Mock()
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trello.source.trello_source"
        ) as trello_source:
            TrelloSource().source_for_pipeline(
                _config(),
                manager,
                _inputs(
                    schema_name=schema_name,
                    should_use_incremental_field=incremental,
                    db_incremental_field_last_value=last_value,
                ),
            )

        kwargs = trello_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == schema_name
        assert kwargs["should_use_incremental_field"] is incremental
        assert kwargs["db_incremental_field_last_value"] == expected_last_value
