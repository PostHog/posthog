from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway import scaleway
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.scaleway import (
    ScalewayResumeConfig,
    _base_params,
    _resolve_path,
    get_rows,
    probe_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scaleway.settings import (
    INSTANCE_ZONES,
    PAGE_SIZE,
    SCALEWAY_ENDPOINTS,
)


def _response(body: dict, status: int = 200, ok: bool = True) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.ok = ok
    resp.text = ""
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


def _manager(resume: ScalewayResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _drive(endpoint: str, responses: list[MagicMock], manager: MagicMock) -> tuple[list[list[dict]], MagicMock]:
    """Run get_rows for `endpoint` against a session that returns `responses` in order."""
    session = MagicMock()
    session.get.side_effect = responses
    with patch.object(scaleway, "make_tracked_session", return_value=session):
        pages = list(
            get_rows(
                secret_key="scw-secret",
                organization_id="org-123",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
            )
        )
    return pages, session


class TestBaseParams:
    @parameterized.expand(
        [
            # (endpoint, expected page-size param, expected org param name)
            ("users", "page_size", "organization_id"),
            ("projects", "page_size", "organization_id"),
            ("invoices", "page_size", "organization_id"),
            ("instance_servers", "per_page", "organization"),
            ("audit_trail_events", "page_size", "organization_id"),
        ]
    )
    def test_pagination_and_org_param_wiring(self, endpoint: str, page_param: str, org_param: str) -> None:
        # Guards the three-dialect wiring: Instance must use per_page + `organization`, everything else
        # page_size + `organization_id`. A swap here silently breaks pagination or org scoping.
        params = _base_params(SCALEWAY_ENDPOINTS[endpoint], "org-123")
        assert params[page_param] == PAGE_SIZE
        assert params[org_param] == "org-123"

    @parameterized.expand(
        [
            ("users", "order_by", "created_at_asc"),
            ("invoices", "order_by", "start_date_asc"),
            ("instance_servers", "order", "creation_date_asc"),
            ("audit_trail_events", "order_by", "recorded_at_asc"),
        ]
    )
    def test_sort_param_wiring(self, endpoint: str, order_param: str, order_value: str) -> None:
        params = _base_params(SCALEWAY_ENDPOINTS[endpoint], "org-123")
        assert params[order_param] == order_value

    def test_audit_trail_sets_recorded_after_lower_bound(self) -> None:
        # Audit Trail defaults to a 1h window, so a full pull must send an explicit recorded_after.
        params = _base_params(SCALEWAY_ENDPOINTS["audit_trail_events"], "org-123")
        assert "recorded_after" in params
        assert params["recorded_after"].endswith("Z")

    def test_non_audit_endpoint_has_no_time_filter(self) -> None:
        assert "recorded_after" not in _base_params(SCALEWAY_ENDPOINTS["users"], "org-123")


class TestResolvePath:
    @parameterized.expand(
        [
            ("users", "fr-par", "/iam/v1alpha1/users"),
            ("instance_servers", "nl-ams-1", "/instance/v1/zones/nl-ams-1/servers"),
            ("audit_trail_events", "fr-par", "/audit-trail/v1alpha1/regions/fr-par/events"),
        ]
    )
    def test_scope_substitution(self, endpoint: str, scope: str, expected: str) -> None:
        assert _resolve_path(SCALEWAY_ENDPOINTS[endpoint], scope) == expected


class TestPageNumberPagination:
    def test_terminates_on_short_page_and_saves_resume_after_full_page(self) -> None:
        full = _response({"users": [{"id": str(i)} for i in range(PAGE_SIZE)]})
        short = _response({"users": [{"id": "x"}]})
        manager = _manager()

        pages, session = _drive("users", [full, short], manager)

        assert [len(p) for p in pages] == [PAGE_SIZE, 1]
        # Two page requests, second asks for page 2.
        assert session.get.call_count == 2
        assert session.get.call_args_list[1].kwargs["params"]["page"] == 2
        # Resume state persisted only while more pages remained — pointing at the next page.
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert ScalewayResumeConfig(scope_index=0, page=2) in saved

    def test_resumes_from_saved_page(self) -> None:
        short = _response({"users": [{"id": "x"}]})
        manager = _manager(ScalewayResumeConfig(scope_index=0, page=7))

        _pages, session = _drive("users", [short], manager)

        assert session.get.call_args_list[0].kwargs["params"]["page"] == 7


class TestTokenPagination:
    def test_chains_tokens_and_drops_window_filter_on_subsequent_requests(self) -> None:
        page1 = _response({"events": [{"id": "a"}], "next_page_token": "tok2"})
        page2 = _response({"events": [{"id": "b"}], "next_page_token": None})
        # audit_trail_events fans out over two regions; give each region a single terminal page after
        # the first region's two-page chain.
        region2 = _response({"events": [], "next_page_token": None})
        manager = _manager()

        pages, session = _drive("audit_trail_events", [page1, page2, region2], manager)

        assert [row["id"] for page in pages for row in page] == ["a", "b"]
        # First request carries the recorded_after window; the token follow-up must not (the token
        # already encodes it server-side).
        first_params = session.get.call_args_list[0].kwargs["params"]
        second_params = session.get.call_args_list[1].kwargs["params"]
        assert "recorded_after" in first_params
        assert second_params == {"page_size": PAGE_SIZE, "page_token": "tok2"}

    def test_resumes_from_saved_token(self) -> None:
        terminal = _response({"events": [], "next_page_token": None})
        manager = _manager(ScalewayResumeConfig(scope_index=1, page_token="saved-tok"))

        _pages, session = _drive("audit_trail_events", [terminal], manager)

        # scope_index=1 skips the already-finished first region; the saved token drives the request.
        assert session.get.call_args_list[0].kwargs["params"]["page_token"] == "saved-tok"


class TestFanOut:
    def test_iterates_every_zone_and_advances_scope_between_them(self) -> None:
        # Each zone returns one short page, so the connector visits every zone once.
        responses = [_response({"servers": [{"id": f"srv-{z}"}]}) for z in INSTANCE_ZONES]
        manager = _manager()

        pages, session = _drive("instance_servers", responses, manager)

        assert session.get.call_count == len(INSTANCE_ZONES)
        requested_urls = [c.args[0] for c in session.get.call_args_list]
        for zone in INSTANCE_ZONES:
            assert any(f"/zones/{zone}/servers" in url for url in requested_urls)
        # Between scopes the bookmark advances so a crash resumes at the next zone, not the first.
        saved_scope_indices = [c.args[0].scope_index for c in manager.save_state.call_args_list]
        assert saved_scope_indices == list(range(1, len(INSTANCE_ZONES)))
        assert sum(len(p) for p in pages) == len(INSTANCE_ZONES)


class TestFetchErrors:
    def test_non_ok_response_raises(self) -> None:
        err = _response({}, status=403, ok=False)
        err.raise_for_status.side_effect = requests.HTTPError("403 Client Error: Forbidden", response=err)
        manager = _manager()

        with pytest.raises(requests.HTTPError):
            _drive("users", [err], manager)


class TestProbeEndpoint:
    @parameterized.expand([("ok", 200, 200), ("unauthorized", 401, 401), ("forbidden", 403, 403)])
    def test_returns_status_code(self, _name: str, status: int, expected: int) -> None:
        session = MagicMock()
        session.get.return_value = _response({}, status=status, ok=status < 400)
        with patch.object(scaleway, "make_tracked_session", return_value=session):
            assert probe_endpoint("scw-secret", "org-123", "users") == expected

    def test_network_error_returns_zero(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(scaleway, "make_tracked_session", return_value=session):
            assert probe_endpoint("scw-secret", "org-123", "users") == 0

    @parameterized.expand([("page_size_endpoint", "users"), ("token_endpoint", "audit_trail_events")])
    def test_requests_a_single_row(self, _name: str, endpoint: str) -> None:
        session = MagicMock()
        session.get.return_value = _response({}, status=200)
        with patch.object(scaleway, "make_tracked_session", return_value=session):
            probe_endpoint("scw-secret", "org-123", endpoint)
        params: dict[str, Any] = session.get.call_args.kwargs["params"]
        size_key = "per_page" if SCALEWAY_ENDPOINTS[endpoint].pagination == "per_page" else "page_size"
        assert params[size_key] == 1
