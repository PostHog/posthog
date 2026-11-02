from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce import (
    BabelforceResumeConfig,
    _base_url,
    _build_params,
    _to_epoch,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.settings import (
    BABELFORCE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.source import BabelforceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.babelforce import (
    BabelforceSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        BabelforceSource(), BabelforceSourceConfig(environment="services", access_id="id", access_token="token")
    )


def _page(items: list[dict[str, Any]], current: Optional[int], pages: Optional[int]) -> ScriptedResponse:
    pagination: dict[str, Any] = {"total": 0, "max": 100}
    if current is not None:
        pagination["current"] = current
    if pages is not None:
        pagination["pages"] = pages
    return ScriptedResponse(json={"items": items, "pagination": pagination})


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            ("2023-11-14T22:13:20.000Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-date", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestEnvironmentValidation:
    def test_base_url_rejects_invalid_environment(self):
        with pytest.raises(ValueError):
            _base_url("evil.example.com")


class TestBuildParams:
    def test_full_refresh_endpoint_never_gets_window(self):
        params = _build_params(BABELFORCE_ENDPOINTS["agents"], from_timestamp=1700000000, to_timestamp=1700000100)
        assert "dateCreated.start" not in params
        assert "dateCreated.end" not in params


class TestSessionHardening:
    def test_sessions_redact_credentials_and_disable_redirects_and_capture(self) -> None:
        # The token rides a custom header the sampler's denylist doesn't know and that requests
        # would forward on a cross-host redirect; dropping any of these would leak a usable
        # credential into HTTP samples or to a redirect target. Both the validation probe and the
        # sync path must build the session with all three protections.
        with scripted_network([_page([], current=1, pages=1)]) as network:
            assert validate_credentials("services", "id", "token") is True
        result = _driver().run("agents", [_page([], current=1, pages=1)])

        assert result.raised is None
        options = [*network.session_options, *result.session_options]
        assert len(options) >= 2
        for option in options:
            assert option["redact_values"] == ("id", "token")
            assert option["allow_redirects"] is False
            assert option["capture"] is False


class TestPagination:
    def test_paginates_until_last_page(self) -> None:
        result = _driver().run(
            "agents",
            [
                _page([{"id": "1"}, {"id": "2"}], current=1, pages=2),
                _page([{"id": "3"}], current=2, pages=2),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        # First request omits `page` (first-page index is undocumented); second requests page 2.
        assert result.params("page") == [None, "2"]
        # State is saved only while a next page exists.
        assert len(result.saved_states) == 1
        assert result.saved_states[0].next_page == 2

    def test_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "calls",
            [_page([{"id": "9"}], current=5, pages=5)],
            resume_state=BabelforceResumeConfig(next_page=5, params={"max": 100, "dateCreated.end": 1700000100}),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["9"]
        # The saved window and page are reused so the resumed run continues the same query.
        assert result.params("page") == ["5"]
        assert result.params("dateCreated.end") == ["1700000100"]

    def test_terminates_when_page_param_is_ignored(self) -> None:
        # If the server ignores `page` and re-serves the same page, the paginator detects the
        # non-advancing `current` and stops — preventing an infinite loop. The repeated page is
        # deduped downstream by primary key.
        result = _driver().run(
            "sms", [_page([{"id": "1"}], current=1, pages=3), _page([{"id": "1"}], current=1, pages=3)]
        )

        assert result.raised is None
        assert len(result.requests) == 2
        assert [row["id"] for row in result.rows] == ["1", "1"]

    def test_stops_when_pagination_current_missing(self) -> None:
        result = _driver().run("agents", [_page([{"id": "1"}], current=None, pages=None)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1"]
        assert len(result.requests) == 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.time")
    def test_incremental_run_windows_the_query(self, mock_time: mock.MagicMock) -> None:
        mock_time.time.return_value = 1700000100
        result = _driver().run(
            "calls",
            [_page([{"id": "1"}], current=1, pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2023-11-14T22:13:20.000Z",
        )

        assert result.raised is None
        assert result.params("dateCreated.start") == ["1700000000"]
        assert result.params("dateCreated.end") == ["1700000100"]


class TestBabelforceSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = BABELFORCE_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_page([], current=1, pages=1)])
        assert result.raised is None
        response = result.response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Reporting order is undocumented, so the watermark must only finalize on completion.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


# Each fan-out child, the path its parent id resolves into, and the field that id is injected as.
FANOUT_CASES = [
    ("conversation_events", "/conversations/p1/events", "conversationId"),
    ("outbound_leads", "/outbound/lists/p1/leads", "listId"),
    ("outbound_campaign_statistics", "/outbound/campaigns/p1/statistics", "campaignId"),
]


class TestFanout:
    @pytest.mark.parametrize("endpoint, child_path, parent_key", FANOUT_CASES)
    def test_child_rows_carry_the_parent_key(self, endpoint: str, child_path: str, parent_key: str) -> None:
        # Child rows are keyed by their parent, so the injected field has to be the one the
        # primary key names - otherwise rows from different parents collide on merge.
        result = _driver().run(
            endpoint,
            [_page([{"id": "p1"}], current=1, pages=1), _page([{"probe": "row"}], current=1, pages=1)],
        )

        assert result.raised is None
        assert result.paths[1].endswith(child_path)
        assert result.rows == [{"probe": "row", parent_key: "p1"}]
        assert parent_key in BABELFORCE_ENDPOINTS[endpoint].primary_keys

    def test_unpaginated_fan_out_reads_one_page_without_paging_params(self) -> None:
        # Both pages advertise more to come. The outbound endpoints document no `pagination`
        # object and take no `page`/`max` params, so neither is sent and neither is followed.
        result = _driver().run(
            "outbound_leads", [_page([{"id": "l1"}], current=1, pages=3), _page([{"id": "d1"}], current=1, pages=3)]
        )

        assert result.raised is None
        assert result.queries == [{}, {}]
        assert len(result.requests) == 2
        assert [row["id"] for row in result.rows] == ["d1"]

    def test_fan_out_checkpoints_each_parent(self) -> None:
        result = _driver().run(
            "conversation_events",
            [
                _page([{"id": "c1"}, {"id": "c2"}], current=1, pages=1),
                _page([{"id": "e1"}], current=1, pages=1),
                _page([{"id": "e2"}], current=1, pages=1),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["e1", "e2"]
        assert result.saved_states[-1].fanout["completed"] == [
            "/conversations/c1/events",
            "/conversations/c2/events",
        ]

    def test_fan_out_resume_skips_completed_parents(self) -> None:
        result = _driver().run(
            "conversation_events",
            [
                _page([{"id": "c1"}, {"id": "c2"}], current=1, pages=1),
                _page([{"id": "e2"}], current=1, pages=1),
            ],
            resume_state=BabelforceResumeConfig(
                fanout={"completed": ["/conversations/c1/events"], "current": None, "child_state": None}
            ),
        )

        # The parent list is re-read, but only the unfinished conversation is fetched again.
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["e2"]
        assert result.paths == ["/api/v2/conversations", "/api/v2/conversations/c2/events"]
