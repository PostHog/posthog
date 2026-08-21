import json
from datetime import UTC, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.gainsight_px import (
    GainsightPxResumeConfig,
    _base_url,
    _build_url,
    _normalize_row,
    gainsight_px_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import (
    GAINSIGHT_PX_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the gainsight_px module.
GAINSIGHT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.gainsight_px.make_tracked_session"
)


def _response(data_key: str, records: list[dict[str, Any]], *, status_code: int = 200, **extra: Any) -> Response:
    body: dict[str, Any] = {data_key: records, **extra}
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: GainsightPxResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy per prepare.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock) -> Any:
    return gainsight_px_source(
        api_key="secret-key",
        region="us",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestBaseUrl:
    @parameterized.expand(
        [
            ("us", "https://api.aptrinsic.com/v1"),
            ("eu", "https://api-eu.aptrinsic.com/v1"),
            ("us2", "https://api-us2.aptrinsic.com/v1"),
            ("unknown", "https://api.aptrinsic.com/v1"),
        ]
    )
    def test_base_url(self, region: str, expected: str) -> None:
        assert _base_url(region) == expected


class TestBuildUrl:
    def test_encodes_params(self) -> None:
        url = _build_url("https://api.aptrinsic.com/v1/users", {"pageSize": 1000, "scrollId": "a b/c"})
        assert url == "https://api.aptrinsic.com/v1/users?pageSize=1000&scrollId=a+b%2Fc"

    def test_no_params(self) -> None:
        assert _build_url("https://api.aptrinsic.com/v1/users", {}) == "https://api.aptrinsic.com/v1/users"


class TestNormalizeRow:
    def test_converts_epoch_millis_to_datetime(self) -> None:
        # 2021-01-01T00:00:00Z == 1609459200000 ms
        row = _normalize_row({"id": "u1", "createDate": 1609459200000})
        assert row["createDate"] == datetime(2021, 1, 1, tzinfo=UTC)

    def test_leaves_non_date_fields_untouched(self) -> None:
        row = _normalize_row({"id": "u1", "score": 42, "globalUnsubscribe": True, "name": "Acme"})
        assert row == {"id": "u1", "score": 42, "globalUnsubscribe": True, "name": "Acme"}

    def test_ignores_missing_and_non_int_dates(self) -> None:
        # releaseDate is an ISO string on articles — must not be reinterpreted as epoch millis.
        row = _normalize_row({"id": "a1", "releaseDate": "2021-01-01"})
        assert row["releaseDate"] == "2021-01-01"


class TestScrollPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_scroll_id_and_stops_on_short_page(self, MockSession, monkeypatch) -> None:
        # users caps at a large pageSize; shrink it so a 2-then-1 record run terminates.
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["users"], "page_size", 2)
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response("users", [{"id": "1"}, {"id": "2"}], scrollId="s1"),
                _response("users", [{"id": "3"}], scrollId="s2"),  # short page → stop
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        # First request carries only pageSize; the second carries the scroll cursor.
        assert params[0] == {"pageSize": 2}
        assert params[1]["scrollId"] == "s1"
        # State saved after the first (full) page only, carrying the next scroll cursor.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == GainsightPxResumeConfig(scroll_id="s1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_scroll_id_absent(self, MockSession, monkeypatch) -> None:
        # A full page whose scrollId is null still terminates — the null cursor ends it.
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["accounts"], "page_size", 2)
        session = MockSession.return_value
        _wire(session, [_response("accounts", [{"id": "1"}, {"id": "2"}], scrollId=None)])

        manager = _make_manager()
        rows = _rows(_source("accounts", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_scroll_id(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["users"], "page_size", 2)
        session = MockSession.return_value
        params = _wire(session, [_response("users", [{"id": "9"}], scrollId=None)])

        manager = _make_manager(GainsightPxResumeConfig(scroll_id="saved-cursor"))
        _rows(_source("users", manager))

        assert params[0]["scrollId"] == "saved-cursor"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows_and_stops(self, MockSession, monkeypatch) -> None:
        # These endpoints don't fail loud on a missing key (parity with the hand-rolled `or []`).
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["users"], "page_size", 2)
        session = MockSession.return_value
        _wire(session, [_response("wrongKey", [{"id": "x"}], scrollId="s1")])

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestPageNumberPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_is_last_page(self, MockSession, monkeypatch) -> None:
        # page_size 1 keeps each page "full", so isLastPage (not the short-page guard) is what stops us.
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["features"], "page_size", 1)
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response("features", [{"id": "f1"}], isLastPage=False),
                _response("features", [{"id": "f2"}], isLastPage=True),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("features", manager))

        assert [r["id"] for r in rows] == ["f1", "f2"]
        assert params[0]["pageNumber"] == 0
        assert params[1]["pageNumber"] == 1
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == GainsightPxResumeConfig(page_number=1)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_short_page(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["segments"], "page_size", 2)
        session = MockSession.return_value
        # short page → stop even though isLastPage is False.
        _wire(session, [_response("segments", [{"id": "s1"}], isLastPage=False)])

        manager = _make_manager()
        rows = _rows(_source("segments", manager))

        assert [r["id"] for r in rows] == ["s1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page_number(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["features"], "page_size", 100)
        session = MockSession.return_value
        params = _wire(session, [_response("features", [{"id": "f"}], isLastPage=True)])

        manager = _make_manager(GainsightPxResumeConfig(page_number=4))
        _rows(_source("features", manager))

        assert params[0]["pageNumber"] == 4


class TestRowNormalization:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_epoch_millis_fields_are_converted_during_iteration(self, MockSession, monkeypatch) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["accounts"], "page_size", 2)
        session = MockSession.return_value
        _wire(session, [_response("accounts", [{"id": "a1", "createDate": 1609459200000}], scrollId=None)])

        rows = _rows(_source("accounts", _make_manager()))

        assert rows[0]["createDate"] == datetime(2021, 1, 1, tzinfo=UTC)


class TestRetries:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried(self, MockSession, _mock_sleep, monkeypatch) -> None:
        monkeypatch.setattr(GAINSIGHT_PX_ENDPOINTS["accounts"], "page_size", 2)
        session = MockSession.return_value
        _wire(
            session,
            [
                _response("accounts", [], status_code=429),
                _response("accounts", [{"id": "1"}, {"id": "2"}], status_code=200, scrollId=None),
            ],
        )

        rows = _rows(_source("accounts", _make_manager()))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 2


class TestSessionHardening:
    """The API key travels in a custom header the sample-capture denylist can't recognise, so the
    framework auth registers its value for redaction across errors, logs, and captured samples."""

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_registers_api_key_for_redaction(self, MockSession) -> None:
        _source("users", _make_manager())
        assert MockSession.call_args.kwargs["redact_values"] == ("secret-key",)

    @mock.patch(GAINSIGHT_SESSION_PATCH)
    def test_validate_credentials_masks_key(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("secret-key", "us")
        assert mock_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(GAINSIGHT_SESSION_PATCH)
    def test_maps_status_to_bool(self, _name: str, status_code: int, expected: bool, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("key", "us") is expected

    @mock.patch(GAINSIGHT_SESSION_PATCH)
    def test_network_error_is_false(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "us") is False

    @mock.patch(GAINSIGHT_SESSION_PATCH)
    def test_probes_accounts_endpoint(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key", "eu")
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == "https://api-eu.aptrinsic.com/v1/accounts?pageSize=1"


class TestSourceResponse:
    @parameterized.expand(
        [
            ("accounts", ["id"], "createDate"),
            ("users", ["id"], "createDate"),
            ("features", ["id"], None),
            ("segments", ["id"], None),
            ("engagements", ["id"], None),
            ("articles", ["id"], "createdDate"),
            ("kc_bots", ["id"], "createdDate"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None, MockSession
    ) -> None:
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
