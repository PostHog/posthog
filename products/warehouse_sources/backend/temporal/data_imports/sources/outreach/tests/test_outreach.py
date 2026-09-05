from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.outreach.outreach import (
    OutreachResumeConfig,
    OutreachRetryableError,
    _flatten_item,
    _format_datetime,
    _get_session,
    get_rows,
    outreach_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outreach.settings import (
    ENDPOINTS,
    OUTREACH_ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.outreach.outreach"


class FakeResumeManager(ResumableSourceManager[OutreachResumeConfig]):
    def __init__(self, state: Optional[OutreachResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[OutreachResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[OutreachResumeConfig]:
        return self.state

    def save_state(self, data: OutreachResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _token_response() -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"access_token": "the-token", "expires_in": 7200}
    resp.status_code = 200
    resp.ok = True
    return resp


def _json_response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.text = str(body)
    return resp


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (
                "datetime_with_microseconds",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "some-cursor-value", "some-cursor-value"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_plus_zero_offset_in_output(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestFlattenItem:
    def test_attributes_are_merged_into_the_root(self) -> None:
        item = {
            "type": "prospect",
            "id": 1,
            "attributes": {"firstName": "Sally", "updatedAt": "2026-01-01T00:00:00.000Z"},
        }

        row = _flatten_item(item)

        assert row["id"] == 1
        assert row["firstName"] == "Sally"
        assert row["updatedAt"] == "2026-01-01T00:00:00.000Z"
        assert "attributes" not in row

    def test_to_one_relationship_becomes_an_id_column(self) -> None:
        item = {
            "id": 1,
            "attributes": {},
            "relationships": {"account": {"data": {"type": "account", "id": 42}}},
        }

        row = _flatten_item(item)

        assert row["accountId"] == 42
        assert "relationships" not in row

    def test_to_many_relationship_is_dropped(self) -> None:
        item = {
            "id": 1,
            "attributes": {},
            "relationships": {"calls": {"data": [{"type": "call", "id": 1}, {"type": "call", "id": 2}]}},
        }

        row = _flatten_item(item)

        assert "callsId" not in row
        assert "calls" not in row

    def test_relationship_with_no_data_is_skipped(self) -> None:
        item = {"id": 1, "attributes": {}, "relationships": {"owner": {"data": None}}}

        row = _flatten_item(item)

        assert "ownerId" not in row

    def test_links_are_dropped(self) -> None:
        item = {"id": 1, "attributes": {}, "links": {"self": "https://api.outreach.io/api/v2/prospects/1"}}

        row = _flatten_item(item)

        assert "links" not in row


class TestSession:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_session_opts_out_of_body_capture_and_redacts_secrets(self, mock_session: mock.MagicMock) -> None:
        # Outreach rows are CRM records (names, emails, employers, mailing bodies, custom
        # attributes) that the name-based scrubbers can't reliably redact, so raw bodies must
        # never reach the shared HTTP sample store.
        _get_session("sec", "rt")

        assert mock_session.call_args.kwargs["capture"] is False
        assert mock_session.call_args.kwargs["redact_values"] == ("sec", "rt")


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_when_token_mints_and_probe_succeeds(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response({"data": []})

        assert validate_credentials("cid", "sec", "rt") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_when_probe_is_forbidden_but_token_is_genuine(self, mock_session: mock.MagicMock) -> None:
        # A 403 still proves the refresh token works; the app may just lack the users scope.
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response({}, status_code=403)

        assert validate_credentials("cid", "sec", "rt") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_token_mint_fails(self, mock_session: mock.MagicMock) -> None:
        resp = mock.MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("400 Client Error", response=mock.MagicMock())
        mock_session.return_value.post.return_value = resp

        assert validate_credentials("cid", "sec", "rt") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_probe_errors(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response({}, status_code=500)

        assert validate_credentials("cid", "sec", "rt") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_single_page_yields_flattened_rows(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response(
            {"data": [{"id": 1, "attributes": {"firstName": "Sally"}}], "links": {}}
        )

        batches = list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), FakeResumeManager()))

        assert batches == [[{"id": 1, "firstName": "Sally"}]]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_follows_links_next_across_pages_and_saves_state(self, mock_session: mock.MagicMock) -> None:
        page1 = _json_response(
            {
                "data": [{"id": 1, "attributes": {}}],
                "links": {"next": "https://api.outreach.io/api/v2/prospects?page[after]=abc"},
            }
        )
        page2 = _json_response({"data": [{"id": 2, "attributes": {}}], "links": {}})
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [page1, page2]
        manager = FakeResumeManager()

        batches = list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), manager))

        assert [item for batch in batches for item in batch] == [{"id": 1}, {"id": 2}]
        assert manager.saved == [
            OutreachResumeConfig(next_url="https://api.outreach.io/api/v2/prospects?page[after]=abc")
        ]
        assert manager.cleared is True
        # Only the first request carries explicit params; the second follows links.next verbatim.
        second_call = mock_session.return_value.get.call_args_list[1]
        assert second_call.args[0] == "https://api.outreach.io/api/v2/prospects?page[after]=abc"
        assert second_call.kwargs["params"] is None

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_next_url(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response(
            {"data": [{"id": 9, "attributes": {}}], "links": {}}
        )
        manager = FakeResumeManager(
            state=OutreachResumeConfig(next_url="https://api.outreach.io/api/v2/prospects?page[after]=resume")
        )

        list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), manager))

        first_call = mock_session.return_value.get.call_args_list[0]
        assert first_call.args[0] == "https://api.outreach.io/api/v2/prospects?page[after]=resume"
        assert first_call.kwargs["params"] is None

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_off_origin_links_next_is_refused_and_not_saved(self, mock_session: mock.MagicMock) -> None:
        # Following it would send the Authorization header to a host that isn't Outreach.
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response(
            {"data": [{"id": 1, "attributes": {}}], "links": {"next": "https://evil.example.com/api/v2/prospects"}}
        )
        manager = FakeResumeManager()

        with pytest.raises(ValueError, match="off-origin"):
            list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), manager))

        assert manager.saved == []
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_off_origin_resume_url_is_refused_before_any_request(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        manager = FakeResumeManager(
            state=OutreachResumeConfig(next_url="https://api.outreach.io@evil.example.com/api/v2/prospects")
        )

        with pytest.raises(ValueError, match="off-origin"):
            list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 0

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_plaintext_downgrade_of_the_api_host_is_refused(self, mock_session: mock.MagicMock) -> None:
        # Same host, but http:// would put the bearer token on the wire in the clear.
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response(
            {"data": [], "links": {"next": "http://api.outreach.io/api/v2/prospects?page[after]=abc"}}
        )

        with pytest.raises(ValueError, match="off-origin"):
            list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), FakeResumeManager()))

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_request_carries_the_updated_at_filter(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response({"data": [], "links": {}})

        list(
            get_rows(
                "cid",
                "sec",
                "rt",
                "prospects",
                mock.MagicMock(),
                FakeResumeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        params = mock_session.return_value.get.call_args_list[0].kwargs["params"]
        assert params["newFilterSyntax"] == "true"
        assert params["filter[updatedAt][gte]"] == "2026-03-04T00:00:00.000Z"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_request_has_no_filter_params(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response({"data": [], "links": {}})

        list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), FakeResumeManager()))

        params = mock_session.return_value.get.call_args_list[0].kwargs["params"]
        assert "newFilterSyntax" not in params
        assert "filter[updatedAt][gte]" not in params

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_remints_token_on_401(self, mock_session: mock.MagicMock) -> None:
        expired = _json_response({}, status_code=401)
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            expired,
            _json_response({"data": [{"id": 1, "attributes": {}}], "links": {}}),
        ]

        batches = list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), FakeResumeManager()))

        assert batches == [[{"id": 1}]]
        # One mint at start + one re-mint after the 401.
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_transient_error_is_retried_then_succeeds(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            requests.ConnectionError("connection reset"),
            _json_response({"data": [{"id": 1, "attributes": {}}], "links": {}}),
        ]

        with mock.patch("time.sleep", return_value=None):
            batches = list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), FakeResumeManager()))

        assert batches == [[{"id": 1}]]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retryable_status_is_retried_and_eventually_raises(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response({}, status_code=503)

        with mock.patch("time.sleep", return_value=None):
            with pytest.raises(OutreachRetryableError):
                list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), FakeResumeManager()))

        assert mock_session.return_value.get.call_count == 5  # MAX_RETRY_ATTEMPTS

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_retryable_status_raises_immediately(self, mock_session: mock.MagicMock) -> None:
        forbidden = _json_response({}, status_code=403)
        forbidden.raise_for_status.side_effect = requests.HTTPError("403 Client Error", response=mock.MagicMock())
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = forbidden

        with pytest.raises(requests.HTTPError):
            list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), FakeResumeManager()))

        # A 403 is a permission problem, not a transient one, so it isn't retried.
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_no_items_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _json_response({"data": [], "links": {}})

        assert list(get_rows("cid", "sec", "rt", "prospects", mock.MagicMock(), FakeResumeManager())) == []


class TestOutreachSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = OUTREACH_ENDPOINTS[endpoint]
        response = outreach_source("cid", "sec", "rt", endpoint, mock.MagicMock(), FakeResumeManager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == [config.partition_key]
