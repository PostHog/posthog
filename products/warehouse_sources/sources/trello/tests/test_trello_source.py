from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.trello.source import TrelloSource


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
        assert kwargs["team_id"] == 1
        assert kwargs["job_id"] == "job-id"
        # The cursor value is plumbed only when the schema is synced incrementally.
        assert kwargs["db_incremental_field_last_value"] == expected_last_value
