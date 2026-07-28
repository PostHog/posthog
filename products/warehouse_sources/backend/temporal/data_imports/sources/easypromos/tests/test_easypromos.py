import json
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, cast

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos import easypromos
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.easypromos import (
    EASYPROMOS_BASE_URL,
    EasypromosResumeConfig,
    easypromos_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.settings import EASYPROMOS_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"

PROMOS_URL = f"{EASYPROMOS_BASE_URL}/promotions"


def _url(path: str) -> str:
    return f"{EASYPROMOS_BASE_URL}{path}"


def _body(items: list[dict[str, Any]], next_cursor: int | None) -> dict[str, Any]:
    return {"items": items, "paging": {"next_cursor": next_cursor, "items_page": 100}}


def _response(url: str, body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.url = url
    resp._content = json.dumps(body).encode()
    return resp


class _FakeSession:
    """Routes each prepared request to a canned page keyed by (url, next_cursor request param).

    ``request.params`` is mutated in place across pages by the paginator, so the key is snapshotted
    at prepare_request time (mirroring how the real session prepares each request).
    """

    def __init__(self, pages: dict[tuple[str, int | None], dict[str, Any]]) -> None:
        self._pages = pages
        self.headers: dict[str, str] = {}
        self.requests: list[tuple[str, int | None]] = []
        self._pending: tuple[str, int | None] | None = None

    def prepare_request(self, request: Any) -> Any:
        cursor = (request.params or {}).get("next_cursor")
        self._pending = (request.url, cursor)
        self.requests.append((request.url, cursor))
        return SimpleNamespace(url=request.url)

    def send(self, prepared: Any, **kwargs: Any) -> Response:
        assert self._pending is not None
        return _response(prepared.url, self._pages[self._pending])


def _make_manager(state: EasypromosResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = state
    manager.saved = []
    manager.save_state.side_effect = manager.saved.append
    return manager


def _rows(endpoint: str, manager: mock.MagicMock) -> list[dict[str, Any]]:
    response = easypromos_source(
        access_token="tok",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )
    return [row for page in cast("Iterable[Any]", response.items()) for row in page]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Easypromos access token"),
            ("forbidden_plan", 403, False, "does not have access to the REST API"),
            ("server_error", 500, False, "returned status 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_msg: str | None) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch.object(easypromos, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("tok")
        assert ok is expected_ok
        if expected_msg is None:
            assert error is None
        else:
            assert error is not None and expected_msg in error

    def test_request_exception_is_invalid(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch.object(easypromos, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("tok")
        assert ok is False
        assert error is not None


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_cursor_until_null(self, mock_session) -> None:
        mock_session.return_value = _FakeSession(
            {
                (PROMOS_URL, None): _body([{"id": 1}, {"id": 2}], 100),
                (PROMOS_URL, 100): _body([{"id": 3}], None),
            }
        )
        rows = _rows("promotions", _make_manager())
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_inject_promotion_id_for_top_level(self, mock_session) -> None:
        url = _url("/organizing_brands")
        mock_session.return_value = _FakeSession({(url, None): _body([{"id": 7, "name": "Acme"}], None)})
        rows = _rows("organizing_brands", _make_manager())
        assert rows == [{"id": 7, "name": "Acme"}]
        assert "promotion_id" not in rows[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, mock_session) -> None:
        # Only the resumed page is served; if the run started at the first page this would KeyError.
        session = _FakeSession({(PROMOS_URL, 100): _body([{"id": 3}], None)})
        mock_session.return_value = session
        rows = _rows("promotions", _make_manager(EasypromosResumeConfig(cursor=100)))
        assert rows == [{"id": 3}]
        assert session.requests == [(PROMOS_URL, 100)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_cursor_while_a_page_remains(self, mock_session) -> None:
        mock_session.return_value = _FakeSession(
            {
                (PROMOS_URL, None): _body([{"id": 1}], 100),
                (PROMOS_URL, 100): _body([{"id": 2}], None),
            }
        )
        manager = _make_manager()
        _rows("promotions", manager)
        # Checkpoint saved once, after the first page, pointing at the next cursor; the final (null)
        # page has no next cursor and is not checkpointed.
        assert manager.saved == [EasypromosResumeConfig(cursor=100)]


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_promotions_and_injects_promotion_id(self, mock_session) -> None:
        mock_session.return_value = _FakeSession(
            {
                (PROMOS_URL, None): _body([{"id": 10}, {"id": 20}], None),
                (_url("/users/10"), None): _body([{"id": 1}, {"id": 2}], None),
                (_url("/users/20"), None): _body([{"id": 1}], None),
            }
        )
        rows = _rows("users", _make_manager())
        assert rows == [
            {"id": 1, "promotion_id": 10},
            {"id": 2, "promotion_id": 10},
            {"id": 1, "promotion_id": 20},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_child_pagination(self, mock_session) -> None:
        mock_session.return_value = _FakeSession(
            {
                (PROMOS_URL, None): _body([{"id": 10}], None),
                (_url("/participations/10"), None): _body([{"id": 1}], 5),
                (_url("/participations/10"), 5): _body([{"id": 2}], None),
            }
        )
        rows = _rows("participations", _make_manager())
        assert rows == [{"id": 1, "promotion_id": 10}, {"id": 2, "promotion_id": 10}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_promotions_and_uses_child_cursor(self, mock_session) -> None:
        # Saved fan-out state: promotion 10 fully synced, mid-way through promotion 20 at child
        # cursor 5. Promotion 10's child endpoint must never be fetched (its page is not served, so
        # a fetch would KeyError); promotion 20 resumes at cursor 5; promotion 30 runs fresh.
        session = _FakeSession(
            {
                (PROMOS_URL, None): _body([{"id": 10}, {"id": 20}, {"id": 30}], None),
                (_url("/users/20"), 5): _body([{"id": 9}], None),
                (_url("/users/30"), None): _body([{"id": 1}], None),
            }
        )
        mock_session.return_value = session
        manager = _make_manager(
            EasypromosResumeConfig(
                fanout_state={"completed": ["/users/10"], "current": "/users/20", "child_state": {"cursor": 5}}
            )
        )
        rows = _rows("users", manager)
        assert rows == [{"id": 9, "promotion_id": 20}, {"id": 1, "promotion_id": 30}]
        assert (_url("/users/10"), None) not in session.requests

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_records_fanout_progress(self, mock_session) -> None:
        mock_session.return_value = _FakeSession(
            {
                (PROMOS_URL, None): _body([{"id": 10}], None),
                (_url("/prizes/10"), None): _body([{"id": 1}], None),
            }
        )
        manager = _make_manager()
        _rows("prizes", manager)
        # The final checkpoint marks the promotion's child path complete so a restart skips it.
        assert manager.saved[-1] == EasypromosResumeConfig(
            fanout_state={"completed": ["/prizes/10"], "current": None, "child_state": None}
        )


class TestSourceResponse:
    @parameterized.expand(list(EASYPROMOS_ENDPOINTS.keys()))
    def test_primary_keys_and_partitioning_match_settings(self, endpoint: str) -> None:
        config = EASYPROMOS_ENDPOINTS[endpoint]
        response = easypromos_source(
            access_token="tok",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_fan_out_children_carry_promotion_id_in_primary_key(self) -> None:
        for endpoint, config in EASYPROMOS_ENDPOINTS.items():
            if config.fan_out_over_promotions:
                assert "promotion_id" in config.primary_keys, endpoint
