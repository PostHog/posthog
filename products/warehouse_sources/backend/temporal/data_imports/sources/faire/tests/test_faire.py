import json
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import PreparedRequest, Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.faire.faire import (
    FairePaginator,
    FaireResumeConfig,
    faire_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.faire.settings import FAIRE_ENDPOINTS

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
    def test_init_request_sets_limit(self) -> None:
        paginator = FairePaginator(limit=50, filter_params=("updated_at_min",))
        request = Request(params={"updated_at_min": "2026-01-01"})

        paginator.init_request(request)

        assert request.params == {"updated_at_min": "2026-01-01", "limit": 50}

    def test_init_request_applies_seeded_cursor(self) -> None:
        paginator = FairePaginator(limit=50, filter_params=("updated_at_min", "sort_by"))
        paginator.set_resume_state({"cursor": "resume-cursor"})
        request = Request(params={"updated_at_min": "2026-01-01", "sort_by": "UPDATED_AT"})

        paginator.init_request(request)

        assert request.params == {"cursor": "resume-cursor", "limit": 50}

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

    def test_update_request_drops_filter_params_and_sets_cursor(self) -> None:
        paginator = FairePaginator(limit=50, filter_params=("updated_at_min", "sku"))
        paginator.update_state(_response({"cursor": "abc"}))
        request = Request(params={"updated_at_min": "2026-01-01", "sku": "SKU1", "page": 1})

        paginator.update_request(request)

        assert request.params == {"cursor": "abc", "limit": 50}

    def test_resume_state_round_trips(self) -> None:
        paginator = FairePaginator(limit=50, filter_params=())
        paginator.update_state(_response({"cursor": "abc"}))

        state = paginator.get_resume_state()
        assert state == {"cursor": "abc"}

        resumed = FairePaginator(limit=50, filter_params=())
        resumed.set_resume_state(state or {})
        assert resumed.has_next_page is True

    def test_no_resume_state_once_exhausted(self) -> None:
        paginator = FairePaginator(limit=50, filter_params=())
        paginator.update_state(_response({"orders": []}))

        assert paginator.get_resume_state() is None


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
    def test_first_page_carries_sort_by_and_limit(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"orders": [{"id": "1"}]})])

        _rows(_source("Orders", _make_manager()))

        assert snapshots[0]["params"] == {"sort_by": "UPDATED_AT", "limit": 50}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_second_page_drops_filters_and_keeps_only_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response({"orders": [{"id": "1"}], "cursor": "next"}),
                _response({"orders": [{"id": "2"}]}),
            ],
        )

        _rows(_source("Orders", _make_manager()))

        assert snapshots[1]["params"] == {"cursor": "next", "limit": 50}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_products_uses_its_own_page_size_and_filters(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"products": [{"id": "p1"}]})])

        rows = _rows(_source("Products", _make_manager()))

        assert [r["id"] for r in rows] == ["p1"]
        assert snapshots[0]["params"] == {"limit": 250}

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
    def test_non_incremental_sync_omits_updated_at_min(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"orders": [{"id": "1"}]})])

        _rows(_source("Orders", _make_manager(), should_use_incremental_field=False))

        assert "updated_at_min" not in snapshots[0]["params"]

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
    def test_auth_uses_faire_access_token_header(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"orders": [{"id": "1"}]})])

        _rows(_source("Orders", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, APIKeyAuth)
        assert auth.api_key == "token"
        assert auth.name == "X-FAIRE-ACCESS-TOKEN"
        assert auth.location == "header"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"orders": [{"id": "1"}], "cursor": "page-2"}),
                _response({"orders": [{"id": "2"}]}),
            ],
        )

        manager = _make_manager()
        _rows(_source("Orders", manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FaireResumeConfig(cursor="page-2")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"orders": [{"id": "2"}]})])

        rows = _rows(_source("Orders", _make_manager(FaireResumeConfig(cursor="page-2"))))

        assert [r["id"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"] == {"cursor": "page-2", "limit": 50}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page_without_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"orders": []})])

        manager = _make_manager()
        rows = _rows(_source("Orders", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestFaireSourceBrand:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_returns_single_row_from_root_object(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"brand_id": "b1", "name": "Acme Co"})])

        rows = _rows(_source("Brand", _make_manager()))

        assert rows == [{"brand_id": "b1", "name": "Acme Co"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_never_saves_resume_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"brand_id": "b1"})])

        manager = _make_manager()
        _rows(_source("Brand", manager))

        manager.save_state.assert_not_called()

    def test_returned_source_response_uses_brand_id_primary_key(self) -> None:
        assert FAIRE_ENDPOINTS["Brand"].primary_keys == ["brand_id"]
        assert FAIRE_ENDPOINTS["Brand"].partition_key is None


class TestValidateCredentials:
    @mock.patch(FAIRE_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("token") == (True, 200)

    @mock.patch(FAIRE_SESSION_PATCH)
    def test_unauthorized(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("token") == (False, 401)

    @mock.patch(FAIRE_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") == (False, None)

    @mock.patch(FAIRE_SESSION_PATCH)
    def test_probes_brand_profile_with_access_token_header(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("token")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://www.faire.com/external-api/v2/brands/profile"
        assert call.kwargs["headers"]["X-FAIRE-ACCESS-TOKEN"] == "token"
        assert call.kwargs["allow_redirects"] is False


def test_prepared_request_type_is_used_for_auth() -> None:
    # Sanity check that APIKeyAuth is callable against a PreparedRequest, matching how the
    # framework applies auth — guards against a signature mismatch going unnoticed.
    auth = APIKeyAuth(api_key="token", name="X-FAIRE-ACCESS-TOKEN", location="header")
    prepared = PreparedRequest()
    prepared.headers = {}  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
    auth(prepared)
    assert prepared.headers["X-FAIRE-ACCESS-TOKEN"] == "token"
