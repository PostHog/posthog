from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tvmaze import TVMazeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.source import TVMazeSource


class TestTVMazeSource:
    def setup_method(self) -> None:
        self.source = TVMazeSource()
        self.team_id = 123
        self.config = TVMazeSourceConfig()

    def test_get_non_retryable_errors_covers_auth_rejections(self) -> None:
        # A 401/403 from the public API is an IP-level block that a retry can't
        # fix, so it must be classified non-retryable rather than looping forever.
        errors = self.source.get_non_retryable_errors()
        assert set(errors) == {"401 Client Error", "403 Client Error"}
        assert all(message for message in errors.values())
