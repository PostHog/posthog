from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail import (
    CallRailResumeConfig,
    _format_start_date,
    resolve_account_id,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.settings import (
    CALLRAIL_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source import CallRailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.callrail import (
    CallRailSourceConfig,
)


def _driver(account_id: str | None = "ACC") -> SourceDriver:
    return SourceDriver(CallRailSource(), CallRailSourceConfig(api_key="key", account_id=account_id))


def _page(response_key: str, items: list[dict[str, Any]], total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(json={response_key: items, "total_pages": total_pages, "total_records": 999})


def _accounts(ids: list[str]) -> ScriptedResponse:
    return ScriptedResponse(json={"accounts": [{"id": account_id} for account_id in ids]})


class TestFormatStartDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2026, 3, 4, 22, 13, 20, tzinfo=UTC), "2026-03-04"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T22:13:20Z", "2026-03-04"),
            ("", None),
        ],
    )
    def test_format_start_date(self, value: Any, expected: str | None) -> None:
        assert _format_start_date(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        attempts = 4 if status_code == 500 else 1
        with scripted_network([ScriptedResponse(status=status_code)] * attempts) as network:
            assert validate_credentials("key") is expected

        assert len(network.requests_log) == attempts
        assert network.requests_log[0].path == "/v3/a.json"
        assert network.requests_log[0].param("per_page") == "1"


class TestResolveAccountId:
    def test_raises_when_no_accounts(self) -> None:
        with scripted_network([_accounts([])]) as network:
            with pytest.raises(ValueError):
                resolve_account_id("key", 1, "j")

        assert network.requests_log[0].path == "/v3/a.json"


class TestGetRows:
    def test_paginates_by_page_number(self) -> None:
        result = _driver().run(
            "calls",
            [
                _page("calls", [{"id": "1"}, {"id": "2"}], total_pages=2),
                _page("calls", [{"id": "3"}], total_pages=2),
            ],
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["1", "2", "3"]
        assert result.params("page") == ["1", "2"]
        assert result.params("per_page") == ["250", "250"]
        # State saved once (after page 1, pointing at page 2); page 2 is the last so no save after it.
        assert result.saved_states == [CallRailResumeConfig(account_id="ACC", page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "calls",
            [_page("calls", [{"id": "9"}], total_pages=5)],
            resume_state=CallRailResumeConfig(account_id="ACC9", page=5),
        )

        # Resumes at the saved page and pinned account, ignoring the passed account_id, and
        # without re-resolving accounts.
        assert result.raised is None
        assert len(result.requests) == 1
        assert result.params("page") == ["5"]
        assert "/a/ACC9/" in result.urls[0]

    def test_resolves_account_when_not_resuming(self) -> None:
        result = _driver(account_id=None).run(
            "users",
            [
                _accounts(["RESOLVED"]),
                _page("users", [{"id": "u1"}], total_pages=1),
            ],
        )

        assert result.raised is None
        assert "/a/RESOLVED/users.json" in result.urls[1]

    def test_start_date_omitted_when_last_value_missing(self) -> None:
        result = _driver().run(
            "calls",
            [_page("calls", [{"id": "1"}], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert result.requests[0].param("start_date") is None


class TestCallRailSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = CALLRAIL_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [ScriptedResponse(json={"total_pages": 1})])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(CALLRAIL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: Any) -> None:
        # Never partition on a mutable field; only stable creation/start timestamps are allowed.
        if config.partition_key:
            assert config.partition_key in {"start_time", "submitted_at", "created_at", "event_date"}

    @pytest.mark.parametrize("config", list(CALLRAIL_ENDPOINTS.values()))
    def test_incremental_endpoints_have_a_sort_field(self, config: Any) -> None:
        # An incremental endpoint must sort ascending on its cursor so the watermark advances.
        if config.supports_incremental:
            assert config.sort_field is not None
            assert config.incremental_fields


class TestAccountsEndpoint:
    def test_accounts_needs_no_account_resolution(self) -> None:
        result = _driver(account_id=None).run("accounts", [_page("accounts", [{"id": "ACC1"}], total_pages=1)])

        # /a.json is the one endpoint not nested under an account, so the listing is the only request.
        assert result.raised is None
        assert len(result.requests) == 1
        assert result.paths == ["/v3/a.json"]
        assert result.params("sort") == ["name"]


class TestLeadsEndpoint:
    def test_leads_sorts_ascending_and_never_sends_a_date_filter(self) -> None:
        result = _driver().run(
            "leads",
            [_page("leads", [{"id": "L1"}], total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("sort") == ["created_at"]
        assert result.params("order") == ["asc"]
        # CallRail's date filters cover calls, the call summary, and conversations only.
        assert result.requests[0].param("start_date") is None


def _page_view(page_url: str, created_at: str) -> dict[str, Any]:
    return {"referrer_url": "https://example.com/", "page_url": page_url, "created_at": created_at}


_CALLS_PARENT = [{"id": "C1"}, {"id": "C2"}]
_C1_PATH = "/a/ACC/calls/C1/page_views.json"
_C2_PATH = "/a/ACC/calls/C2/page_views.json"


class TestFanoutEndpoints:
    def test_page_views_fan_out_injects_the_parent_call_id(self) -> None:
        result = _driver().run(
            "page_views",
            [
                _page("calls", _CALLS_PARENT, total_pages=1),
                _page("page_views", [_page_view("https://example.com/a", "2026-01-01T00:00:00Z")], total_pages=1),
                _page("page_views", [_page_view("https://example.com/b", "2026-01-02T00:00:00Z")], total_pages=1),
            ],
        )

        assert result.raised is None
        assert [row["call_id"] for row in result.rows] == ["C1", "C2"]
        # Page-view rows carry no id, so call_id is part of the primary key and must not stay
        # under the framework's `_{parent}_{field}` prefix.
        assert not any(key.startswith("_calls_") for row in result.rows for key in row)
        assert _C1_PATH in result.urls[1]
        assert _C2_PATH in result.urls[2]
        assert result.requests[1].param("per_page") == "250"
        # The parent listing walks ascending by its own cursor field so its pagination is stable.
        assert result.requests[0].param("sort") == "start_time"
        # The endpoint takes no sort param of its own.
        assert result.requests[1].param("sort") is None

    def test_fan_out_child_never_sends_a_date_filter(self) -> None:
        # The child endpoints take no date filter, so an incremental sync bounds its requests
        # through the parent listing and relies on the merge to keep earlier rows.
        result = _driver().run(
            "page_views",
            [
                _page("calls", [{"id": "C1"}], total_pages=1),
                _page("page_views", [_page_view("https://example.com/a", "2026-01-01T00:00:00Z")], total_pages=1),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param("start_date") is None
        assert result.requests[1].param("created_at") is None
