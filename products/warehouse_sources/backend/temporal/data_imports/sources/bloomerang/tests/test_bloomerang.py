import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.bloomerang import (
    BloomerangResumeConfig,
    _build_params,
    _flatten_audit_trail,
    _format_last_modified,
    bloomerang_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.settings import BLOOMERANG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth

# The client config and validate_credentials both build their tracked session directly in the
# bloomerang module (capture=False needs a session built here, not RESTClient's default one).
BLOOMERANG_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.bloomerang.make_tracked_session"
)


class TestFlattenAuditTrail:
    def test_promotes_created_and_last_modified(self) -> None:
        item = {
            "Id": 1,
            "AuditTrail": {"CreatedDate": "2026-01-01T00:00:00Z", "LastModifiedDate": "2026-02-01T00:00:00Z"},
        }

        result = _flatten_audit_trail(item)

        assert result["CreatedDate"] == "2026-01-01T00:00:00Z"
        assert result["LastModifiedDate"] == "2026-02-01T00:00:00Z"
        assert "AuditTrail" not in result

    def test_missing_audit_trail_is_a_no_op(self) -> None:
        item = {"Id": 1}
        assert _flatten_audit_trail(item) == {"Id": 1}

    def test_non_dict_audit_trail_is_ignored(self) -> None:
        item = {"Id": 1, "AuditTrail": None}
        result = _flatten_audit_trail(item)
        assert "CreatedDate" not in result
        assert "AuditTrail" not in result


class TestFormatLastModified:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_last_modified(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_incremental_endpoint_with_cursor(self) -> None:
        params = _build_params(
            BLOOMERANG_ENDPOINTS["Constituents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {
            "lastModified": "2026-03-04T02:58:14Z",
            "orderBy": "LastModifiedDate",
            "orderDirection": "Asc",
        }

    def test_incremental_endpoint_without_cursor_falls_back_to_stable_sort(self) -> None:
        # First-ever sync: no watermark yet, but the endpoint still supports sorting, so page
        # boundaries must stay stable rather than sending no params at all.
        params = _build_params(
            BLOOMERANG_ENDPOINTS["Constituents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params == {"orderBy": "Id", "orderDirection": "Asc"}

    def test_full_refresh_endpoint_with_sort_support_never_filters(self) -> None:
        # Transactions has no server-side lastModified filter; a cursor must not leak into the request.
        params = _build_params(
            BLOOMERANG_ENDPOINTS["Transactions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"orderBy": "Id", "orderDirection": "Asc"}

    def test_endpoint_without_sort_support_sends_no_params(self) -> None:
        params = _build_params(
            BLOOMERANG_ENDPOINTS["Appeals"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert params == {}


def _response(
    items: list[dict[str, Any]] | None, *, total_filtered: int | None = None, drop_results: bool = False
) -> Response:
    body: dict[str, Any] = {}
    if not drop_results:
        body["Results"] = items or []
    body["Total"] = total_filtered if total_filtered is not None else len(items or [])
    if total_filtered is not None:
        body["TotalFiltered"] = total_filtered
    body["Start"] = 0
    body["ResultCount"] = len(items or [])
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: BloomerangResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params/auth AT SEND TIME."""
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return bloomerang_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestBloomerangSourceTransport:
    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession) -> None:
        # A full first page (== PAGE_SIZE) signals more rows remain; the paginator only stops once
        # a page comes back shorter than PAGE_SIZE.
        session = MockSession.return_value
        first_page = [{"Id": i} for i in range(1, 51)]
        snapshots = _wire(
            session,
            [
                _response(first_page, total_filtered=51),
                _response([{"Id": 51}], total_filtered=51),
            ],
        )

        rows = _rows(_source("Appeals", _make_manager()))

        assert [r["Id"] for r in rows] == list(range(1, 52))
        assert session.send.call_count == 2
        assert snapshots[0]["params"] == {"skip": 0, "take": 50}
        assert snapshots[1]["params"] == {"skip": 50, "take": 50}

    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_auth_is_framework_api_key(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"Id": 1}], total_filtered=1)])

        _rows(_source("Appeals", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, APIKeyAuth)
        assert auth.api_key == "key"
        assert auth.name == "X-Api-Key"
        assert auth.location == "header"

    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_production_sync_does_not_follow_redirects(self, MockSession) -> None:
        # `X-Api-Key` isn't the standard Authorization header, so `requests` won't strip it on a
        # cross-origin redirect — pin `allow_redirects=False` the same way the credential probe does.
        session = MockSession.return_value
        _wire(session, [_response([{"Id": 1}], total_filtered=1)])

        _rows(_source("Appeals", _make_manager()))

        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        first_page = [{"Id": i} for i in range(1, 51)]
        _wire(
            session,
            [
                _response(first_page, total_filtered=51),
                _response([{"Id": 51}], total_filtered=51),
            ],
        )

        manager = _make_manager()
        _rows(_source("Appeals", manager))

        # State is saved only while more pages remain (offset 0 -> next offset 50), never on the
        # final (short) page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BloomerangResumeConfig(next_offset=50)

    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"Id": 51}], total_filtered=51)])

        rows = _rows(_source("Appeals", _make_manager(BloomerangResumeConfig(next_offset=50))))

        assert [r["Id"] for r in rows] == [51]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["skip"] == 50

    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_incremental_cursor_added_to_request(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"Id": 1}], total_filtered=1)])

        _rows(
            _source(
                "Constituents",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["lastModified"] == "2026-03-04T02:58:14Z"
        assert snapshots[0]["params"]["orderBy"] == "LastModifiedDate"

    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_audit_trail_endpoint_flattens_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    [
                        {
                            "Id": 1,
                            "AuditTrail": {
                                "CreatedDate": "2026-01-01T00:00:00Z",
                                "LastModifiedDate": "2026-01-02T00:00:00Z",
                            },
                        }
                    ],
                    total_filtered=1,
                )
            ],
        )

        rows = _rows(_source("Constituents", _make_manager()))

        assert rows[0]["CreatedDate"] == "2026-01-01T00:00:00Z"
        assert rows[0]["LastModifiedDate"] == "2026-01-02T00:00:00Z"
        assert "AuditTrail" not in rows[0]

    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_non_audit_trail_endpoint_leaves_rows_untouched(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"Id": 1, "Name": "Winter Appeal"}], total_filtered=1)])

        rows = _rows(_source("Appeals", _make_manager()))

        assert rows[0] == {"Id": 1, "Name": "Winter Appeal"}

    @parameterized.expand(
        [
            ("Constituents", "merge"),
            ("Transactions", "replace"),
            ("Appeals", "replace"),
        ]
    )
    def test_write_disposition_merges_only_for_incremental_sync(self, endpoint, expected_disposition) -> None:
        resource = _source(
            endpoint,
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        ).items()

        write_disposition = resource._hints.get("write_disposition")
        if expected_disposition == "merge":
            assert write_disposition == {"disposition": "merge", "strategy": "upsert"}
        else:
            assert write_disposition == "replace"

    def test_partition_key_present_only_for_audit_trail_endpoints(self) -> None:
        constituents = _source("Constituents", _make_manager())
        appeals = _source("Appeals", _make_manager())

        assert constituents.partition_keys == ["CreatedDate"]
        assert constituents.partition_mode == "datetime"
        assert appeals.partition_keys is None
        assert appeals.partition_mode is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
        ]
    )
    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_status_mapping(self, status_code, expected_valid, expected_status, MockSession) -> None:
        session = MockSession.return_value
        response = mock.MagicMock()
        response.status_code = status_code
        session.get.return_value = response

        is_valid, returned_status = validate_credentials("key")

        assert is_valid is expected_valid
        assert returned_status == expected_status

    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_sends_api_key_header_without_following_redirects(self, MockSession) -> None:
        session = MockSession.return_value
        response = mock.MagicMock()
        response.status_code = 200
        session.get.return_value = response

        validate_credentials("secret-key")

        call_kwargs = session.get.call_args.kwargs
        assert call_kwargs["headers"] == {"X-Api-Key": "secret-key"}
        assert call_kwargs["allow_redirects"] is False

    @mock.patch(BLOOMERANG_SESSION_PATCH)
    def test_network_failure_is_reported_as_invalid(self, MockSession) -> None:
        session = MockSession.return_value
        session.get.side_effect = Exception("boom")

        is_valid, status = validate_credentials("key")

        assert is_valid is False
        assert status is None
