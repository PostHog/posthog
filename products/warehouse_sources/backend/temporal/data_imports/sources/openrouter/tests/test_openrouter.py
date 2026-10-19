from datetime import UTC, date, datetime, timedelta

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openrouter import (
    OpenRouterSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter import openrouter
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.openrouter import (
    OpenRouterResumeConfig,
    _to_date,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.settings import ACTIVITY_RETENTION_DAYS
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.source import OpenRouterSource


def _response(status_code: int, body: dict | None = None, text: str = "") -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.text = text
    response.json.return_value = body or {}
    response.request = None
    if not response.ok:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} Client Error for url: https://openrouter.ai", response=response
        )
    return response


def _driver() -> SourceDriver:
    return SourceDriver(OpenRouterSource(), OpenRouterSourceConfig(api_key="sk-or-x"))


class TestFetch:
    @pytest.fixture(autouse=True)
    def _instant_retry(self):
        # Zero the tenacity backoff so retry tests don't actually sleep.
        with mock.patch.object(openrouter._fetch.retry, "wait", return_value=0):  # type: ignore[attr-defined]
            yield

    @pytest.mark.parametrize("status_code", [408, 429, 500, 502, 503])
    def test_retries_then_succeeds_on_transient_status(self, status_code):
        session = mock.Mock()
        session.get.side_effect = [_response(status_code), _response(200, {"data": []})]

        result = openrouter._fetch(session, "https://openrouter.ai/api/v1/models", {}, mock.Mock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_client_errors_raise(self, status_code):
        session = mock.Mock()
        session.get.return_value = _response(status_code, text="nope")

        with pytest.raises(requests.exceptions.HTTPError):
            openrouter._fetch(session, "https://openrouter.ai/api/v1/keys", {}, mock.Mock())


class TestGetKeyInfo:
    def test_returns_data_on_200(self):
        with scripted_network([ScriptedResponse(json={"data": {"is_management_key": True}})]) as network:
            assert openrouter.get_key_info("sk-or-x") == {"is_management_key": True}
        assert network.requests_log[0].path == "/api/v1/key"
        assert network.requests_log[0].headers["authorization"] == "Bearer sk-or-x"

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    def test_returns_none_on_non_200(self, status_code):
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert openrouter.get_key_info("sk-or-x") is None
        assert network.requests_log[0].path == "/api/v1/key"

    def test_validate_credentials_wraps_get_key_info(self):
        with mock.patch.object(openrouter, "get_key_info", return_value={"is_management_key": False}):
            assert openrouter.validate_credentials("sk-or-x") is True
        with mock.patch.object(openrouter, "get_key_info", return_value=None):
            assert openrouter.validate_credentials("sk-or-x") is False


class TestToDate:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2026-06-15", date(2026, 6, 15)),
            ("2026-06-15T12:00:00Z", date(2026, 6, 15)),
            (date(2026, 6, 15), date(2026, 6, 15)),
            (datetime(2026, 6, 15, 8, tzinfo=UTC), date(2026, 6, 15)),
            ("not-a-date", None),
            (None, None),
        ],
    )
    def test_coercion(self, value, expected):
        assert _to_date(value) == expected


class TestActivityRows:
    def test_pulls_each_day_and_saves_state_after_yield(self):
        row = {"date": "2026-06-01", "endpoint_id": "e1"}
        result = _driver().run("activity", [ScriptedResponse(json={"data": [row]})] * ACTIVITY_RETENTION_DAYS)

        assert result.raised is None
        assert result.items == [[row]] * ACTIVITY_RETENTION_DAYS
        assert len(result.requests) == ACTIVITY_RETENTION_DAYS
        assert all(request.param("date") is not None for request in result.requests)
        # State saved once per day, after each yield.
        assert result.saved_states == [OpenRouterResumeConfig(date=day) for day in result.params("date")]

    def test_resume_skips_already_completed_days(self):
        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        already_done = yesterday - timedelta(days=1)

        result = _driver().run(
            "activity",
            [ScriptedResponse(json={"data": []})],
            resume_state=OpenRouterResumeConfig(date=already_done.isoformat()),
            should_use_incremental_field=True,
            db_incremental_field_last_value=(yesterday - timedelta(days=10)).isoformat(),
        )

        # Only the day after the completed bookmark (yesterday) is fetched.
        assert result.raised is None
        assert result.params("date") == [yesterday.isoformat()]


class TestOffsetPagination:
    def test_offset_limit_stops_on_short_page(self):
        # organization_members sends `limit`, so a page shorter than the limit is the last page.
        page1 = [{"id": f"m{i}"} for i in range(100)]
        page2 = [{"id": "m100"}]
        result = _driver().run(
            "organization_members", [ScriptedResponse(json={"data": page1}), ScriptedResponse(json={"data": page2})]
        )

        assert result.raised is None
        assert result.items == [page1, page2]
        assert result.params("offset") == ["0", "100"]
        # State saved after the first full page, not after the short page.
        assert result.saved_states == [OpenRouterResumeConfig(offset=100)]

    @pytest.mark.parametrize(
        "endpoint,include_inactive",
        [("organization_members", [None]), ("end_users", ["true"])],
    )
    def test_offset_limit_endpoints_send_limit(self, endpoint, include_inactive):
        result = _driver().run(endpoint, [ScriptedResponse(json={"data": []})])

        assert result.raised is None
        assert result.params("limit") == ["100"]
        assert result.params("include_inactive") == include_inactive


class TestCursorPagination:
    def test_batches_follow_last_id_until_has_more_is_false(self):
        page1 = [{"id": "b3"}, {"id": "b2"}]
        page2 = [{"id": "b1"}]
        result = _driver().run(
            "batches",
            [
                ScriptedResponse(json={"data": page1, "has_more": True, "last_id": "b2"}),
                ScriptedResponse(json={"data": page2, "has_more": False, "last_id": "b1"}),
            ],
        )

        assert result.raised is None
        assert result.items == [page1, page2]
        assert result.params("after") == [None, "b2"]
        assert result.params("limit") == ["100", "100"]
        assert result.saved_states == [OpenRouterResumeConfig(after="b2")]

    def test_batches_fail_when_page_cap_leaves_pages_unread(self):
        with mock.patch.object(openrouter, "MAX_PAGES", 2):
            result = _driver().run(
                "batches",
                [
                    ScriptedResponse(json={"data": [{"id": "b3"}], "has_more": True, "last_id": "b3"}),
                    ScriptedResponse(json={"data": [{"id": "b2"}], "has_more": True, "last_id": "b2"}),
                ],
            )

        assert isinstance(result.raised, openrouter.OpenRouterPageCapError)

    def test_batches_resume_from_saved_cursor(self):
        result = _driver().run(
            "batches",
            [ScriptedResponse(json={"data": [{"id": "b1"}], "has_more": False, "last_id": "b1"})],
            resume_state=OpenRouterResumeConfig(after="b2"),
        )

        assert result.raised is None
        assert result.params("after") == ["b2"]


class TestSingleAndSingleton:
    def test_models_yields_list(self):
        rows = [{"id": "a"}, {"id": "b"}]
        result = _driver().run("models", [ScriptedResponse(json={"data": rows})])
        assert result.raised is None
        assert result.items == [rows]

    def test_credits_singleton_wrapped_in_list(self):
        row = {"total_credits": 10, "total_usage": 3}
        result = _driver().run("credits", [ScriptedResponse(json={"data": row})])
        assert result.raised is None
        assert result.items == [[row]]


class TestSourceResponse:
    def test_activity_partitions_on_date(self):
        yesterday = datetime.now(UTC).date() - timedelta(days=1)
        result = _driver().run(
            "activity",
            [ScriptedResponse(json={"data": []})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=yesterday.isoformat(),
        )
        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["date"]
