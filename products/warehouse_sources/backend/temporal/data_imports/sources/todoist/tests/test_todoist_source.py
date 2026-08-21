from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.todoist import (
    TodoistSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.source import TodoistSource


class TestTodoistSource:
    def setup_method(self) -> None:
        self.source = TodoistSource()
        self.team_id = 123
        self.config = TodoistSourceConfig(api_token="tok-test")

    def test_validate_credentials_success(self) -> None:
        with mock.patch.object(source_module, "validate_todoist_credentials", return_value=True) as probe:
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is True
        assert error is None
        probe.assert_called_once_with("tok-test")

    def test_validate_credentials_failure(self) -> None:
        with mock.patch.object(source_module, "validate_todoist_credentials", return_value=False):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert error == "Invalid Todoist API token"
