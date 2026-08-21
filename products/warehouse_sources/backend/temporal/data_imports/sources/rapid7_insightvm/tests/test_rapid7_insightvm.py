import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.rapid7_insightvm import (
    Rapid7InsightvmResumeConfig,
    rapid7_insightvm_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the rapid7_insightvm module.
TRANSPORT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.rapid7_insightvm.make_tracked_session"


def _page(items: list[dict[str, Any]] | None, cursor: str | None) -> Response:
    body: dict[str, Any] = {"data": items or [], "metadata": {"cursor": cursor} if cursor is not None else {}}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error(status: int, body: dict[str, Any] | None = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body or {}).encode()
    return resp


def _redirect(location: str = "https://evil.example.com/") -> Response:
    resp = Response()
    resp.status_code = 302
    resp.headers["Location"] = location
    resp._content = b""
    return resp


def _make_manager(resume_state: Rapid7InsightvmResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's query params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than reading the final state after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = "https://us.api.insight.rapid7.com/vm/v4/integration/assets"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(responses: list[Response], manager: mock.MagicMock) -> tuple[list[dict[str, Any]], mock.MagicMock, list[dict]]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        params = _wire(session, responses)
        rows = _rows(
            rapid7_insightvm_source(
                api_key="key",
                region="us",
                endpoint="assets",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
            )
        )
    return rows, session, params


class TestPagination:
    def test_walks_pages_until_cursor_missing(self) -> None:
        pages = [
            _page([{"id": 1}], cursor="c1"),
            _page([{"id": 2}], cursor="c2"),
            _page([{"id": 3}], cursor=None),
        ]
        rows, session, _ = _run(pages, _make_manager())

        assert [row["id"] for row in rows] == [1, 2, 3]
        assert session.send.call_count == 3

    def test_terminates_when_cursor_repeats(self) -> None:
        # Some deployments echo the last cursor instead of dropping it; a naive loop would spin forever.
        pages = [_page([{"id": 1}], cursor="c1"), _page([{"id": 2}], cursor="c1")]
        rows, session, _ = _run(pages, _make_manager())

        assert [row["id"] for row in rows] == [1, 2]
        assert session.send.call_count == 2

    def test_terminates_on_empty_page(self) -> None:
        rows, session, _ = _run([_page([], cursor="c1")], _make_manager())

        assert rows == []
        assert session.send.call_count == 1

    def test_first_request_carries_size_and_no_cursor(self) -> None:
        _, _, params = _run([_page([{"id": 1}], cursor=None)], _make_manager())

        assert params[0]["size"] == 1000
        assert "cursor" not in params[0]

    def test_saves_cursor_after_each_yielded_batch(self) -> None:
        pages = [
            _page([{"id": 1}], cursor="c1"),
            _page([{"id": 2}], cursor="c2"),
            _page([{"id": 3}], cursor=None),
        ]
        manager = _make_manager()
        _run(pages, manager)

        # State is persisted only for pages with a successor cursor (c1, c2); the final page (no next
        # cursor) saves nothing, so a resumed run re-yields the last page rather than skipping it.
        assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["c1", "c2"]

    def test_resumes_from_saved_cursor(self) -> None:
        manager = _make_manager(Rapid7InsightvmResumeConfig(cursor="saved-cursor"))
        _, _, params = _run([_page([{"id": 99}], cursor=None)], manager)

        # The first (and only) request must carry the saved cursor as its starting point.
        assert params[0]["cursor"] == "saved-cursor"


class TestRetryAndErrorClassification:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_are_reissued(self, status: int) -> None:
        # A 429/5xx is transient: the client reissues the request rather than failing loud.
        with mock.patch("time.sleep"):
            rows, session, _ = _run([_error(status), _page([{"id": 1}], cursor=None)], _make_manager())

        assert [row["id"] for row in rows] == [1]
        assert session.send.call_count == 2

    def test_client_error_raises_http_error(self) -> None:
        # A 403 is permanent — surface it as an HTTPError instead of retrying.
        with pytest.raises(HTTPError):
            _run([_error(403)], _make_manager())


class TestCredentialedSessionIsHardened:
    def test_redirect_is_rejected(self) -> None:
        # A 3xx from the credentialed endpoint would replay `X-Api-Key` to the redirect target;
        # the client pins redirects off and rejects any 3xx before following it.
        with pytest.raises(ValueError, match="refusing to follow"):
            _run([_redirect()], _make_manager())

    def test_api_key_is_redacted_from_errors(self) -> None:
        # The key must never leak into a user-visible error message.
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            _wire(session, [_redirect(location="https://us.api.insight.rapid7.com/?token=super-secret-key")])
            with pytest.raises(ValueError) as exc:
                _rows(
                    rapid7_insightvm_source(
                        api_key="super-secret-key",
                        region="us",
                        endpoint="assets",
                        team_id=1,
                        job_id="j",
                        resumable_source_manager=_make_manager(),
                    )
                )
        assert "super-secret-key" not in str(exc.value)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_maps_to_validity(self, status: int, expected_valid: bool) -> None:
        session = mock.MagicMock()
        session.post.return_value = mock.MagicMock(status_code=status)
        with mock.patch(TRANSPORT_SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is expected_valid
        assert (message is None) is expected_valid

    def test_network_error_is_not_valid(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = requests.ConnectionError("boom")
        with mock.patch(TRANSPORT_SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials("key", "us")

        assert is_valid is False
        assert message is not None

    def test_probe_pins_redirects_off_and_redacts_key(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = mock.MagicMock(status_code=200)
        with mock.patch(TRANSPORT_SESSION_PATCH, return_value=session) as factory:
            validate_credentials("secret-key", "us")

        factory.assert_called_once_with(redact_values=("secret-key",), allow_redirects=False)


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", ["assets", "vulnerabilities"])
    def test_full_refresh_endpoints_have_no_partitioning(self, endpoint: str) -> None:
        response = rapid7_insightvm_source(
            api_key="key",
            region="us",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
