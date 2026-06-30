from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm import agilecrm
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.agilecrm import (
    AgileCRMResumeConfig,
    base_url,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.settings import AGILECRM_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: AgileCRMResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[AgileCRMResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> AgileCRMResumeConfig | None:
        return self._state

    def save_state(self, data: AgileCRMResumeConfig) -> None:
        self.saved.append(data)


def _collect_rows(
    monkeypatch: Any,
    pages: list[list[dict[str, Any]]],
    manager: _FakeResumableManager,
    endpoint: str = "contacts",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drive get_rows against a queue of fake pages, returning (rows, recorded request params)."""
    recorded_params: list[dict[str, Any]] = []
    queue = list(pages)

    def fake_fetch(session: Any, url: str, params: dict[str, Any], logger: Any) -> list[dict[str, Any]]:
        recorded_params.append(dict(params))
        return queue.pop(0) if queue else []

    monkeypatch.setattr(agilecrm, "_fetch_page", fake_fetch)
    monkeypatch.setattr(agilecrm, "_make_session", lambda email, api_key: MagicMock())

    rows: list[dict[str, Any]] = []
    for table in get_rows(
        domain="acme",
        email="a@b.com",
        api_key="key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows, recorded_params


class TestBaseUrl:
    @parameterized.expand(
        [
            ("simple", "acme", "https://acme.agilecrm.com/dev/api"),
            ("with_hyphen", "my-company", "https://my-company.agilecrm.com/dev/api"),
            ("trims_whitespace", "  acme  ", "https://acme.agilecrm.com/dev/api"),
        ]
    )
    def test_valid_domains(self, _name: str, domain: str, expected: str) -> None:
        assert base_url(domain) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            # A `#`/`/`/`.` in the domain could break out of the agilecrm.com host and retarget the
            # basic-auth credentials at an attacker-controlled server, so these must be rejected.
            ("fragment_breakout", "evil.com#"),
            ("slash_breakout", "evil.com/"),
            ("dotted", "evil.com"),
            ("at_breakout", "user@evil.com"),
        ]
    )
    def test_invalid_domains_rejected(self, _name: str, domain: str) -> None:
        with pytest.raises(ValueError):
            base_url(domain)


class TestPagination:
    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        page_size = AGILECRM_ENDPOINTS["contacts"].page_size
        first_page = [{"id": i} for i in range(page_size - 1)] + [{"id": page_size, "cursor": "CURSOR1"}]
        second_page = [{"id": 9001}]  # short page -> terminal
        manager = _FakeResumableManager()

        rows, params = _collect_rows(monkeypatch, [first_page, second_page], manager)

        assert len(rows) == page_size + 1
        # First request has no cursor; the second carries the cursor from the last item of page one.
        assert "cursor" not in params[0]
        assert params[1]["cursor"] == "CURSOR1"
        # The cursor is navigation metadata and must never leak into the warehouse rows.
        assert all("cursor" not in row for row in rows)

    def test_stops_when_full_page_has_no_cursor(self, monkeypatch: Any) -> None:
        # A full page whose last item carries no cursor must terminate rather than loop forever.
        page_size = AGILECRM_ENDPOINTS["contacts"].page_size
        full_page_no_cursor = [{"id": i} for i in range(page_size)]
        manager = _FakeResumableManager()

        rows, params = _collect_rows(monkeypatch, [full_page_no_cursor, [{"id": 1}]], manager)

        assert len(rows) == page_size
        assert len(params) == 1

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, params = _collect_rows(monkeypatch, [[]], manager)
        assert rows == []
        assert len(params) == 1

    def test_resume_uses_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(AgileCRMResumeConfig(cursor="SAVED"))
        rows, params = _collect_rows(monkeypatch, [[{"id": 1}]], manager)

        assert rows == [{"id": 1}]
        assert params[0]["cursor"] == "SAVED"

    def test_saves_state_after_yielding_batch(self, monkeypatch: Any) -> None:
        # The Batcher flushes once 2000 rows accumulate; state must be saved (with the next cursor)
        # only after that batch is yielded, so a crash re-yields the last page rather than skipping it.
        big_first_page = [{"id": i} for i in range(2499)] + [{"id": 2500, "cursor": "NEXT"}]
        manager = _FakeResumableManager()

        rows, _ = _collect_rows(monkeypatch, [big_first_page, [{"id": 1}]], manager)

        assert manager.saved
        assert manager.saved[0].cursor == "NEXT"
        # The cursor is navigation metadata and must never leak into the warehouse rows.
        assert all("cursor" not in row for row in rows)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response

        with patch.object(agilecrm, "_make_session", lambda email, api_key: session):
            assert validate_credentials("acme", "a@b.com", "key") is expected

    def test_invalid_domain_short_circuits_to_false(self, monkeypatch: Any) -> None:
        # An invalid domain must fail before any request is attempted.
        session = MagicMock()
        monkeypatch.setattr(agilecrm, "_make_session", lambda email, api_key: session)

        assert validate_credentials("evil.com#", "a@b.com", "key") is False
        session.get.assert_not_called()

    def test_network_error_is_false(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(agilecrm, "_make_session", lambda email, api_key: session)

        assert validate_credentials("acme", "a@b.com", "key") is False
