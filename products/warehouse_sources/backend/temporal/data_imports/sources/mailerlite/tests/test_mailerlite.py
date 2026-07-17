import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import ChunkedEncodingError, HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite import (
    MAILERLITE_BASE_URL,
    MailerLiteResumeConfig,
    mailerlite_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the mailerlite module.
MAILERLITE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite.make_tracked_session"
)


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(items: list[dict[str, Any]], next_url: str | None) -> Response:
    return _make_response({"data": items, "links": {"next": next_url}, "meta": {}})


def _make_manager(resume: MailerLiteResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: MagicMock, responses: Any) -> list[str]:
    """Wire a mock session and return the URLs each request is actually sent to.

    ``_check_allowed_host`` reads ``prepared.url``, so prepare_request must return a real
    ``PreparedRequest`` whose URL reflects the request's URL + params for that page. The
    next-page URL is followed with an empty params dict, so its ``prepared.url`` echoes the
    absolute ``links.next`` exactly.
    """
    session.headers = {}
    sent_urls: list[str] = []

    def _prepare(request: Any) -> Any:
        prepared = request.prepare()
        sent_urls.append(prepared.url)
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return sent_urls


def _run(endpoint: str, manager: MagicMock, responses: Any) -> tuple[list[list[dict[str, Any]]], list[str], MagicMock]:
    with patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        sent_urls = _wire(session, responses)
        source = mailerlite_source(
            api_key="test-key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager
        )
        batches = list(source.items())
    return batches, sent_urls, session


class TestPagination:
    def test_follows_links_next_across_pages(self) -> None:
        next_url = f"{MAILERLITE_BASE_URL}/subscribers?cursor=abc&limit=100"
        responses = [_page([{"id": "1"}], next_url), _page([{"id": "2"}], None)]

        batches, sent_urls, _ = _run("subscribers", _make_manager(), responses)

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        assert sent_urls[0] == f"{MAILERLITE_BASE_URL}/subscribers?limit=100"
        assert sent_urls[1] == next_url

    def test_saves_state_after_each_non_terminal_page(self) -> None:
        next_url_1 = f"{MAILERLITE_BASE_URL}/groups?page=2&limit=100"
        next_url_2 = f"{MAILERLITE_BASE_URL}/groups?page=3&limit=100"
        manager = _make_manager()
        responses = [
            _page([{"id": "1"}], next_url_1),
            _page([{"id": "2"}], next_url_2),
            _page([{"id": "3"}], None),
        ]

        _run("groups", manager, responses)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            MailerLiteResumeConfig(next_url=next_url_1),
            MailerLiteResumeConfig(next_url=next_url_2),
        ]

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = _make_manager()

        _run("groups", manager, [_page([{"id": "only"}], None)])

        manager.save_state.assert_not_called()

    def test_resume_starts_from_saved_url(self) -> None:
        resumed_url = f"{MAILERLITE_BASE_URL}/subscribers?cursor=resumed&limit=100"
        manager = _make_manager(MailerLiteResumeConfig(next_url=resumed_url))

        _, sent_urls, _ = _run("subscribers", manager, [_page([{"id": "9"}], None)])

        assert sent_urls == [resumed_url]
        manager.load_state.assert_called_once()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = _make_manager()

        _run("subscribers", manager, [_page([{"id": "1"}], None)])

        manager.load_state.assert_not_called()

    def test_empty_page_yields_nothing_and_stops(self) -> None:
        manager = _make_manager()

        batches, _, _ = _run("groups", manager, [_page([], None)])

        assert batches == []
        manager.save_state.assert_not_called()

    def test_non_retryable_status_raises(self) -> None:
        with pytest.raises(HTTPError):
            _run("groups", _make_manager(), [_make_response({"message": "Not Found"}, status_code=404)])

    @pytest.mark.parametrize(
        "off_host_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.example.com/api/subscribers?cursor=abc",
            "https://connect.mailerlite.com.evil.com/api/subscribers",
        ],
    )
    def test_off_host_next_url_is_ignored(self, off_host_url: str) -> None:
        # The custom paginator drops a tampered off-host ``next`` link, so we yield the first page
        # and stop without ever issuing (or checkpointing) the off-host request.
        manager = _make_manager()

        batches, sent_urls, _ = _run("subscribers", manager, [_page([{"id": "1"}], off_host_url)])

        assert batches == [[{"id": "1"}]]
        assert sent_urls == [f"{MAILERLITE_BASE_URL}/subscribers?limit=100"]
        manager.save_state.assert_not_called()

    def test_off_host_resume_url_raises(self) -> None:
        # A seeded resume URL pointing off-host is rejected by the client's allowed_hosts guard
        # before the authenticated request leaves the process.
        manager = _make_manager(MailerLiteResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"))

        with pytest.raises(ValueError, match="disallowed host"):
            _run("subscribers", manager, [])


class TestRetry:
    def test_chunked_encoding_error_is_retried(self) -> None:
        # A mid-stream connection drop while reading the body raises ChunkedEncodingError, which the
        # client reissues so a single dropped connection doesn't fail the whole import.
        manager = _make_manager()
        good = _page([{"id": "1"}], None)

        with patch(CLIENT_SESSION_PATCH) as MockSession, patch("tenacity.nap.time.sleep"):
            session = MockSession.return_value
            _wire(session, [ChunkedEncodingError("Connection broken: InvalidChunkLength"), good])
            source = mailerlite_source(
                api_key="test-key", endpoint="subscribers", team_id=1, job_id="j", resumable_source_manager=manager
            )
            batches = list(source.items())

        assert batches == [[{"id": "1"}]]
        assert session.send.call_count == 2

    def test_chunked_encoding_error_eventually_reraises(self) -> None:
        manager = _make_manager()

        with patch(CLIENT_SESSION_PATCH) as MockSession, patch("tenacity.nap.time.sleep"):
            session = MockSession.return_value
            _wire(session, ChunkedEncodingError("Connection broken"))
            source = mailerlite_source(
                api_key="test-key", endpoint="subscribers", team_id=1, job_id="j", resumable_source_manager=manager
            )
            with pytest.raises(RESTClientRetryableError):
                list(source.items())

        assert session.send.call_count == 5


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_maps_to_bool(self, status_code: int, expected: bool) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response({}, status_code=status_code)
            assert validate_credentials("key") is expected

    def test_exception_returns_false(self) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") is False


class TestMailerLiteSourceResponse:
    def test_partitioned_endpoint_response_shape(self) -> None:
        response = mailerlite_source(
            api_key="key", endpoint="subscribers", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.name == "subscribers"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["created_at"]

    def test_unpartitioned_endpoint_has_no_partition(self) -> None:
        response = mailerlite_source(
            api_key="key", endpoint="fields", team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.partition_mode is None
        assert response.partition_format is None
        assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = mailerlite_source(
            api_key="key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
