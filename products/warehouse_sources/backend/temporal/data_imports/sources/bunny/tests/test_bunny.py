import json
import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.bunny import (
    BUNNY_BASE_URL,
    BUNNY_STREAM_BASE_URL,
    PER_PAGE,
    BunnyResumeConfig,
    bunny_source,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.settings import BUNNY_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# check_access builds its own tracked session in the bunny module.
BUNNY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.bunny.bunny.make_tracked_session"
)


def _response(
    items: list[dict[str, Any]] | None,
    *,
    has_more: bool = False,
    drop_items: bool = False,
    status_code: int = 200,
) -> Response:
    body: dict[str, Any] = {"CurrentPage": 1, "TotalItems": len(items or []), "HasMoreItems": has_more}
    if not drop_items:
        body["Items"] = items or []
    resp = Response()
    resp.status_code = status_code
    resp.url = f"{BUNNY_BASE_URL}/pullzone"
    resp.reason = "Error" if status_code >= 400 else "OK"
    resp._content = json.dumps(body).encode()
    return resp


def _raw_response(body: Any, *, status_code: int = 200) -> Response:
    """A response whose whole body is the row payload (the statistics endpoints)."""
    resp = Response()
    resp.status_code = status_code
    resp.url = f"{BUNNY_BASE_URL}/statistics"
    resp.reason = "Error" if status_code >= 400 else "OK"
    resp._content = json.dumps(body).encode()
    return resp


def _stream_response(items: list[dict[str, Any]]) -> Response:
    """A Stream API list envelope, which is lower-cased and carries no ``HasMoreItems``."""
    return _raw_response({"items": items, "totalItems": len(items), "currentPage": 1, "itemsPerPage": PER_PAGE})


def _utc(day: int) -> datetime:
    return datetime(2024, 5, day, tzinfo=UTC)


def _make_manager(resume_state: BunnyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


@dataclasses.dataclass(frozen=True)
class _Sent:
    url: str
    params: dict[str, Any]
    auth: Any


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[_Sent]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    sent: list[_Sent] = []

    def _prepare(request: Any) -> mock.MagicMock:
        sent.append(_Sent(url=request.url, params=dict(request.params or {}), auth=request.auth))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return sent


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, endpoint: str = "pull_zones", last_value: Any = None):
    return bunny_source(
        access_key="bunny-key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        db_incremental_field_last_value=last_value,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_items_and_stops(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(session, [_response([{"Id": 1}, {"Id": 2}], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"Id": 1}, {"Id": 2}]
        assert session.send.call_count == 1
        assert sent[0].params == {"page": 1, "perPage": PER_PAGE}
        # No further pages, so no resume state is persisted.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_pagination_until_has_more_is_false(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(
            session,
            [
                _response([{"Id": 1}], has_more=True),
                _response([{"Id": 2}], has_more=True),
                _response([{"Id": 3}], has_more=False),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"Id": 1}, {"Id": 2}, {"Id": 3}]
        assert [s.params["page"] for s in sent] == [1, 2, 3]
        assert all(s.params["perPage"] == PER_PAGE for s in sent)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_each_batch(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"Id": 1}], has_more=True), _response([{"Id": 2}], has_more=False)])

        manager = _make_manager()
        _rows(_source(manager))

        # State is saved AFTER page 1 is yielded (pointing at page 2), and never for the final page.
        assert [call.args[0] for call in manager.save_state.call_args_list] == [BunnyResumeConfig(next_page=2)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        # Page 1 must never be fetched on resume.
        sent = _wire(session, [_response([{"Id": 2}], has_more=True), _response([{"Id": 3}], has_more=False)])

        manager = _make_manager(BunnyResumeConfig(next_page=2))
        rows = _rows(_source(manager))

        assert rows == [{"Id": 2}, {"Id": 3}]
        assert [s.params["page"] for s in sent] == [2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_with_has_more_continues(self, MockSession) -> None:
        session = MockSession.return_value
        # Termination follows HasMoreItems, not page emptiness — an empty page mid-stream must not
        # end the sync early.
        _wire(session, [_response([], has_more=True), _response([{"Id": 9}], has_more=False)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"Id": 9}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_items_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, drop_items=True)])

        # A 200 body without "Items" means the response shape changed — fail loud, not silently 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_access_key_travels_via_redacting_auth(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(session, [_response([{"Id": 1}], has_more=False)])

        _rows(_source(_make_manager()))

        # The secret goes through the framework auth (value-redacted in logs), not plain headers.
        assert sent[0].auth.api_key == "bunny-key"
        assert sent[0].auth.name == "AccessKey"
        assert sent[0].auth.location == "header"
        assert session.headers.get("Accept") == "application/json"
        assert "AccessKey" not in session.headers


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_retried_then_succeed(
        self, _name: str, status: int, MockSession, _mock_sleep
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status_code=status), _response([{"Id": 1}], has_more=False)])

        rows = _rows(_source(_make_manager()))

        assert rows == [{"Id": 1}]
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_persistent_server_error_exhausts_retries(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status_code=500)] * 5)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(_make_manager()))
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status_code=status)])

        with pytest.raises(requests.HTTPError):
            _rows(_source(_make_manager()))
        # Credential problems are permanent — no retries.
        assert session.send.call_count == 1


class TestCheckAccess:
    @pytest.mark.parametrize(
        "status, expected",
        [
            (200, (True, 200)),
            (401, (False, 401)),
            (403, (False, 403)),
            (500, (False, 500)),
        ],
    )
    @mock.patch(BUNNY_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status: int, expected: tuple[bool, int]) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert check_access("bunny-key") == expected

    @mock.patch(BUNNY_SESSION_PATCH)
    def test_connection_error_maps_to_none(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert check_access("bunny-key") == (False, None)


class TestBunnySourceResponse:
    @parameterized.expand(
        [
            ("pull_zones", ["Id"], None),
            ("storage_zones", ["Id"], None),
            ("dns_zones", ["Id"], "DateCreated"),
            ("video_libraries", ["Id"], "DateCreated"),
            ("statistics", ["Timestamp"], "Timestamp"),
            ("storage_zone_statistics", ["StorageZoneId", "Timestamp"], "Timestamp"),
            ("storage_zone_egress", ["StorageZoneId", "Timestamp"], "Timestamp"),
            ("videos", ["videoLibraryId", "guid"], "dateUploaded"),
            ("video_library_statistics", ["videoLibraryId", "timestamp"], "timestamp"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitioning_matches_endpoint_config(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None, MockSession
    ) -> None:
        MockSession.return_value.headers = {}
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    def test_top_level_endpoints_use_the_globally_unique_id(self) -> None:
        # bunny.net IDs are globally unique, so a single `Id` key is sufficient table-wide.
        top_level = [c for c in BUNNY_ENDPOINTS.values() if c.parent is None and c.charts is None]
        assert all(config.primary_keys == ["Id"] for config in top_level)
        assert set(BUNNY_ENDPOINTS) == set(ENDPOINTS)

    def test_fanout_children_carry_their_parent_id_in_the_key(self) -> None:
        # A child aggregates rows from every parent into one table, so a key unique only within a
        # parent seeds duplicate rows that every later merge multi-matches.
        children = [c for c in BUNNY_ENDPOINTS.values() if c.parent is not None]
        assert children
        assert all(config.parent is not None and config.parent.id_column in config.primary_keys for config in children)

    def test_fanout_tables_defer_the_watermark_to_the_end_of_the_run(self) -> None:
        # Their rows arrive grouped by parent, so the table is not in timestamp order and a run cut
        # short mid-walk must not leave the watermark past parents it never reached.
        for config in BUNNY_ENDPOINTS.values():
            if config.parent is not None and config.timestamp_column is not None:
                assert config.sort_mode == "desc"


CHART_COLUMNS = set((BUNNY_ENDPOINTS["statistics"].charts or {}).values())


class TestAccountStatistics:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pivots_charts_into_one_row_per_timestamp(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _raw_response(
                    {
                        # Deliberately out of order, and the two charts cover different days.
                        "BandwidthUsedChart": {"2024-05-02T00:00:00": 20, "2024-05-01T00:00:00": 10},
                        "RequestsServedChart": {"2024-05-02T00:00:00": 7},
                        "TotalBandwidthUsed": 30,
                    }
                )
            ],
        )

        rows = _rows(_source(_make_manager(), endpoint="statistics"))

        assert [row["Timestamp"] for row in rows] == [_utc(1), _utc(2)]
        assert [row["BandwidthUsed"] for row in rows] == [10, 20]
        assert [row["RequestsServed"] for row in rows] == [None, 7]
        # Every row carries every chart column, so a batch converts to one Arrow schema even
        # when the charts cover different ranges.
        assert all(set(row) == CHART_COLUMNS | {"Timestamp"} for row in rows)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_asks_for_the_charts_without_a_date_bound(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(session, [_raw_response({"BandwidthUsedChart": {"2024-05-01T00:00:00": 1}})])

        _rows(_source(_make_manager(), endpoint="statistics"))

        assert session.send.call_count == 1
        assert sent[0].url == f"{BUNNY_BASE_URL}/statistics"
        # Each chart defaults to off, so a missing load flag silently returns an empty column.
        assert sent[0].params["loadBandwidthUsed"] == "true"
        assert sent[0].params["loadRequestsServed"] == "true"
        assert "dateFrom" not in sent[0].params

    @parameterized.expand(
        [
            ("datetime", datetime(2024, 5, 2, 3, 4, 5, tzinfo=UTC)),
            # The pipeline persists the watermark as a string for some sources.
            ("string", "2024-05-02T03:04:05+00:00"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_asks_from_the_watermark(self, _name: str, last_value: Any, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(session, [_raw_response({"BandwidthUsedChart": {}})])

        _rows(_source(_make_manager(), endpoint="statistics", last_value=last_value))

        assert sent[0].params["dateFrom"] == "2024-05-02T03:04:05Z"


class TestStorageZoneFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_calls_each_zone_and_stamps_its_id_on_every_row(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(
            session,
            [
                _response([{"Id": 11}, {"Id": 22}], has_more=False),
                _raw_response(
                    {"StorageUsedChart": {"2024-05-01T00:00:00": 5}, "FileCountChart": {"2024-05-01T00:00:00": 2}}
                ),
                _raw_response({"StorageUsedChart": {"2024-05-01T00:00:00": 9}}),
            ],
        )

        rows = _rows(_source(_make_manager(), endpoint="storage_zone_statistics"))

        assert [s.url for s in sent] == [
            f"{BUNNY_BASE_URL}/storagezone",
            f"{BUNNY_BASE_URL}/storagezone/11/statistics",
            f"{BUNNY_BASE_URL}/storagezone/22/statistics",
        ]
        assert rows == [
            {"StorageZoneId": 11, "Timestamp": _utc(1), "StorageUsed": 5, "FileCount": 2},
            {"StorageZoneId": 22, "Timestamp": _utc(1), "StorageUsed": 9, "FileCount": None},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_egress_splits_the_protocols_into_columns(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(
            session,
            [
                _response([{"Id": 11}], has_more=False),
                _raw_response(
                    {
                        "HttpEgressChart": {"2024-05-01T00:00:00": 3},
                        "TotalEgressChart": {"2024-05-01T00:00:00": 3},
                        "TotalEgress": 3,
                    }
                ),
            ],
        )

        rows = _rows(_source(_make_manager(), endpoint="storage_zone_egress"))

        assert sent[1].url == f"{BUNNY_BASE_URL}/storagezone/11/statistics/egress"
        assert rows == [
            {
                "StorageZoneId": 11,
                "Timestamp": _utc(1),
                "HttpEgress": 3,
                "S3Egress": None,
                "S3PresignedEgress": None,
                "FtpEgress": None,
                "SftpEgress": None,
                "TotalEgress": 3,
            }
        ]


class TestStreamFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_videos_use_the_library_key_against_the_stream_host(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(
            session,
            [
                _response([{"Id": 7, "ReadOnlyApiKey": "lib-ro", "ApiKey": "lib-rw"}], has_more=False),
                _stream_response([{"guid": "g1", "videoLibraryId": 7}]),
                _stream_response([]),
            ],
        )

        rows = _rows(_source(_make_manager(), endpoint="videos"))

        assert rows == [{"guid": "g1", "videoLibraryId": 7}]
        # The account key lists the libraries; the Stream host only accepts the library's own key.
        assert sent[0].auth.api_key == "bunny-key"
        assert sent[1].url == f"{BUNNY_STREAM_BASE_URL}/library/7/videos"
        assert sent[1].auth.api_key == "lib-ro"
        assert sent[1].params == {"page": 1, "itemsPerPage": PER_PAGE, "orderBy": "date"}
        # The Stream envelope carries no "more items" flag, so the walk ends on an empty page.
        assert [s.params["page"] for s in sent[1:]] == [1, 2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_falls_back_to_the_read_write_library_key(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(
            session,
            [
                _response([{"Id": 7, "ReadOnlyApiKey": "", "ApiKey": "lib-rw"}], has_more=False),
                _stream_response([]),
            ],
        )

        _rows(_source(_make_manager(), endpoint="videos"))

        assert sent[1].auth.api_key == "lib-rw"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_library_without_a_key_is_skipped(self, MockSession) -> None:
        session = MockSession.return_value
        # A library we cannot authenticate against must not fail the whole table.
        _wire(session, [_response([{"Id": 7}], has_more=False)])

        rows = _rows(_source(_make_manager(), endpoint="videos"))

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_library_statistics_pivot_onto_the_library_id(self, MockSession) -> None:
        session = MockSession.return_value
        sent = _wire(
            session,
            [
                _response([{"Id": 7, "ReadOnlyApiKey": "lib-ro"}], has_more=False),
                _raw_response(
                    {
                        "viewsChart": {"2024-05-01T00:00:00": 4},
                        "watchTimeChart": {"2024-05-01T00:00:00": 120},
                        "countryViewCounts": {"US": 4},
                    }
                ),
            ],
        )

        rows = _rows(_source(_make_manager(), endpoint="video_library_statistics"))

        assert sent[1].url == f"{BUNNY_STREAM_BASE_URL}/library/7/statistics"
        # The country breakdown is a different grain and stays out of this table.
        assert rows == [{"videoLibraryId": 7, "timestamp": _utc(1), "views": 4, "watchTime": 120}]
