import json
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales import (
    FreshsalesResumeConfig,
    _normalize_alias,
    _resolve_view_id,
    check_credentials,
    freshsales_source,
    get_rows,
)


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


class TestResolveViewId:
    def test_falls_back_to_first_view(self) -> None:
        session = _session([_resp(body={"filters": [{"id": 7, "name": "Recently created"}]})])
        assert _resolve_view_id(session, "https://acme.myfreshworks.com/crm/sales/api", "contacts", MagicMock()) == 7


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

    def test_selector_falls_back_to_the_only_list_in_the_envelope(self) -> None:
        # Freshsales doesn't publish selector response bodies; an unexpected envelope key must not
        # silently sync an empty table.
        manager = _FakeResumeManager()
        batches = self._run("owners", [_resp(body={"portal_users": [{"id": 1, "name": "Ann"}]})], manager)
        assert batches == [[{"id": 1, "name": "Ann"}]]

    def test_deal_stages_walks_every_pipeline(self) -> None:
        # /selector/deal_stages covers the default pipeline only, so a single request would miss the
        # stages that deals in every other pipeline point at.
        pipelines = _resp(body={"deal_pipelines": [{"id": 1, "name": "Sales"}, {"id": 2, "name": "Renewals"}]})
        stages_1 = _resp(body={"deal_stages": [{"id": 10, "name": "New", "deal_pipeline_id": 1}]})
        stages_2 = _resp(body={"deal_stages": [{"id": 20, "name": "Due", "deal_pipeline_id": 2}]})
        manager = _FakeResumeManager()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales.make_tracked_session"
        ) as mocked:
            session = _session([pipelines, stages_1, stages_2])
            mocked.return_value = session
            batches = list(get_rows("acme", "acme", "deal_stages", MagicMock(), manager))  # type: ignore[arg-type]

        assert [row["id"] for batch in batches for row in batch] == [10, 20]
        assert [call.args[0].rsplit("/api/", 1)[1] for call in session.get.call_args_list] == [
            "selector/deal_pipelines",
            "selector/deal_pipelines/1/deal_stages",
            "selector/deal_pipelines/2/deal_stages",
        ]

    def test_list_contacts_pages_every_list_and_tags_rows_with_list_id(self) -> None:
        # /lists and /contacts/lists/{id} are paginated, unlike selectors, and the contact rows don't
        # say which list they came from.
        lists_page = _resp(body={"lists": [{"id": 1}, {"id": 2}], "meta": {"total_pages": 1}})
        list_1_page_1 = _resp(body={"contacts": [{"id": i} for i in range(100)], "meta": {"total_pages": 2}})
        list_1_page_2 = _resp(body={"contacts": [{"id": 100}], "meta": {"total_pages": 2}})
        list_2_page_1 = _resp(body={"contacts": [{"id": 0}], "meta": {"total_pages": 1}})
        manager = _FakeResumeManager()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales.make_tracked_session"
        ) as mocked:
            session = _session([lists_page, list_1_page_1, list_1_page_2, list_2_page_1])
            mocked.return_value = session
            batches = list(get_rows("acme", "acme", "list_contacts", MagicMock(), manager))  # type: ignore[arg-type]

        rows = [row for batch in batches for row in batch]
        assert len(rows) == 102
        assert rows[100] == {"id": 100, "list_id": 1}
        assert rows[101] == {"id": 0, "list_id": 2}
        assert [call.args[0].rsplit("/api/", 1)[1] for call in session.get.call_args_list] == [
            "lists?page=1&per_page=100",
            "contacts/lists/1?page=1&per_page=100",
            "contacts/lists/1?page=2&per_page=100",
            "contacts/lists/2?page=1&per_page=100",
        ]
        assert manager.saved == [FreshsalesResumeConfig(next_page=2, parent_id=1)]

    @parameterized.expand(
        [
            ("saved_list_still_exists", 2, ["contacts/lists/2?page=3&per_page=100"]),
            (
                "saved_list_deleted",
                9,
                ["contacts/lists/1?page=1&per_page=100", "contacts/lists/2?page=1&per_page=100"],
            ),
        ]
    )
    def test_list_contacts_resumes_at_saved_list_and_page(
        self, _name: str, saved_list_id: int, expected_child_calls: list[str]
    ) -> None:
        lists_page = _resp(body={"lists": [{"id": 1}, {"id": 2}], "meta": {"total_pages": 1}})
        child_pages = [_resp(body={"contacts": [{"id": 5}]}) for _ in expected_child_calls]
        manager = _FakeResumeManager(FreshsalesResumeConfig(next_page=3, parent_id=saved_list_id))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales.make_tracked_session"
        ) as mocked:
            session = _session([lists_page, *child_pages])
            mocked.return_value = session
            list(get_rows("acme", "acme", "list_contacts", MagicMock(), manager))  # type: ignore[arg-type]

        assert [call.args[0].rsplit("/api/", 1)[1] for call in session.get.call_args_list[1:]] == expected_child_calls

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
            ("list_contacts", ["list_id", "id"], "created_at"),
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
