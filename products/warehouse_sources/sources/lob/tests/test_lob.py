import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import unquote

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.sources.lob._config import LobSourceConfig
from products.warehouse_sources.sources.lob.lob import (
    LobResumeConfig,
    LobRetryableError,
    _fetch_page,
    _format_date_filter_value,
    _parse_date_created,
    validate_credentials,
)
from products.warehouse_sources.sources.lob.source import LobSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network


def _make_response(json_body: dict[str, Any] | None = None, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body or {}).encode()
    return resp


def _driver() -> SourceDriver:
    return SourceDriver(LobSource(), LobSourceConfig(api_key="k"))


class TestFormatDateFilterValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "cursor", "cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_date_filter_value(value) == expected


class TestParseDateCreated:
    @parameterized.expand(
        [
            ("z_suffix", "2019-08-08T17:09:14.514Z", datetime(2019, 8, 8, 17, 9, 14, 514000, tzinfo=UTC)),
            ("offset", "2019-08-08T17:09:14+00:00", datetime(2019, 8, 8, 17, 9, 14, tzinfo=UTC)),
            ("garbage", "not-a-date", None),
            ("non_string", 12345, None),
        ]
    )
    def test_parse(self, _name: str, value: object, expected: datetime | None) -> None:
        assert _parse_date_created(value) == expected


class TestGetRows:
    def test_stops_on_empty_data(self) -> None:
        result = _driver().run("letters", [ScriptedResponse(json={"data": []})])

        assert result.items == []
        assert result.saved_states == []
        assert result.params("limit") == ["100"]
        assert result.raised is None

    def test_resumes_from_saved_next_url(self) -> None:
        result = _driver().run(
            "letters",
            [
                ScriptedResponse(
                    json={"data": [{"id": "ltr_9", "date_created": "2026-01-09T00:00:00Z"}], "next_url": None}
                )
            ],
            resume_state=LobResumeConfig(next_url="https://api.lob.com/v1/letters?after=saved"),
        )

        assert result.urls == ["https://api.lob.com/v1/letters?after=saved"]
        assert [row["id"] for row in result.rows] == ["ltr_9"]
        assert result.raised is None

    def test_incremental_watermark_guard_stops_when_page_predates_watermark(self) -> None:
        # Defends against the cursor dropping the time filter on later pages: every row here predates
        # the watermark, and there is still a next_url, so pagination must stop instead of walking back.
        result = _driver().run(
            "letters",
            [
                ScriptedResponse(
                    json={
                        "data": [{"id": "ltr_old", "date_created": "2020-01-01T00:00:00Z"}],
                        "next_url": "https://api.lob.com/v1/letters?after=cursor",
                    }
                )
            ],
            incremental_field="date_created",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        # The page is still yielded (merge dedupes), but we stop before following the next_url.
        assert [row["id"] for row in result.rows] == ["ltr_old"]
        assert result.paths == ["/v1/letters"]
        assert result.saved_states == []
        assert result.raised is None

    def test_full_refresh_endpoint_ignores_watermark_guard(self) -> None:
        # Full-refresh endpoints have no incremental support, so the watermark guard never engages
        # even if a stale last-value is passed in.
        result = _driver().run(
            "addresses",
            [
                ScriptedResponse(
                    json={
                        "data": [{"id": "adr_1", "date_created": "2020-01-01T00:00:00Z"}],
                        "next_url": "https://api.lob.com/v1/addresses?after=c",
                    }
                ),
                ScriptedResponse(json={"data": [{"id": "adr_2", "date_created": "2019-01-01T00:00:00Z"}]}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert [row["id"] for row in result.rows] == ["adr_1", "adr_2"]
        assert result.paths == ["/v1/addresses", "/v1/addresses"]
        assert result.params("after") == [None, "c"]
        assert result.raised is None

    @parameterized.expand(
        [
            (
                "offset_walk_keeps_filters_and_stops_on_short_page",
                "billing_groups",
                [
                    {"data": [{"id": f"bg_{i}"} for i in range(100)]},
                    {"data": [{"id": "bg_last"}]},
                ],
                [
                    "https://api.lob.com/v1/billing_groups?limit=100&sort_by[date_created]=asc"
                    "&date_created[gt]=2026-01-01T00:00:00.000000Z",
                    "https://api.lob.com/v1/billing_groups?limit=100&sort_by[date_created]=asc"
                    "&date_created[gt]=2026-01-01T00:00:00.000000Z&offset=100",
                ],
                101,
            ),
            (
                "bare_array_is_a_single_page",
                "uploads",
                [[{"id": "upl_1"}, {"id": "upl_2"}]],
                ["https://api.lob.com/v1/uploads"],
                2,
            ),
        ]
    )
    def test_pagination_modes(
        self, _name: str, endpoint: str, pages: list[Any], expected_urls: list[str], expected_rows: int
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=page) for page in pages],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [unquote(url) for url in result.urls] == expected_urls
        assert len(result.rows) == expected_rows


LOB = "https://api.lob.com/v1"


class TestFanOutRows:
    @parameterized.expand(
        [
            (
                "card_orders_walks_every_parent_page_and_skips_empty_children",
                "card_orders",
                [
                    {"data": [{"id": "card_a"}, {"id": "card_b"}], "next_url": f"{LOB}/cards?after=p2"},
                    {"data": [{"id": "co_1", "card_id": "card_a"}]},
                    {"data": []},
                    {"data": [{"id": "card_c"}]},
                    {"data": [{"id": "co_2", "card_id": "card_c"}]},
                ],
                [
                    f"{LOB}/cards?limit=100",
                    f"{LOB}/cards/card_a/orders?limit=100",
                    f"{LOB}/cards/card_b/orders?limit=100",
                    f"{LOB}/cards?after=p2",
                    f"{LOB}/cards/card_c/orders?limit=100",
                ],
                [("co_1", "card_a"), ("co_2", "card_c")],
                LobResumeConfig(parent_url=f"{LOB}/cards?after=p2", parent_id="card_c"),
            ),
            (
                "template_versions_follow_child_cursor_and_stamp_template_id",
                "template_versions",
                [
                    {"data": [{"id": "tmpl_a"}]},
                    {"data": [{"id": "vrsn_1"}], "next_url": f"{LOB}/templates/tmpl_a/versions?after=v2"},
                    {"data": [{"id": "vrsn_2"}]},
                ],
                [
                    f"{LOB}/templates?limit=100",
                    f"{LOB}/templates/tmpl_a/versions?limit=100",
                    f"{LOB}/templates/tmpl_a/versions?after=v2",
                ],
                [("vrsn_1", "tmpl_a"), ("vrsn_2", "tmpl_a")],
                LobResumeConfig(parent_url=f"{LOB}/templates?limit=100", parent_id="tmpl_a"),
            ),
        ]
    )
    def test_walk(
        self,
        _name: str,
        endpoint: str,
        pages: list[Any],
        expected_urls: list[str],
        expected_rows: list[tuple[str, str]],
        expected_final_state: LobResumeConfig,
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=page) for page in pages])

        assert result.raised is None
        assert result.urls == expected_urls
        parent_field = "card_id" if endpoint == "card_orders" else "template_id"
        assert [(row["id"], row[parent_field]) for row in result.rows] == expected_rows
        assert result.final_state == expected_final_state

    @parameterized.expand(
        [
            (
                "mid_parent_resumes_at_child_cursor",
                LobResumeConfig(
                    next_url=f"{LOB}/templates/tmpl_b/versions?after=v9",
                    parent_url=f"{LOB}/templates?after=p3",
                    parent_id="tmpl_b",
                ),
                [f"{LOB}/templates/tmpl_b/versions?after=v9", f"{LOB}/templates/tmpl_c/versions?limit=100"],
            ),
            (
                "finished_parent_continues_with_the_next_one",
                LobResumeConfig(parent_url=f"{LOB}/templates?after=p3", parent_id="tmpl_b"),
                [f"{LOB}/templates/tmpl_c/versions?limit=100"],
            ),
            (
                "deleted_parent_restarts_the_page",
                LobResumeConfig(
                    next_url=f"{LOB}/templates/tmpl_gone/versions?after=v9",
                    parent_url=f"{LOB}/templates?after=p3",
                    parent_id="tmpl_gone",
                ),
                [
                    f"{LOB}/templates/tmpl_a/versions?limit=100",
                    f"{LOB}/templates/tmpl_b/versions?limit=100",
                    f"{LOB}/templates/tmpl_c/versions?limit=100",
                ],
            ),
        ]
    )
    def test_resume(self, _name: str, resume_state: LobResumeConfig, expected_child_urls: list[str]) -> None:
        parent_page = {"data": [{"id": "tmpl_a"}, {"id": "tmpl_b"}, {"id": "tmpl_c"}]}
        child_pages = [{"data": [{"id": f"vrsn_{i}"}]} for i in range(len(expected_child_urls))]
        result = _driver().run(
            "template_versions",
            [ScriptedResponse(json=page) for page in [parent_page, *child_pages]],
            resume_state=resume_state,
        )

        assert result.raised is None
        assert result.urls == [f"{LOB}/templates?after=p3", *expected_child_urls]

    def test_top_level_resume_state_restarts_the_parent_walk(self) -> None:
        result = _driver().run(
            "card_orders",
            [ScriptedResponse(json={"data": []})],
            resume_state=LobResumeConfig(next_url=f"{LOB}/letters?after=stale"),
        )

        assert result.raised is None
        assert result.urls == [f"{LOB}/cards?limit=100"]


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _make_response({}, status=status)
        # Call the undecorated function so a single attempt raises immediately instead of
        # exercising tenacity's exponential backoff.
        with pytest.raises(LobRetryableError):
            _fetch_page.__wrapped__(session, "https://api.lob.com/v1/letters", "k", {}, MagicMock())  # type: ignore[attr-defined]

    def test_client_error_raises_for_status(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_response({"error": {"message": "bad"}}, status=401)
        with pytest.raises(Exception):
            _fetch_page(session, "https://api.lob.com/v1/letters", "k", {}, MagicMock())

    def test_uses_http_basic_auth_with_blank_password(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_response({"data": []})
        _fetch_page(session, "https://api.lob.com/v1/letters", "my_key", {}, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["auth"] == ("my_key", "")


class TestValidateCredentials:
    @parameterized.expand([("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            is_valid, status_code = validate_credentials("k")
        assert is_valid is expected_valid
        assert status_code == status
        assert network.requests_log[0].path == "/v1/addresses"
        assert network.requests_log[0].param("limit") == "1"


class TestLobSource:
    @parameterized.expand([("letters", "asc"), ("postcards", "asc"), ("addresses", "desc"), ("campaigns", "desc")])
    def test_sort_mode_matches_incremental_support(self, endpoint: str, expected_sort: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json={"data": []})])
        response = result.response
        assert response is not None
        assert result.raised is None
        assert response.sort_mode == expected_sort
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["date_created"]
        assert response.partition_mode == "datetime"
