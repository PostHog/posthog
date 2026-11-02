import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hoorayhr import (
    HoorayHRSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.hoorayhr import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.settings import HOORAYHR_BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.source import HoorayHRSource


class TestHoorayHRTransport:
    def test_time_off_yields_single_batch_with_bearer_auth(self) -> None:
        result = SourceDriver(HoorayHRSource(), HoorayHRSourceConfig(api_key="pk_test_key")).run(
            "time_off", [ScriptedResponse(json=[{"id": 1}, {"id": 2}])]
        )

        assert result.raised is None
        assert result.items == [[{"id": 1}, {"id": 2}]]
        # No pagination anywhere on HoorayHR's API — exactly one request per endpoint.
        assert len(result.requests) == 1
        assert result.urls == [f"{HOORAYHR_BASE_URL}/time-off"]
        assert result.requests[0].headers["authorization"] == "Bearer pk_test_key"

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_public_holidays_fetches_each_year_and_merges_policy_duplicates(self) -> None:
        result = SourceDriver(HoorayHRSource(), HoorayHRSourceConfig(api_key="pk_test_key")).run(
            "public_holidays",
            [
                ScriptedResponse(json=[]),
                ScriptedResponse(
                    json=[
                        {"id": 7, "name": "New Year", "date": "2026-01-01", "userIds": [1, 2]},
                        {"id": 7, "name": "New Year", "date": "2026-01-01", "userIds": [2, 3]},
                        {"id": 8, "name": "Kings Day", "date": "2026-04-27", "userIds": [1]},
                    ]
                ),
                ScriptedResponse(json=[{"id": 7, "name": "New Year", "date": "2027-01-01", "userIds": [1]}]),
            ],
        )

        assert result.raised is None
        assert result.items == [
            [
                {"id": 7, "name": "New Year", "date": "2026-01-01", "userIds": [1, 2, 3]},
                {"id": 8, "name": "Kings Day", "date": "2026-04-27", "userIds": [1]},
            ],
            [{"id": 7, "name": "New Year", "date": "2027-01-01", "userIds": [1]}],
        ]
        assert result.queries == [
            {"date[$gte]": ("2025-01-01",), "date[$lte]": ("2025-12-31",)},
            {"date[$gte]": ("2026-01-01",), "date[$lte]": ("2026-12-31",)},
            {"date[$gte]": ("2027-01-01",), "date[$lte]": ("2027-12-31",)},
        ]
        assert result.paths == ["/public-holidays"] * 3
        assert all(request.origin == HOORAYHR_BASE_URL for request in result.requests)
        assert result.requests[0].headers["authorization"] == "Bearer pk_test_key"


class TestValidateCredentials:
    def test_connection_error_returns_false(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("pk_k") is False

        assert network.requests_log[0].path == "/leave-types"
