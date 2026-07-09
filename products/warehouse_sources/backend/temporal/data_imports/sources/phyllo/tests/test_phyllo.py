from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo import phyllo
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.phyllo import (
    PAGE_SIZE,
    PhylloResumeConfig,
    PhylloRetryableError,
    check_access,
    get_base_url,
    get_rows,
    phyllo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.settings import ENDPOINTS, PHYLLO_ENDPOINTS

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = phyllo._fetch_page.__wrapped__  # type: ignore[attr-defined]

PROD_URL = "https://api.getphyllo.com"


class _FakeResumableManager:
    def __init__(self, state: PhylloResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PhylloResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PhylloResumeConfig | None:
        return self._state

    def save_state(self, data: PhylloResumeConfig) -> None:
        self.saved.append(data)


def _page_of(count: int, prefix: str) -> list[dict]:
    return [{"id": f"{prefix}{i}"} for i in range(count)]


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[tuple[str, str | None, int], list[dict]],
        endpoint: str,
    ) -> list[dict]:
        def fake_fetch(session: Any, url: str, params: dict[str, Any], logger: Any) -> list[dict]:
            return pages[(url, params.get("account_id"), params["offset"])]

        monkeypatch.setattr(phyllo, "_fetch_page", fake_fetch)
        monkeypatch.setattr(phyllo, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            client_id="cid",
            client_secret="cs",
            environment="production",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_single_short_page_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        url = f"{PROD_URL}/v1/users"
        rows = self._collect(manager, monkeypatch, {(url, None, 0): [{"id": "a"}, {"id": "b"}]}, "users")
        assert rows == [{"id": "a"}, {"id": "b"}]
        # A short page ends the sync without persisting resume state.
        assert manager.saved == []

    def test_advances_offset_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        url = f"{PROD_URL}/v1/users"
        first = _page_of(PAGE_SIZE, "a")
        pages: dict[tuple[str, str | None, int], list[dict]] = {
            (url, None, 0): first,
            (url, None, PAGE_SIZE): [{"id": "z"}],
        }
        rows = self._collect(manager, monkeypatch, pages, "users")
        assert rows == [*first, {"id": "z"}]
        # State is saved once — after the full first page, pointing at the next offset — then we stop.
        assert [s.offset for s in manager.saved] == [PAGE_SIZE]
        assert manager.saved[0].account_id is None

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PhylloResumeConfig(offset=PAGE_SIZE))
        url = f"{PROD_URL}/v1/users"
        # Offset 0 must never be fetched on resume.
        pages: dict[tuple[str, str | None, int], list[dict]] = {(url, None, PAGE_SIZE): [{"id": "z"}]}
        rows = self._collect(manager, monkeypatch, pages, "users")
        assert rows == [{"id": "z"}]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        url = f"{PROD_URL}/v1/users"
        rows = self._collect(manager, monkeypatch, {(url, None, 0): []}, "users")
        assert rows == []
        assert manager.saved == []


class TestFanOutRows:
    ACCOUNTS_URL = f"{PROD_URL}/v1/accounts"
    CONTENTS_URL = f"{PROD_URL}/v1/social/contents"

    def _accounts_page(self, ids: list[str]) -> list[dict]:
        return [{"id": account_id} for account_id in ids]

    def test_iterates_accounts_in_sorted_order(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            (self.ACCOUNTS_URL, None, 0): self._accounts_page(["acc_b", "acc_a"]),
            (self.CONTENTS_URL, "acc_a", 0): [{"id": "c1"}],
            (self.CONTENTS_URL, "acc_b", 0): [{"id": "c2"}],
        }
        rows = TestGetRows._collect(manager, monkeypatch, pages, "social_contents")
        # Accounts are fetched in sorted order regardless of API listing order.
        assert rows == [{"id": "c1"}, {"id": "c2"}]
        # Finishing acc_a checkpoints past it so a crash doesn't replay it.
        assert [(s.account_id, s.offset) for s in manager.saved] == [("acc_b", 0)]

    def test_saves_state_after_each_full_page_within_account(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        full = _page_of(PAGE_SIZE, "c")
        pages = {
            (self.ACCOUNTS_URL, None, 0): self._accounts_page(["acc_a"]),
            (self.CONTENTS_URL, "acc_a", 0): full,
            (self.CONTENTS_URL, "acc_a", PAGE_SIZE): [{"id": "last"}],
        }
        rows = TestGetRows._collect(manager, monkeypatch, pages, "social_contents")
        assert rows == [*full, {"id": "last"}]
        assert [(s.account_id, s.offset) for s in manager.saved] == [("acc_a", PAGE_SIZE)]

    def test_resumes_mid_account_and_skips_earlier_accounts(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PhylloResumeConfig(offset=PAGE_SIZE, account_id="acc_b"))
        pages = {
            (self.ACCOUNTS_URL, None, 0): self._accounts_page(["acc_a", "acc_b", "acc_c"]),
            # acc_a must be skipped entirely; acc_b starts at the saved offset.
            (self.CONTENTS_URL, "acc_b", PAGE_SIZE): [{"id": "b2"}],
            (self.CONTENTS_URL, "acc_c", 0): [{"id": "c1"}],
        }
        rows = TestGetRows._collect(manager, monkeypatch, pages, "social_contents")
        assert rows == [{"id": "b2"}, {"id": "c1"}]

    def test_resume_with_disconnected_account_continues_from_next(self, monkeypatch: Any) -> None:
        # The saved account was disconnected between runs; the saved offset must not leak into the
        # next account's pagination.
        manager = _FakeResumableManager(PhylloResumeConfig(offset=PAGE_SIZE, account_id="acc_b"))
        pages = {
            (self.ACCOUNTS_URL, None, 0): self._accounts_page(["acc_a", "acc_c"]),
            (self.CONTENTS_URL, "acc_c", 0): [{"id": "c1"}],
        }
        rows = TestGetRows._collect(manager, monkeypatch, pages, "social_contents")
        assert rows == [{"id": "c1"}]

    def test_paginates_accounts_listing_itself(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first_accounts = self._accounts_page([f"acc_{i:03d}" for i in range(PAGE_SIZE)])
        pages: dict[tuple[str, str | None, int], list[dict]] = {
            (self.ACCOUNTS_URL, None, 0): first_accounts,
            (self.ACCOUNTS_URL, None, PAGE_SIZE): self._accounts_page(["acc_zzz"]),
        }
        for account in [*first_accounts, {"id": "acc_zzz"}]:
            pages[(self.CONTENTS_URL, account["id"], 0)] = [{"id": f"content_{account['id']}"}]
        rows = TestGetRows._collect(manager, monkeypatch, pages, "social_contents")
        assert len(rows) == PAGE_SIZE + 1


class TestFetchPage:
    def _session_returning(
        self, status_code: int, body: Any = None, headers: dict[str, str] | None = None
    ) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"data": [], "metadata": {}}
        response.text = ""
        response.headers = headers or {}
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(PhylloRetryableError):
            _fetch_page_unwrapped(session, f"{PROD_URL}/v1/users", {"limit": PAGE_SIZE, "offset": 0}, MagicMock())

    def test_rate_limit_honors_retry_after_header(self) -> None:
        session = self._session_returning(429, headers={"Retry-After": "2"})
        with patch.object(phyllo.time, "sleep") as mock_sleep:
            with pytest.raises(PhylloRetryableError):
                _fetch_page_unwrapped(session, f"{PROD_URL}/v1/users", {"limit": PAGE_SIZE, "offset": 0}, MagicMock())
        mock_sleep.assert_called_once_with(2.0)

    @parameterized.expand([("missing", None), ("malformed", "soon"), ("negative", "-1")])
    def test_unusable_retry_after_skips_sleep(self, _name: str, header_value: str | None) -> None:
        headers = {"Retry-After": header_value} if header_value is not None else {}
        session = self._session_returning(429, headers=headers)
        with patch.object(phyllo.time, "sleep") as mock_sleep:
            with pytest.raises(PhylloRetryableError):
                _fetch_page_unwrapped(session, f"{PROD_URL}/v1/users", {"limit": PAGE_SIZE, "offset": 0}, MagicMock())
        mock_sleep.assert_not_called()

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, f"{PROD_URL}/v1/users", {"limit": PAGE_SIZE, "offset": 0}, MagicMock())

    def test_success_returns_data_list(self) -> None:
        body = {"data": [{"id": "a"}], "metadata": {"offset": 0, "limit": 100}}
        session = self._session_returning(200, body)
        rows = _fetch_page_unwrapped(session, f"{PROD_URL}/v1/users", {"limit": PAGE_SIZE, "offset": 0}, MagicMock())
        assert rows == [{"id": "a"}]

    @parameterized.expand([("bare_list", [{"id": "a"}]), ("missing_data", {"metadata": {}})])
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(PhylloRetryableError):
            _fetch_page_unwrapped(session, f"{PROD_URL}/v1/users", {"limit": PAGE_SIZE, "offset": 0}, MagicMock())


class TestCheckAccess:
    def _session(self, response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Phyllo returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with patch.object(phyllo, "make_tracked_session", return_value=self._session(response)):
            assert check_access("cid", "cs", "production") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        session = self._session(requests.ConnectionError("boom"))
        with patch.object(phyllo, "make_tracked_session", return_value=session):
            status, message = check_access("cid", "cs", "production")
        assert status == 0
        assert message is not None and "boom" in message

    def test_sandbox_environment_probes_sandbox_host(self) -> None:
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        session = self._session(response)
        with patch.object(phyllo, "make_tracked_session", return_value=session):
            check_access("cid", "cs", "sandbox")
        assert session.get.call_args.args[0].startswith("https://api.sandbox.getphyllo.com")

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Phyllo client ID or secret for the selected environment"),
            ("forbidden", 403, False, "Invalid Phyllo client ID or secret for the selected environment"),
            ("server_error", 500, False, "Phyllo returned HTTP 500"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with patch.object(phyllo, "make_tracked_session", return_value=self._session(response)):
            assert validate_credentials("cid", "cs", "production") == (expected_valid, expected_message)


class TestPhylloSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = phyllo_source(
            client_id="cid",
            client_secret="cs",
            environment="production",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Phyllo doesn't guarantee ordering or a stable creation timestamp on every object, so we
        # don't partition.
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
