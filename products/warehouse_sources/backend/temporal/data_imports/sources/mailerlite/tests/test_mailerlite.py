import json
from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import ChunkedEncodingError, HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite import (
    MAILERLITE_BASE_URL,
    MailerLiteResumeConfig,
    get_rows,
    mailerlite_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import ENDPOINTS


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(items: list[dict[str, Any]], next_url: str | None) -> dict[str, Any]:
    return {"data": items, "links": {"next": next_url}, "meta": {}}


def _drive_get_rows(
    endpoint: str, manager: MagicMock, responses: list[Response]
) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """Run get_rows against a mocked tracked session, returning (yielded_batches, fetched_urls)."""
    fetched_urls: list[str] = []
    response_iter = iter(responses)

    def fake_get(url: str, *_args: Any, **_kwargs: Any) -> Response:
        fetched_urls.append(url)
        return next(response_iter)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite.make_tracked_session"
    ) as MockSession:
        mock_session = MockSession.return_value
        mock_session.get.side_effect = fake_get

        batches = list(get_rows("test-key", endpoint, MagicMock(), manager))
        return batches, fetched_urls


class TestGetRows:
    def test_follows_links_next_across_pages(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        next_url = f"{MAILERLITE_BASE_URL}/subscribers?cursor=abc&limit=100"
        responses = [
            _make_response(_page([{"id": "1"}], next_url)),
            _make_response(_page([{"id": "2"}], None)),
        ]

        batches, fetched_urls = _drive_get_rows("subscribers", manager, responses)

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        assert fetched_urls[0] == f"{MAILERLITE_BASE_URL}/subscribers?limit=100"
        assert fetched_urls[1] == next_url

    def test_saves_state_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        next_url_1 = f"{MAILERLITE_BASE_URL}/groups?page=2&limit=100"
        next_url_2 = f"{MAILERLITE_BASE_URL}/groups?page=3&limit=100"
        responses = [
            _make_response(_page([{"id": "1"}], next_url_1)),
            _make_response(_page([{"id": "2"}], next_url_2)),
            _make_response(_page([{"id": "3"}], None)),
        ]

        _drive_get_rows("groups", manager, responses)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            MailerLiteResumeConfig(next_url=next_url_1),
            MailerLiteResumeConfig(next_url=next_url_2),
        ]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_make_response(_page([{"id": "only"}], None))]

        _drive_get_rows("groups", manager, responses)

        manager.save_state.assert_not_called()

    def test_resume_starts_from_saved_url(self) -> None:
        resumed_url = f"{MAILERLITE_BASE_URL}/subscribers?cursor=resumed&limit=100"
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = MailerLiteResumeConfig(next_url=resumed_url)
        responses = [_make_response(_page([{"id": "9"}], None))]

        _, fetched_urls = _drive_get_rows("subscribers", manager, responses)

        assert fetched_urls == [resumed_url]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_make_response(_page([{"id": "1"}], None))]

        _drive_get_rows("subscribers", manager, responses)

        manager.load_state.assert_not_called()

    def test_empty_page_yields_nothing_and_stops(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_make_response(_page([], None))]

        batches, _ = _drive_get_rows("groups", manager, responses)

        assert batches == []
        manager.save_state.assert_not_called()

    def test_chunked_encoding_error_is_retried(self) -> None:
        # A mid-stream connection drop while reading the body raises ChunkedEncodingError, which
        # must be retried so a single dropped connection doesn't fail the whole import.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        good_response = _make_response(_page([{"id": "1"}], None))
        attempts: Iterator[ChunkedEncodingError | Response] = iter(
            [
                ChunkedEncodingError("Connection broken: InvalidChunkLength(got length b'', 0 bytes read)"),
                good_response,
            ]
        )

        def fake_get(url: str, *_args: Any, **_kwargs: Any) -> Response:
            result = next(attempts)
            if isinstance(result, Exception):
                raise result
            return result

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite.make_tracked_session"
            ) as MockSession,
            patch("tenacity.nap.time.sleep"),
        ):
            MockSession.return_value.get.side_effect = fake_get
            batches = list(get_rows("test-key", "subscribers", MagicMock(), manager))

        assert batches == [[{"id": "1"}]]
        assert MockSession.return_value.get.call_count == 2

    def test_chunked_encoding_error_eventually_reraises(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite.make_tracked_session"
            ) as MockSession,
            patch("tenacity.nap.time.sleep"),
        ):
            MockSession.return_value.get.side_effect = ChunkedEncodingError("Connection broken")
            with pytest.raises(ChunkedEncodingError):
                list(get_rows("test-key", "subscribers", MagicMock(), manager))

        assert MockSession.return_value.get.call_count == 5

    def test_non_retryable_status_raises(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_make_response({"message": "Not Found"}, status_code=404)]

        with pytest.raises(HTTPError):
            _drive_get_rows("groups", manager, responses)

    @pytest.mark.parametrize(
        "off_host_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.example.com/api/subscribers?cursor=abc",
            "https://connect.mailerlite.com.evil.com/api/subscribers",
        ],
    )
    def test_off_host_next_url_is_ignored(self, off_host_url: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_make_response(_page([{"id": "1"}], off_host_url))]

        batches, fetched_urls = _drive_get_rows("subscribers", manager, responses)

        # The tampered next URL is dropped: we yield the first page and stop without following it.
        assert batches == [[{"id": "1"}]]
        assert fetched_urls == [f"{MAILERLITE_BASE_URL}/subscribers?limit=100"]
        manager.save_state.assert_not_called()

    def test_off_host_resume_url_raises(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = MailerLiteResumeConfig(next_url="http://169.254.169.254/latest/meta-data/")

        with pytest.raises(ValueError, match="unexpected URL"):
            _drive_get_rows("subscribers", manager, [])


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_maps_to_bool(self, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_response({}, status_code=status_code)
            assert validate_credentials("key") is expected

    def test_exception_returns_false(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") is False


class TestMailerLiteSource:
    def test_partitioned_endpoint_response_shape(self) -> None:
        response = mailerlite_source("key", "subscribers", MagicMock(), MagicMock(spec=ResumableSourceManager))

        assert response.name == "subscribers"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["created_at"]

    def test_unpartitioned_endpoint_has_no_partition(self) -> None:
        response = mailerlite_source("key", "fields", MagicMock(), MagicMock(spec=ResumableSourceManager))

        assert response.partition_mode is None
        assert response.partition_format is None
        assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = mailerlite_source("key", endpoint, MagicMock(), MagicMock(spec=ResumableSourceManager))
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
