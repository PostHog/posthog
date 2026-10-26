from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rkicovid import (
    RKICovidSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.source import RKICovidSource


def _make_config(history_days: int | None = None) -> RKICovidSourceConfig:
    return RKICovidSourceConfig(history_days=history_days)


class TestRKICovidSource:
    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert RKICovidSource.lists_tables_without_credentials is True

    def test_validate_credentials_rejects_invalid_days_without_probing(self) -> None:
        with scripted_network([]) as network:
            ok, message = RKICovidSource().validate_credentials(_make_config(0), team_id=1)
        assert ok is False
        assert message is not None and "History window" in message
        assert network.requests_log == []

    def test_source_for_pipeline_plumbs_endpoint_and_history_days(self) -> None:
        result = SourceDriver(RKICovidSource(), _make_config(30)).run(
            "germany_history_cases", [ScriptedResponse(json={"data": [], "meta": {}})]
        )
        assert result.paths == ["/germany/history/cases/30"]

    def test_source_for_pipeline_rejects_invalid_history_days(self) -> None:
        # A previously-saved bad config must fail the run loudly instead of syncing a wrong window.
        result = SourceDriver(RKICovidSource(), _make_config(-1)).run("germany_history_cases", [])
        assert isinstance(result.raised, ValueError)
        assert "History window" in str(result.raised)
        assert result.requests == []
