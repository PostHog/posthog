from typing import Any
from urllib.parse import urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.eventee import (
    EVENTEE_BASE_URL,
    MAX_RETRY_ATTEMPTS,
    EventeeRetryableError,
    eventee_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.settings import (
    ENDPOINTS,
    EVENTEE_ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.eventee.eventee"


def _json_response(body: Any) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


def _error_response(status_code: int) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = False
    resp.text = "error"
    return resp


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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("tok") is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_sends_bearer_token(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("tok")

        headers = mock_session.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("tok") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_content_subresource_extracted_by_data_key(self, mock_session):
        # /content bundles several lists; the `halls` table reads its rows from the `halls` key and
        # must not pick up rows from sibling keys.
        content = {
            "halls": [{"id": 1, "name": "Main"}],
            "lectures": [{"id": 99, "name": "Keynote"}],
        }
        mock_session.return_value.get.return_value = _json_response(content)

        batches = list(get_rows("tok", "halls", mock.MagicMock()))

        assert batches == [[{"id": 1, "name": "Main"}]]
        url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(url).path == "/public/v1/content"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_standalone_array_endpoint(self, mock_session):
        mock_session.return_value.get.return_value = _json_response([{"id": 7}, {"id": 8}])

        batches = list(get_rows("tok", "groups", mock.MagicMock()))

        assert batches == [[{"id": 7}, {"id": 8}]]
        assert urlparse(mock_session.return_value.get.call_args.args[0]).path == "/public/v1/groups"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_single_object_response_wrapped_in_list(self, mock_session):
        # /registrations can return a bare object rather than an array.
        mock_session.return_value.get.return_value = _json_response({"id": 420, "email": "a@b.com"})

        batches = list(get_rows("tok", "registrations", mock.MagicMock()))

        assert batches == [[{"id": 420, "email": "a@b.com"}]]

    @pytest.mark.parametrize(
        "endpoint, body",
        [
            ("halls", {"halls": []}),
            ("halls", {"lectures": [{"id": 1}]}),  # data_key missing entirely
            ("groups", []),
            ("groups", None),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_or_missing_data_yields_nothing(self, mock_session, endpoint, body):
        mock_session.return_value.get.return_value = _json_response(body)

        assert list(get_rows("tok", endpoint, mock.MagicMock())) == []

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_retryable_status_then_succeeds(self, mock_session, _mock_sleep):
        mock_session.return_value.get.side_effect = [
            _error_response(500),
            _error_response(429),
            _json_response([{"id": 1}]),
        ]

        batches = list(get_rows("tok", "groups", mock.MagicMock()))

        assert batches == [[{"id": 1}]]
        assert mock_session.return_value.get.call_count == 3

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_retries_exhausted_raises(self, mock_session, _mock_sleep):
        mock_session.return_value.get.return_value = _error_response(503)

        with pytest.raises(EventeeRetryableError):
            list(get_rows("tok", "groups", mock.MagicMock()))

        assert mock_session.return_value.get.call_count == MAX_RETRY_ATTEMPTS

    @mock.patch("time.sleep")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_client_error_raises_for_status(self, mock_session, _mock_sleep):
        # A 401 is not retryable — it must propagate via raise_for_status so the source can mark it
        # non-retryable rather than burning retries on a bad token.
        resp = _error_response(401)
        resp.raise_for_status.side_effect = Exception("401 Client Error")
        mock_session.return_value.get.return_value = resp

        with pytest.raises(Exception, match="401 Client Error"):
            list(get_rows("tok", "groups", mock.MagicMock()))

        assert mock_session.return_value.get.call_count == 1


class TestEventeeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = EVENTEE_ENDPOINTS[endpoint]
        response = eventee_source("tok", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"

        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partition_keys_are_stable_creation_fields(self, endpoint):
        # Partitioning on a mutable field (updated_at / checked_at) rewrites partitions every sync.
        config = EVENTEE_ENDPOINTS[endpoint]
        if config.partition_key:
            assert config.partition_key in ("created_at", "registered_at")

    def test_base_url_is_fixed(self):
        assert EVENTEE_BASE_URL == "https://api.eventee.com/public/v1"
