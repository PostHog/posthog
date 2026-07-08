import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales import (
    FreshsalesResumeConfig,
    _build_page_url,
    _build_root,
    _normalize_alias,
    _resolve_view_id,
    check_credentials,
    freshsales_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.settings import FRESHSALES_ENDPOINTS


def _resp(status: int = 200, body: Optional[dict] = None) -> MagicMock:
    body = body or {}
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.json.return_value = body
    response.text = json.dumps(body)
    if response.ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = HTTPError(response=response)
    return response


def _session(responses: list[MagicMock]) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = responses
    return session


class _FakeResumeManager:
    """In-memory stand-in for ResumableSourceManager."""

    def __init__(self, state: Optional[FreshsalesResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[FreshsalesResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[FreshsalesResumeConfig]:
        return self.state

    def save_state(self, data: FreshsalesResumeConfig) -> None:
        self.saved.append(data)


class TestNormalizeAlias:
    @parameterized.expand(
        [
            ("plain_alias", "acme", "acme"),
            ("uppercase", "ACME", "acme"),
            ("full_host", "acme.myfreshworks.com", "acme"),
            ("with_scheme", "https://acme.myfreshworks.com", "acme"),
            ("with_path", "acme.myfreshworks.com/crm/sales", "acme"),
            ("hyphenated", "personal-1234", "personal-1234"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid(self, _name: str, value: str, expected: str) -> None:
        assert _normalize_alias(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("underscore", "acme_corp"),
            ("at_sign", "acme@evil.com"),
            ("leading_hyphen", "-acme"),
            ("space_inside", "acme corp"),
        ]
    )
    def test_invalid(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            _normalize_alias(value)

    def test_build_root_constrains_host(self) -> None:
        assert _build_root("acme") == "https://acme.myfreshworks.com/crm/sales/api"


class TestBuildPageUrl:
    def test_view_endpoint_includes_view_and_sort(self) -> None:
        url = _build_page_url(
            "https://acme.myfreshworks.com/crm/sales/api", FRESHSALES_ENDPOINTS["contacts"], view_id=42, page=3
        )
        assert "/contacts/view/42?" in url
        assert "page=3" in url
        assert "per_page=100" in url
        assert "sort=created_at" in url
        assert "sort_type=asc" in url

    def test_direct_endpoint_includes_static_params(self) -> None:
        url = _build_page_url(
            "https://acme.myfreshworks.com/crm/sales/api", FRESHSALES_ENDPOINTS["open_tasks"], view_id=None, page=1
        )
        assert "/tasks?" in url
        assert "filter=open" in url
        assert "sort=" not in url


class TestResolveViewId:
    def test_prefers_all_view(self) -> None:
        session = _session(
            [_resp(body={"filters": [{"id": 1, "name": "My contacts"}, {"id": 2, "name": "All Contacts"}]})]
        )
        assert _resolve_view_id(session, "https://acme.myfreshworks.com/crm/sales/api", "contacts", MagicMock()) == 2

    def test_falls_back_to_first_view(self) -> None:
        session = _session([_resp(body={"filters": [{"id": 7, "name": "Recently created"}]})])
        assert _resolve_view_id(session, "https://acme.myfreshworks.com/crm/sales/api", "contacts", MagicMock()) == 7

    def test_returns_none_on_404(self) -> None:
        session = _session([_resp(status=404)])
        assert _resolve_view_id(session, "https://acme.myfreshworks.com/crm/sales/api", "leads", MagicMock()) is None


class TestGetRows:
    def _run(self, endpoint: str, responses: list[MagicMock], manager: _FakeResumeManager) -> list[list[dict]]:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales.make_tracked_session",
            return_value=_session(responses),
        ):
            return list(get_rows("acme", "acme", endpoint, MagicMock(), manager))  # type: ignore[arg-type]

    def test_paginates_until_total_pages(self) -> None:
        page1 = _resp(body={"sales_activities": [{"id": i} for i in range(100)], "meta": {"total_pages": 2}})
        page2 = _resp(body={"sales_activities": [{"id": 100}], "meta": {"total_pages": 2}})
        manager = _FakeResumeManager()

        batches = self._run("sales_activities", [page1, page2], manager)

        assert len(batches) == 2
        assert batches[0][0] == {"id": 0}
        assert batches[1] == [{"id": 100}]
        # State saved after the first page only (pointing at the next page to fetch).
        assert [s.next_page for s in manager.saved] == [2]

    def test_stops_on_short_page_when_total_pages_missing(self) -> None:
        # /appointments omits total_pages, so a page shorter than per_page ends pagination.
        page1 = _resp(body={"appointments": [{"id": i} for i in range(10)]})
        manager = _FakeResumeManager()

        batches = self._run("upcoming_appointments", [page1], manager)

        assert len(batches) == 1
        assert manager.saved == []

    def test_stops_on_empty_page(self) -> None:
        manager = _FakeResumeManager()
        batches = self._run("sales_activities", [_resp(body={"sales_activities": []})], manager)
        assert batches == []

    def test_resumes_from_saved_state(self) -> None:
        # Resume at page 2 — the view id is already known so /filters is never fetched again.
        page2 = _resp(body={"contacts": [{"id": 5}]})
        manager = _FakeResumeManager(FreshsalesResumeConfig(next_page=2, view_id=99))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales.make_tracked_session"
        ) as mocked:
            session = _session([page2])
            mocked.return_value = session
            batches = list(get_rows("acme", "acme", "contacts", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": 5}]]
        called_url = session.get.call_args_list[0].args[0]
        assert "/contacts/view/99?" in called_url
        assert "page=2" in called_url

    def test_view_endpoint_resolves_view_first(self) -> None:
        filters = _resp(body={"filters": [{"id": 3, "name": "All Contacts"}]})
        page1 = _resp(body={"contacts": [{"id": 1}]})
        manager = _FakeResumeManager()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales.make_tracked_session"
        ) as mocked:
            session = _session([filters, page1])
            mocked.return_value = session
            batches = list(get_rows("acme", "acme", "contacts", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": 1}]]
        assert "/contacts/filters" in session.get.call_args_list[0].args[0]
        assert "/contacts/view/3?" in session.get.call_args_list[1].args[0]

    def test_tolerates_missing_object(self) -> None:
        # leads object absent -> /filters 404 -> stream yields nothing instead of failing.
        manager = _FakeResumeManager()
        batches = self._run("leads", [_resp(status=404)], manager)
        assert batches == []


class TestCheckCredentials:
    def _run(self, response: MagicMock, schema_name: Optional[str] = None, domain: str = "acme") -> Any:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales.make_tracked_session",
            return_value=_session([response]),
        ):
            return check_credentials("key", domain, schema_name)

    @parameterized.expand(
        [
            ("ok", 200, True, 200),
            ("unauthorized", 401, False, 401),
            ("forbidden", 403, False, 403),
            ("not_found", 404, False, 404),
            ("server_error", 500, False, 500),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, expected_status: Optional[int]) -> None:
        ok, error, status_code = self._run(_resp(status=status))
        assert ok is expected_ok
        assert status_code == expected_status
        if not expected_ok:
            assert error

    def test_invalid_domain_short_circuits(self) -> None:
        ok, error, status_code = check_credentials("key", "bad domain", None)
        assert ok is False
        assert status_code is None
        assert error is not None and "domain" in error.lower()

    def test_source_create_probes_account_endpoint(self) -> None:
        session = _session([_resp(status=200, body={})])
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales.make_tracked_session",
            return_value=session,
        ):
            check_credentials("key", "acme", None)
        assert session.get.call_args.args[0].endswith("/selector/owners")

    def test_schema_probe_targets_endpoint(self) -> None:
        session = _session([_resp(status=200, body={})])
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales.make_tracked_session",
            return_value=session,
        ):
            check_credentials("key", "acme", "contacts")
        # contacts requires a view, so it probes the filters endpoint.
        assert "/contacts/filters" in session.get.call_args.args[0]


class TestFreshsalesSource:
    @parameterized.expand(
        [
            ("contacts", ["id"], "created_at"),
            ("deals", ["id"], "created_at"),
            ("sales_activities", ["id"], None),
            ("open_tasks", ["id"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: Optional[str]) -> None:
        response = freshsales_source("key", "acme", endpoint, MagicMock(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
