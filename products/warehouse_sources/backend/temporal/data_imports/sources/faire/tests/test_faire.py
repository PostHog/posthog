import json
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.faire.faire import (
    FairePaginator,
    FaireResumeConfig,
    faire_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the faire module.
FAIRE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.faire.faire.make_tracked_session"
)


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: FaireResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return faire_source(
        api_key="token",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFairePaginator:
    @parameterized.expand(
        [
            ("cursor_present", {"cursor": "next-page"}, True),
            ("cursor_absent", {"orders": []}, False),
            ("cursor_empty_string", {"cursor": ""}, False),
        ]
    )
    def test_update_state_reads_cursor(self, _name: str, body: dict[str, Any], expected_has_next: bool) -> None:
        paginator = FairePaginator(limit=50, filter_params=())

        paginator.update_state(_response(body))

        assert paginator.has_next_page is expected_has_next


class TestFaireSourceOrdersAndProducts:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_cursor_disappears(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"orders": [{"id": "1"}, {"id": "2"}], "cursor": "page-2"}),
                _response({"orders": [{"id": "3"}]}),
            ],
        )

        rows = _rows(_source("Orders", _make_manager()))

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert session.send.call_count == 2
        assert snapshots[0]["url"] == "https://www.faire.com/external-api/v2/orders"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_field_adds_updated_at_min(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"orders": [{"id": "1"}]})])

        _rows(
            _source(
                "Orders",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-01-01T00:00:00Z",
            )
        )

        assert snapshots[0]["params"]["updated_at_min"] == "2026-01-01T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sync_client_does_not_follow_redirects(self, MockSession) -> None:
        # The token rides in a custom header requests preserves across cross-origin redirects, so
        # the sync client must pin allow_redirects off. RESTClient forwards the client config's
        # value into every send().
        session = MockSession.return_value
        send_kwargs: list[dict[str, Any]] = []
        response_iter = iter([_response({"orders": [{"id": "1"}]})])

        def _prepare(request: Any) -> mock.MagicMock:
            return mock.MagicMock()

        def _send(request: Any, **kwargs: Any) -> Response:
            send_kwargs.append(kwargs)
            return next(response_iter)

        session.headers = {}
        session.prepare_request.side_effect = _prepare
        session.send.side_effect = _send

        _rows(_source("Orders", _make_manager()))

        assert send_kwargs and all(kw.get("allow_redirects") is False for kw in send_kwargs)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"orders": [{"id": "2"}]})])

        rows = _rows(_source("Orders", _make_manager(FaireResumeConfig(cursor="page-2"))))

        assert [r["id"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"] == {"cursor": "page-2", "limit": 50}


class TestFaireSourceBrand:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_never_saves_resume_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"brand_id": "b1"})])

        manager = _make_manager()
        _rows(_source("Brand", manager))

        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @mock.patch(FAIRE_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("token") == (True, 200)
