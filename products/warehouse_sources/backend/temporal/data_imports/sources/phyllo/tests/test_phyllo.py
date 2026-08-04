import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.phyllo import (
    PAGE_SIZE,
    PhylloResumeConfig,
    get_base_url,
    phyllo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.settings import ENDPOINTS, PHYLLO_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the phyllo module.
PHYLLO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.phyllo.make_tracked_session"
)
# Backoff sleeps happen inside tenacity; patch its clock so retry tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"

PROD_URL = "https://api.getphyllo.com"


def _response(items: list[dict[str, Any]] | None, *, drop_data: bool = False, status_code: int = 200) -> Response:
    body: dict[str, Any] = {"metadata": {"limit": PAGE_SIZE}}
    if not drop_data:
        body["data"] = items if items is not None else []
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.url = f"{PROD_URL}/probe"
    return resp


def _make_manager(resume_state: PhylloResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire_seq(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Sequential wiring: snapshot each request's params at prepare time (the params dict is mutated
    in place across pages) and return responses in order."""
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _wire_routed(session: mock.MagicMock, routes: list[tuple[str, Response]]) -> list[str]:
    """Dispatch each request to the first still-unconsumed route whose substring appears in the
    fully-prepared URL. Real ``Request.prepare()`` builds the URL (merging the path-embedded query
    with the params dict and applying Basic auth) so fan-out and pagination route deterministically.
    Returns the URLs sent, in order."""
    session.headers = {}
    sent_urls: list[str] = []
    remaining = list(routes)

    def _prepare(request: Any) -> Any:
        return request.prepare()

    def _send(prepared: Any, **kwargs: Any) -> Response:
        sent_urls.append(prepared.url)
        for i, (substr, response) in enumerate(remaining):
            if substr in prepared.url:
                remaining.pop(i)
                return response
        raise AssertionError(f"no route for {prepared.url}")

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return sent_urls


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def _source(endpoint: str, manager: mock.MagicMock, environment: str = "production") -> Any:
    return phyllo_source(
        client_id="cid",
        client_secret="cs-secret",
        environment=environment,
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_short_page_yields_and_stops(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire_seq(session, [_response([{"id": "a"}, {"id": "b"}])])

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert rows == [{"id": "a"}, {"id": "b"}]
        assert session.send.call_count == 1
        # A short page ends the sync without persisting resume state.
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advances_offset_until_short_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        full = [{"id": f"a{i}"} for i in range(PAGE_SIZE)]
        params = _wire_seq(session, [_response(full), _response([{"id": "z"}])])

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert rows == [*full, {"id": "z"}]
        # The full first page advances the offset to PAGE_SIZE; the short page then terminates.
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        # State saved once — after the full first page, pointing at the next offset.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].paginator_state == {"offset": PAGE_SIZE}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire_seq(session, [_response([{"id": "z"}])])

        manager = _make_manager(PhylloResumeConfig(paginator_state={"offset": PAGE_SIZE}))
        rows = _rows(_source("users", manager))

        assert rows == [{"id": "z"}]
        # Offset 0 must never be fetched on resume.
        assert params[0]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_legacy_resume_state_starts_over(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire_seq(session, [_response([{"id": "a"}])])

        # State written by the previous hand-rolled implementation still deserializes (compat) but
        # carries no framework paginator snapshot, so the sync restarts from the first page.
        legacy = PhylloResumeConfig(offset=PAGE_SIZE, account_id="acc_gone")
        assert legacy.paginator_state is None
        rows = _rows(_source("users", _make_manager(legacy)))

        assert rows == [{"id": "a"}]
        assert params[0]["offset"] == 0

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire_seq(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("users", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rows_extracted_from_data_selector(self, MockSession: mock.MagicMock) -> None:
        # Phyllo wraps list results in {"data": [...], "metadata": {...}}; metadata must not leak.
        session = MockSession.return_value
        _wire_seq(session, [_response([{"id": "wp1"}])])

        rows = _rows(_source("work_platforms", _make_manager()))
        assert rows == [{"id": "wp1"}]


class TestAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_basic_auth_header_set_on_request(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        session.headers = {}
        captured: dict[str, str] = {}

        def _prepare(request: Any) -> Any:
            prepared = request.prepare()
            captured.update(prepared.headers)
            return prepared

        def _send(prepared: Any, **kwargs: Any) -> Response:
            return _response([{"id": "a"}])

        session.prepare_request.side_effect = _prepare
        session.send.side_effect = _send

        _rows(_source("users", _make_manager()))

        # Basic auth is base64(client_id:client_secret) — same as the old hand-built header.
        assert captured["Authorization"].startswith("Basic ")


class TestFanOut:
    ACCOUNTS_SUBSTR = "v1/accounts"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_accounts_via_account_id_query_param(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls = _wire_routed(
            session,
            [
                (self.ACCOUNTS_SUBSTR, _response([{"id": "acc_a"}, {"id": "acc_b"}])),
                ("account_id=acc_a", _response([{"id": "c1"}])),
                ("account_id=acc_b", _response([{"id": "c2"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("social_contents", manager))

        # Child rows keep their own shape (no account_id injected).
        assert rows == [{"id": "c1"}, {"id": "c2"}]
        assert _query(urls[1])["account_id"] == ["acc_a"]
        assert _query(urls[2])["account_id"] == ["acc_b"]
        # Single-hop fan-out keeps resume: the dependent resource checkpoints per-parent progress.
        assert manager.save_state.called
        assert "completed" in manager.save_state.call_args.args[0].paginator_state

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_full_page_within_account(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        full = [{"id": f"c{i}"} for i in range(PAGE_SIZE)]
        urls = _wire_routed(
            session,
            [
                (self.ACCOUNTS_SUBSTR, _response([{"id": "acc_a"}])),
                ("offset=100", _response([{"id": "last"}])),
                ("account_id=acc_a", _response(full)),
            ],
        )

        rows = _rows(_source("social_contents", _make_manager()))

        assert rows == [*full, {"id": "last"}]
        first_page = next(u for u in urls if "account_id=acc_a" in u and "offset=100" not in u)
        second_page = next(u for u in urls if "offset=100" in u)
        assert _query(first_page)["offset"] == ["0"]
        assert _query(second_page)["offset"] == ["100"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_accounts(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls = _wire_routed(
            session,
            [
                (self.ACCOUNTS_SUBSTR, _response([{"id": "acc_a"}, {"id": "acc_b"}])),
                ("account_id=acc_b", _response([{"id": "b1"}])),
            ],
        )

        # acc_a's child page is already checkpointed as completed, so only acc_b is fetched.
        manager = _make_manager(
            PhylloResumeConfig(paginator_state={"completed": ["/v1/social/contents?account_id=acc_a"], "current": None})
        )
        rows = _rows(_source("social_contents", manager))

        assert rows == [{"id": "b1"}]
        assert _query(urls[1])["account_id"] == ["acc_b"]
        assert not any("account_id=acc_a" in u for u in urls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_offset_applies_only_to_bookmarked_account(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls = _wire_routed(
            session,
            [
                (self.ACCOUNTS_SUBSTR, _response([{"id": "acc_a"}, {"id": "acc_b"}])),
                ("account_id=acc_a", _response([{"id": "a9"}])),
                ("account_id=acc_b", _response([{"id": "b1"}])),
            ],
        )

        manager = _make_manager(
            PhylloResumeConfig(
                paginator_state={
                    "completed": [],
                    "current": "/v1/social/contents?account_id=acc_a",
                    "child_state": {"offset": PAGE_SIZE},
                }
            )
        )
        _rows(_source("social_contents", manager))

        acc_a_url = next(u for u in urls if "account_id=acc_a" in u)
        acc_b_url = next(u for u in urls if "account_id=acc_b" in u)
        assert _query(acc_a_url)["offset"] == [str(PAGE_SIZE)]
        # The next account starts a fresh page chain from offset 0.
        assert _query(acc_b_url)["offset"] == ["0"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_disconnected_bookmarked_account_does_not_leak_offset(self, MockSession: mock.MagicMock) -> None:
        # The bookmarked account was disconnected between runs; the saved offset must not leak into
        # the remaining account's pagination.
        session = MockSession.return_value
        urls = _wire_routed(
            session,
            [
                (self.ACCOUNTS_SUBSTR, _response([{"id": "acc_a"}, {"id": "acc_c"}])),
                ("account_id=acc_a", _response([{"id": "a1"}])),
                ("account_id=acc_c", _response([{"id": "c1"}])),
            ],
        )

        manager = _make_manager(
            PhylloResumeConfig(
                paginator_state={
                    "completed": [],
                    "current": "/v1/social/contents?account_id=acc_b",
                    "child_state": {"offset": PAGE_SIZE},
                }
            )
        )
        rows = _rows(_source("social_contents", manager))

        assert rows == [{"id": "a1"}, {"id": "c1"}]
        assert _query(next(u for u in urls if "account_id=acc_a" in u))["offset"] == ["0"]
        assert _query(next(u for u in urls if "account_id=acc_c" in u))["offset"] == ["0"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_accounts_listing_itself(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        first_accounts = [{"id": f"acc_{i:03d}"} for i in range(PAGE_SIZE)]
        routes = [
            ("accounts?offset=100", _response([{"id": "acc_zzz"}])),
            (self.ACCOUNTS_SUBSTR, _response(first_accounts)),
        ]
        for account in [*first_accounts, {"id": "acc_zzz"}]:
            routes.append((f"account_id={account['id']}", _response([{"id": f"content_{account['id']}"}])))
        _wire_routed(session, routes)

        rows = _rows(_source("social_contents", _make_manager()))
        assert len(rows) == PAGE_SIZE + 1


class TestMalformedBody:
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_top_level_malformed_body_is_retried_then_recovers(
        self, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        # A 200 body without "data" is treated as transient (the old fetch raised a retryable error
        # on the same condition); the request is re-issued and recovers.
        session = MockSession.return_value
        _wire_seq(session, [_response(None, drop_data=True), _response([{"id": "a"}])])

        rows = _rows(_source("users", _make_manager()))
        assert rows == [{"id": "a"}]
        assert session.send.call_count == 2

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_top_level_persistent_malformed_body_reraises(
        self, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: mock.MagicMock()
        session.send.return_value = _response(None, drop_data=True)

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("users", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_child_malformed_body_fails_loud(self, MockSession: mock.MagicMock) -> None:
        # Dependent resources can't classify a malformed body as retryable, so the child fails loud
        # rather than silently syncing 0 rows.
        session = MockSession.return_value
        _wire_routed(
            session,
            [
                ("v1/accounts", _response([{"id": "acc_a"}])),
                ("account_id=acc_a", _response(None, drop_data=True)),
            ],
        )

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("social_contents", _make_manager()))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Phyllo client ID or secret for the selected environment"),
            ("forbidden", 403, False, "Invalid Phyllo client ID or secret for the selected environment"),
            ("server_error", 500, False, "Phyllo returned HTTP 500"),
        ]
    )
    @mock.patch(PHYLLO_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status
        mock_session.return_value.get.return_value = response

        assert validate_credentials("cid", "cs-secret", "production") == (expected_valid, expected_message)

    @mock.patch(PHYLLO_SESSION_PATCH)
    def test_connection_error_swallowed(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("cid", "cs-secret", "production") == (
            False,
            "Could not validate Phyllo credentials",
        )

    @mock.patch(PHYLLO_SESSION_PATCH)
    def test_sandbox_environment_probes_sandbox_host(self, mock_session: mock.MagicMock) -> None:
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response
        validate_credentials("cid", "cs-secret", "sandbox")
        assert mock_session.return_value.get.call_args.args[0].startswith("https://api.sandbox.getphyllo.com")


class TestPhylloSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire_routed(session, [])
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Phyllo doesn't guarantee ordering or a stable creation timestamp, so we don't partition.
        assert response.partition_mode is None

    def test_fan_out_endpoints_are_account_scoped(self) -> None:
        # These endpoints require an account_id query param; a config regression here would 400 on
        # every page.
        fan_out = {name for name, config in PHYLLO_ENDPOINTS.items() if config.fan_out_by_account}
        assert fan_out == {"social_contents", "income_transactions", "income_payouts"}

    @parameterized.expand(
        [("production", "https://api.getphyllo.com"), ("sandbox", "https://api.sandbox.getphyllo.com")]
    )
    def test_get_base_url(self, environment: str, expected: str) -> None:
        assert get_base_url(environment) == expected
