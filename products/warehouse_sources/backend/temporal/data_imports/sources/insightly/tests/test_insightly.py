import json
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly import (
    PAGE_SIZE,
    InsightlyResumeConfig,
    _format_updated_after,
    base_url,
    insightly_source,
    normalize_pod,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the insightly module.
INSIGHTLY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly.make_tracked_session"
)

# A prepared-request URL on the pinned host, so the client's allowed_hosts guard passes with mocks.
_PINNED_URL = "https://api.na1.insightly.com/v3.1/Contacts"


def _response(items: list[dict[str, Any]] | None, *, status: int = 200, raw: Optional[bytes] = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = _PINNED_URL
    resp.reason = "OK" if status < 400 else "Unauthorized"
    resp._content = raw if raw is not None else json.dumps(items or []).encode()
    return resp


def _make_manager(resume_state: InsightlyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared. The prepared request carries the pinned URL so the allowed_hosts check passes.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock(url=_PINNED_URL)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, **kwargs: Any):
    return insightly_source(
        "na1",
        "key",
        kwargs.pop("endpoint", "Contacts"),
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestNormalizePod:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("na1", "na1"),
            ("NA1", "na1"),
            ("  eu1  ", "eu1"),
            ("https://api.na1.insightly.com/v3.1", "na1"),
            ("https://api.aps1.insightly.com/v3.1/", "aps1"),
            ("api.eu2.insightly.com", "eu2"),
        ],
    )
    def test_normalizes_valid_pods(self, raw: str, expected: str) -> None:
        assert normalize_pod(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "na 1",
            "evil.com",
            "na1.evil.com",
            "http://169.254.169.254",
            "na_1",
        ],
    )
    def test_rejects_invalid_pods(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_pod(raw)

    def test_base_url_is_pinned_to_insightly(self) -> None:
        assert base_url("na1") == "https://api.na1.insightly.com/v3.1"
        assert base_url("https://api.EU1.insightly.com/v3.1") == "https://api.eu1.insightly.com/v3.1"


class TestFormatUpdatedAfter:
    def test_formats_datetime_with_trailing_z(self) -> None:
        from datetime import UTC, datetime

        assert _format_updated_after(datetime(2018, 4, 9, 16, 58, 14, tzinfo=UTC)) == "2018-04-09T16:58:14Z"

    def test_naive_datetime_treated_as_utc(self) -> None:
        from datetime import datetime

        assert _format_updated_after(datetime(2020, 1, 2, 3, 4, 5)) == "2020-01-02T03:04:05Z"

    def test_date_formats_at_midnight(self) -> None:
        from datetime import date

        assert _format_updated_after(date(2021, 6, 7)) == "2021-06-07T00:00:00Z"

    def test_string_passes_through(self) -> None:
        assert _format_updated_after("2022-03-04T05:06:07Z") == "2022-03-04T05:06:07Z"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_offset_and_saves_state_after_full_page(self, MockSession) -> None:
        session = MockSession.return_value
        full_page = [{"CONTACT_ID": i} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([{"CONTACT_ID": 9999}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        # Both pages are yielded; the short second page ends pagination.
        assert rows[-1] == {"CONTACT_ID": 9999}
        assert len(rows) == PAGE_SIZE + 1
        # `top`/`skip` progress from 0 to PAGE_SIZE.
        assert params[0]["skip"] == 0
        assert params[0]["top"] == PAGE_SIZE
        assert params[1]["skip"] == PAGE_SIZE
        # State saved once after the first full page, pointing at the next offset.
        manager.save_state.assert_called_once_with(InsightlyResumeConfig(skip=PAGE_SIZE))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"CONTACT_ID": 1}, {"CONTACT_ID": 2}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"CONTACT_ID": 1}, {"CONTACT_ID": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"CONTACT_ID": 7}])])

        rows = _rows(_source(_make_manager(InsightlyResumeConfig(skip=1000))))

        assert rows == [{"CONTACT_ID": 7}]
        assert params[0]["skip"] == 1000

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_applied_on_every_page(self, MockSession) -> None:
        from datetime import UTC, datetime

        session = MockSession.return_value
        full_page = [{"CONTACT_ID": i} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full_page), _response([])])

        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
        # The `updated_after_utc` server-side filter is present on both the first and second page.
        assert all(p.get("updated_after_utc") == "2020-01-01T00:00:00Z" for p in params)
        assert len(params) == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_incremental_filter_without_value(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"CONTACT_ID": 1}])])

        _rows(_source(_make_manager(), should_use_incremental_field=True, db_incremental_field_last_value=None))
        assert "updated_after_utc" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_filters(self, MockSession) -> None:
        from datetime import UTC, datetime

        session = MockSession.return_value
        params = _wire(session, [_response([{"USER_ID": 1}])])

        # Users is full-refresh only; even with an incremental value it must not send updated_after_utc.
        _rows(
            _source(
                _make_manager(),
                endpoint="Users",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
        assert "updated_after_utc" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_non_retryable_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], status=401)])

        with pytest.raises(Exception, match="401 Client Error"):
            _rows(_source(_make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_on_non_list_response(self, MockSession) -> None:
        session = MockSession.return_value
        # A 200 with an unexpected (non-array) body must fail loudly, not sync zero rows silently.
        _wire(session, [_response(None, raw=json.dumps({"error": "something went wrong"}).encode())])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source(_make_manager()))


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    @mock.patch(INSIGHTLY_SESSION_PATCH)
    def test_returns_status_code(self, mock_session: mock.MagicMock, status_code: int) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("na1", "key", "/Contacts") == status_code
        called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url == "https://api.na1.insightly.com/v3.1/Contacts?top=1"
        # The key is masked in logged URLs and captured samples.
        assert mock_session.call_args.kwargs["redact_values"] == ("key",)

    @mock.patch(INSIGHTLY_SESSION_PATCH)
    def test_returns_none_on_transport_error(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("na1", "key") is None

    def test_propagates_invalid_pod(self) -> None:
        with pytest.raises(ValueError):
            validate_credentials("evil.com", "key")


class TestInsightlySourceResponse:
    @pytest.mark.parametrize(
        "endpoint, expected_pk, expected_partition_keys, expected_mode",
        [
            ("Contacts", "CONTACT_ID", ["DATE_CREATED_UTC"], "datetime"),
            ("Opportunities", "OPPORTUNITY_ID", ["DATE_CREATED_UTC"], "datetime"),
            ("Users", "USER_ID", ["DATE_CREATED_UTC"], "datetime"),
            ("Pipelines", "PIPELINE_ID", None, None),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(
        self,
        MockSession,
        endpoint: str,
        expected_pk: str,
        expected_partition_keys: list[str] | None,
        expected_mode: str | None,
    ) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == [expected_pk]
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == expected_mode
        assert response.sort_mode == "asc"
