from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.debugbear import (
    _date_only,
    _flatten_page_metrics_item,
    _flatten_rum_metrics,
    _iter_annotations_for_project,
    _iter_page_metrics_for_project,
    _iter_pages,
    _iter_projects,
    _iter_rum_metrics_for_project,
    _iter_rum_page_views_for_project,
    _parse_datetime,
    debugbear_source,
    validate_credentials,
)


def _response(json_body: Any, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    if status_code >= 400:
        response.raise_for_status.side_effect = HTTPError(f"{status_code} Client Error", response=response)
    else:
        response.raise_for_status.side_effect = None
    return response


class TestFlattenPageMetricsItem:
    def test_flattens_dotted_metric_keys(self) -> None:
        project = {"id": "p1", "name": "My Project"}
        item = {
            "page": {"id": "pg1", "name": "Homepage", "url": "https://example.com"},
            "metrics": {"analysis.date": "2024-01-10T00:00:00.000Z", "performance.score": 0.96},
        }

        row = _flatten_page_metrics_item(project, item)

        assert row == {
            "project_id": "p1",
            "project_name": "My Project",
            "page_id": "pg1",
            "page_name": "Homepage",
            "page_url": "https://example.com",
            "analysis_date": "2024-01-10T00:00:00.000Z",
            "performance_score": 0.96,
        }

    def test_missing_page_id_returns_none(self) -> None:
        project = {"id": "p1"}
        item = {"page": {"name": "Homepage"}, "metrics": {"analysis.date": "2024-01-10T00:00:00.000Z"}}

        assert _flatten_page_metrics_item(project, item) is None

    def test_missing_analysis_date_returns_none(self) -> None:
        project = {"id": "p1"}
        item = {"page": {"id": "pg1"}, "metrics": {"performance.score": 0.9}}

        assert _flatten_page_metrics_item(project, item) is None

    def test_missing_page_and_metrics_keys_handled_gracefully(self) -> None:
        assert _flatten_page_metrics_item({"id": "p1"}, {}) is None


class TestDateOnly:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2024-01-10T19:06:42.201Z", "2024-01-10"),
            ("2024-01-10", "2024-01-10"),
            ("", None),
        ],
    )
    def test_date_only(self, value: str, expected: str | None) -> None:
        assert _date_only(value) == expected


class TestParseDatetime:
    def test_parses_iso_string(self) -> None:
        parsed = _parse_datetime("2024-01-10T19:06:42.201Z")
        assert parsed == datetime(2024, 1, 10, 19, 6, 42, 201000, tzinfo=UTC)

    def test_invalid_string_returns_none(self) -> None:
        assert _parse_datetime("not-a-date") is None

    def test_none_returns_none(self) -> None:
        assert _parse_datetime(None) is None

    def test_datetime_passthrough(self) -> None:
        value = datetime(2024, 1, 1, tzinfo=UTC)
        assert _parse_datetime(value) == value


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.debugbear.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = _response([], status_code=status_code)
            is_valid, error = validate_credentials("test-key")

        assert is_valid is expected_valid
        if not expected_valid:
            assert error

    def test_request_exception_is_reported(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.debugbear.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.side_effect = RequestsConnectionError("boom")
            is_valid, error = validate_credentials("test-key")

        assert is_valid is False
        assert "boom" in str(error)


class TestSessionFactory:
    def test_session_disables_redirects_so_api_key_is_not_replayed(self) -> None:
        # The API key rides in a custom `x-api-key` header, which `requests` would replay
        # across a cross-origin redirect — so the tracked session must never follow redirects.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.debugbear.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = _response([])
            validate_credentials("test-key")

        mock_make_session.assert_called_once_with(redact_values=("test-key",), allow_redirects=False)


class TestIterProjects:
    def test_filters_non_dict_entries(self) -> None:
        session = MagicMock()
        session.get.return_value = _response([{"id": "p1"}, "unexpected", {"id": "p2"}])

        projects = _iter_projects(session, {})

        assert projects == [{"id": "p1"}, {"id": "p2"}]

    def test_non_list_response_returns_empty(self) -> None:
        session = MagicMock()
        session.get.return_value = _response({"error": "nope"})

        assert _iter_projects(session, {}) == []


class TestIterPageMetricsForProject:
    def test_walks_backward_until_empty_page(self) -> None:
        session = MagicMock()
        page1 = [
            {"page": {"id": "pg1"}, "metrics": {"analysis.date": "2024-01-10T00:00:00.000Z"}},
            {"page": {"id": "pg2"}, "metrics": {"analysis.date": "2024-01-08T00:00:00.000Z"}},
        ]
        page2 = [{"page": {"id": "pg1"}, "metrics": {"analysis.date": "2024-01-01T00:00:00.000Z"}}]
        session.get.side_effect = [_response(page1), _response(page2), _response([])]

        rows = list(_iter_page_metrics_for_project(session, {}, {"id": "proj1"}, stop_when_older_than=None))

        assert [row["page_id"] for row in rows] == ["pg1", "pg2", "pg1"]
        assert session.get.call_count == 3
        # First request has no `before`; the second and third walk backward using the
        # oldest date seen so far (date-only, per the documented `before=YYYY-MM-DD` param).
        sent_urls = [call.args[0] for call in session.get.call_args_list]
        assert "before" not in sent_urls[0]
        assert "before=2024-01-08" in sent_urls[1]
        assert "before=2024-01-01" in sent_urls[2]

    def test_stops_early_once_page_predates_watermark(self) -> None:
        session = MagicMock()
        page1 = [
            {"page": {"id": "pg1"}, "metrics": {"analysis.date": "2024-01-10T00:00:00.000Z"}},
            {"page": {"id": "pg2"}, "metrics": {"analysis.date": "2024-01-08T00:00:00.000Z"}},
        ]
        page2 = [{"page": {"id": "pg1"}, "metrics": {"analysis.date": "2024-01-05T00:00:00.000Z"}}]
        session.get.side_effect = [_response(page1), _response(page2)]
        watermark = datetime(2024, 1, 9, tzinfo=UTC)

        rows = list(_iter_page_metrics_for_project(session, {}, {"id": "proj1"}, stop_when_older_than=watermark))

        # Page 1's newest item (2024-01-10) is after the watermark, so we keep paginating and
        # yield it; page 2's newest item (2024-01-05) already predates the watermark, so its
        # rows are yielded (merge dedupes) but pagination stops there — no third request.
        assert len(rows) == 3
        assert session.get.call_count == 2

    def test_no_backward_progress_stops_pagination(self) -> None:
        session = MagicMock()
        # Every item lands on the same calendar day, so the day-granularity `before`
        # cursor can never move further back — must stop rather than loop forever.
        same_day_page = [
            {"page": {"id": "pg1"}, "metrics": {"analysis.date": "2024-01-05T10:00:00.000Z"}},
            {"page": {"id": "pg2"}, "metrics": {"analysis.date": "2024-01-05T08:00:00.000Z"}},
        ]
        session.get.side_effect = [_response(same_day_page), _response(same_day_page)]

        rows = list(_iter_page_metrics_for_project(session, {}, {"id": "proj1"}, stop_when_older_than=None))

        # Both pages are yielded (merge dedupes the repeat), but a third request never fires.
        assert session.get.call_count == 2
        assert len(rows) == 4

    def test_no_project_id_yields_nothing(self) -> None:
        session = MagicMock()

        rows = list(_iter_page_metrics_for_project(session, {}, {}, stop_when_older_than=None))

        assert rows == []
        session.get.assert_not_called()

    def test_page_with_no_usable_rows_stops(self) -> None:
        session = MagicMock()
        session.get.return_value = _response([{"page": {}, "metrics": {}}])

        rows = list(_iter_page_metrics_for_project(session, {}, {"id": "proj1"}, stop_when_older_than=None))

        assert rows == []
        assert session.get.call_count == 1


def _query(call: Any) -> dict[str, list[str]]:
    return parse_qs(urlparse(call.args[0]).query)


class TestIterPages:
    def test_flattens_pages_out_of_the_projects_listing(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(
            [
                {
                    "id": "p1",
                    "name": "My Project",
                    "pages": [
                        {"id": 999, "name": "Homepage", "url": "https://example.com"},
                        {"name": "No id"},
                        "unexpected",
                    ],
                },
                {"id": "p2", "name": "Empty", "pages": None},
            ]
        )

        rows = list(_iter_pages(session, {}))

        assert rows == [
            {
                "id": "999",
                "name": "Homepage",
                "url": "https://example.com",
                "project_id": "p1",
                "project_name": "My Project",
            }
        ]


class TestFlattenRumMetrics:
    def test_one_row_per_metric_bucket(self) -> None:
        payload = {
            "info": {"groupByTime": "day", "stat": "p75"},
            "lcp": [
                {"date": "2026-04-06T00:00:00.000Z", "count": 2, "value": 1400},
                {"date": "2026-04-07T00:00:00.000Z", "count": 1, "value": 2000},
            ],
            "cls": [{"date": "2026-04-06T00:00:00.000Z", "count": 2, "value": 0.01}],
        }

        rows = list(_flatten_rum_metrics({"project_id": "p1", "project_name": "Proj"}, payload))

        assert rows == [
            {
                "project_id": "p1",
                "project_name": "Proj",
                "metric": "lcp",
                "date": "2026-04-06T00:00:00.000Z",
                "value": 1400,
                "count": 2,
                "stat": "p75",
            },
            {
                "project_id": "p1",
                "project_name": "Proj",
                "metric": "lcp",
                "date": "2026-04-07T00:00:00.000Z",
                "value": 2000,
                "count": 1,
                "stat": "p75",
            },
            {
                "project_id": "p1",
                "project_name": "Proj",
                "metric": "cls",
                "date": "2026-04-06T00:00:00.000Z",
                "value": 0.01,
                "count": 2,
                "stat": "p75",
            },
        ]

    @pytest.mark.parametrize(
        "payload",
        [
            [],
            {"info": {"stat": "p75"}},
            {"lcp": [{"count": 2, "value": 1400}]},
            {"lcp": ["unexpected"]},
        ],
    )
    def test_unusable_payloads_yield_nothing(self, payload: Any) -> None:
        assert list(_flatten_rum_metrics({"project_id": "p1"}, payload)) == []


class TestIterRumMetricsForProject:
    def test_incremental_asks_the_server_for_rows_after_the_watermark(self) -> None:
        session = MagicMock()
        session.get.return_value = _response({"info": {"stat": "p75"}, "lcp": []})

        list(_iter_rum_metrics_for_project(session, {}, {"id": "p1"}, since=datetime(2026, 4, 6, 12, 30, tzinfo=UTC)))

        query = _query(session.get.call_args)
        assert query["from"] == ["2026-04-06T12:30:00Z"]
        assert query["groupByTime"] == ["day"]

    def test_full_refresh_asks_for_the_backfill_window(self) -> None:
        session = MagicMock()
        session.get.return_value = _response({"info": {"stat": "p75"}, "lcp": []})

        list(_iter_rum_metrics_for_project(session, {}, {"id": "p1"}, since=None))

        requested_from = _parse_datetime(_query(session.get.call_args)["from"][0])
        assert requested_from is not None
        assert abs((datetime.now(UTC) - requested_from) - timedelta(days=365)) < timedelta(minutes=5)

    def test_project_without_id_makes_no_request(self) -> None:
        session = MagicMock()

        assert list(_iter_rum_metrics_for_project(session, {}, {}, since=None)) == []
        session.get.assert_not_called()


class TestIterRumPageViewsForProject:
    def test_walks_backward_with_the_to_cutoff_until_empty(self) -> None:
        session = MagicMock()
        page1 = [
            {"path": "/", "date": "2026-04-14T20:30:15.000Z"},
            {"path": "/pricing", "date": "2026-04-14T18:00:00.000Z"},
        ]
        page2 = [{"path": "/", "date": "2026-04-13T09:00:00.000Z"}]
        session.get.side_effect = [_response(page1), _response(page2), _response([])]

        rows = list(_iter_rum_page_views_for_project(session, {}, {"id": "p1"}, since=None))

        assert [row["date"] for row in rows] == [
            "2026-04-14T20:30:15.000Z",
            "2026-04-14T18:00:00.000Z",
            "2026-04-13T09:00:00.000Z",
        ]
        queries = [_query(call) for call in session.get.call_args_list]
        assert "to" not in queries[0]
        assert queries[0]["count"] == ["5000"]
        assert queries[1]["to"] == ["2026-04-14T18:00:00.000Z"]
        assert queries[2]["to"] == ["2026-04-13T09:00:00.000Z"]

    def test_incremental_passes_the_watermark_as_from(self) -> None:
        session = MagicMock()
        session.get.side_effect = [_response([{"date": "2026-04-14T20:30:15.000Z"}]), _response([])]

        list(_iter_rum_page_views_for_project(session, {}, {"id": "p1"}, since=datetime(2026, 4, 14, tzinfo=UTC)))

        assert all(_query(call)["from"] == ["2026-04-14T00:00:00Z"] for call in session.get.call_args_list)

    def test_stops_when_the_oldest_row_does_not_move(self) -> None:
        session = MagicMock()
        page = [{"path": "/", "date": "2026-04-14T20:30:15.000Z"}]
        session.get.side_effect = [_response(page), _response(page)]

        rows = list(_iter_rum_page_views_for_project(session, {}, {"id": "p1"}, since=None))

        assert session.get.call_count == 2
        # The repeat is yielded, but its id matches the first row's so merge collapses them.
        assert len({row["id"] for row in rows}) == 1

    def test_synthesized_id_separates_different_page_views(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(
                [
                    {"path": "/", "device": "mobile", "date": "2026-04-14T20:30:15.000Z"},
                    {"path": "/", "device": "desktop", "date": "2026-04-14T20:30:15.000Z"},
                ]
            ),
            _response([]),
        ]

        rows = list(_iter_rum_page_views_for_project(session, {}, {"id": "p1"}, since=None))

        assert len({row["id"] for row in rows}) == 2

    def test_rows_without_a_date_are_skipped(self) -> None:
        session = MagicMock()
        session.get.return_value = _response([{"path": "/"}])

        assert list(_iter_rum_page_views_for_project(session, {}, {"id": "p1"}, since=None)) == []
        assert session.get.call_count == 1


class TestIterAnnotationsForProject:
    def test_reads_a_bare_list(self) -> None:
        session = MagicMock()
        session.get.return_value = _response([{"id": 7, "title": "V5 release", "date": "2026-04-14T20:30:15.000Z"}])

        rows = list(_iter_annotations_for_project(session, {}, {"id": "p1", "name": "Proj"}))

        assert rows == [
            {
                "id": "7",
                "title": "V5 release",
                "date": "2026-04-14T20:30:15.000Z",
                "project_id": "p1",
                "project_name": "Proj",
            }
        ]

    def test_reads_a_wrapped_list(self) -> None:
        session = MagicMock()
        session.get.return_value = _response({"annotations": [{"id": "7", "title": "V5 release"}]})

        rows = list(_iter_annotations_for_project(session, {}, {"id": "p1"}))

        assert [row["id"] for row in rows] == ["7"]

    def test_annotation_without_an_id_gets_a_content_id(self) -> None:
        session = MagicMock()
        session.get.return_value = _response([{"title": "V5 release"}, {"title": "V6 release"}])

        rows = list(_iter_annotations_for_project(session, {}, {"id": "p1"}))

        assert len({row["id"] for row in rows}) == 2

    @pytest.mark.parametrize("payload", [{"error": "nope"}, "unexpected"])
    def test_unusable_payloads_yield_nothing(self, payload: Any) -> None:
        session = MagicMock()
        session.get.return_value = _response(payload)

        assert list(_iter_annotations_for_project(session, {}, {"id": "p1"})) == []


class TestDebugbearSourceRouting:
    @pytest.mark.parametrize(
        ("endpoint", "name", "primary_keys", "sort_mode", "partition_keys"),
        [
            ("Projects", "projects", ["id"], "asc", None),
            ("Pages", "pages", ["project_id", "id"], "asc", None),
            (
                "PageMetrics",
                "page_metrics",
                ["project_id", "page_id", "analysis_date"],
                "desc",
                ["analysis_date"],
            ),
            ("RumMetrics", "rum_metrics", ["project_id", "metric", "date"], "desc", ["date"]),
            ("RumPageViews", "rum_page_views", ["project_id", "id"], "desc", ["date"]),
            ("Annotations", "annotations", ["project_id", "id"], "asc", None),
        ],
    )
    def test_endpoint_routes_to_its_response(
        self,
        endpoint: str,
        name: str,
        primary_keys: list[str],
        sort_mode: str,
        partition_keys: list[str] | None,
    ) -> None:
        response = debugbear_source(api_key="key", endpoint=endpoint)

        assert response.name == name
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == partition_keys

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown DebugBear endpoint"):
            debugbear_source(api_key="key", endpoint="Nope")

    def test_page_metrics_items_iterates_all_projects(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.debugbear.debugbear.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            projects_response = _response([{"id": "proj1"}, {"id": "proj2"}])
            proj1_metrics = _response(
                [{"page": {"id": "pg1"}, "metrics": {"analysis.date": "2024-01-10T00:00:00.000Z"}}]
            )
            proj2_metrics = _response(
                [{"page": {"id": "pg2"}, "metrics": {"analysis.date": "2024-01-11T00:00:00.000Z"}}]
            )
            mock_session.get.side_effect = [
                projects_response,
                proj1_metrics,
                _response([]),
                proj2_metrics,
                _response([]),
            ]

            response = debugbear_source(api_key="key", endpoint="PageMetrics")
            rows = list(cast("Iterable[Any]", response.items()))

        assert [row["project_id"] for row in rows] == ["proj1", "proj2"]
