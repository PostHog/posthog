from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.netlify import netlify
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.netlify import (
    NetlifyResumeConfig,
    _build_url,
    _make_parent_field_injector,
    _parse_next_url,
    get_rows,
    netlify_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.settings import NETLIFY_ENDPOINTS

BASE = "https://api.netlify.com/api/v1"


def _resp(data: Any, next_url: str | None = None, status: int = 200) -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status
    response.ok = status < 400
    response.text = ""
    response.json.return_value = data
    response.headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return response


def _manager(resume: NetlifyResumeConfig | None = None) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestParseNextUrl:
    @parameterized.expand(
        [
            ("no_header", "", None),
            (
                "next_only",
                f'<{BASE}/sites?page=2&per_page=100>; rel="next"',
                f"{BASE}/sites?page=2&per_page=100",
            ),
            (
                "next_and_last",
                f'<{BASE}/sites?page=2>; rel="next", <{BASE}/sites?page=9>; rel="last"',
                f"{BASE}/sites?page=2",
            ),
            (
                "prev_and_last_no_next",
                f'<{BASE}/sites?page=1>; rel="prev", <{BASE}/sites?page=9>; rel="last"',
                None,
            ),
        ]
    )
    def test_parse_next_url(self, _name: str, header: str, expected: str | None) -> None:
        assert _parse_next_url(header) == expected


class TestBuildUrl:
    def test_with_page_size(self) -> None:
        assert _build_url("/sites", 100) == f"{BASE}/sites?per_page=100"

    def test_without_page_size(self) -> None:
        assert _build_url("/accounts", None) == f"{BASE}/accounts"


class TestParentFieldInjector:
    def test_injects_mapped_parent_fields(self) -> None:
        inject = _make_parent_field_injector({"id": "site-1", "slug": "acme"}, {"id": "site_id"})
        assert inject({"id": "build-1"}) == {"id": "build-1", "site_id": "site-1"}

    def test_missing_parent_field_raises(self) -> None:
        # The injected column feeds the child's composite primary key, so a parent missing it must
        # fail loudly rather than silently write a None into the key.
        with pytest.raises(KeyError):
            _make_parent_field_injector({"slug": "acme"}, {"id": "site_id"})


class TestGetRowsTopLevel:
    def test_paginates_and_checkpoints_after_each_page(self) -> None:
        manager = _manager()
        session = mock.Mock()
        session.get.side_effect = [
            _resp([{"id": "a"}], next_url=f"{BASE}/sites?page=2&per_page=100"),
            _resp([{"id": "b"}], next_url=None),
        ]
        with mock.patch.object(netlify, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "sites", mock.Mock(), manager))

        assert batches == [[{"id": "a"}], [{"id": "b"}]]
        # State saved once — after the first page, pointing at the second. The last page has no
        # next link, so nothing is saved for it.
        manager.save_state.assert_called_once_with(NetlifyResumeConfig(next_url=f"{BASE}/sites?page=2&per_page=100"))

    def test_resumes_from_saved_url(self) -> None:
        resume_url = f"{BASE}/sites?page=3&per_page=100"
        manager = _manager(NetlifyResumeConfig(next_url=resume_url))
        session = mock.Mock()
        session.get.side_effect = [_resp([{"id": "c"}], next_url=None)]
        with mock.patch.object(netlify, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "sites", mock.Mock(), manager))

        assert batches == [[{"id": "c"}]]
        assert session.get.call_args_list[0].args[0] == resume_url

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = _manager()
        session = mock.Mock()
        session.get.side_effect = [_resp([])]
        with mock.patch.object(netlify, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "sites", mock.Mock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestGetRowsFanOut:
    def test_injects_parent_site_id_and_checkpoints_parent_page(self) -> None:
        manager = _manager()
        session = mock.Mock()

        def get(url: str, **_kwargs: Any) -> mock.Mock:
            if url == f"{BASE}/sites?per_page=100":
                return _resp([{"id": "s1"}], next_url=None)
            if url == f"{BASE}/sites/s1/builds?per_page=100":
                return _resp([{"id": "b1"}], next_url=None)
            raise AssertionError(f"unexpected url: {url}")

        session.get.side_effect = get
        with mock.patch.object(netlify, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "builds", mock.Mock(), manager))

        # site_id is injected onto each build row (a build carries no site_id of its own).
        assert batches == [[{"id": "b1", "site_id": "s1"}]]
        manager.save_state.assert_called_once_with(NetlifyResumeConfig(next_url=f"{BASE}/sites?per_page=100"))

    def test_members_fan_out_reads_parent_slug(self) -> None:
        manager = _manager()
        session = mock.Mock()

        def get(url: str, **_kwargs: Any) -> mock.Mock:
            if url == f"{BASE}/accounts":
                return _resp([{"id": "acc-1", "slug": "acme"}], next_url=None)
            if url == f"{BASE}/acme/members":
                return _resp([{"id": "u1", "email": "a@b.co"}], next_url=None)
            raise AssertionError(f"unexpected url: {url}")

        session.get.side_effect = get
        with mock.patch.object(netlify, "make_tracked_session", return_value=session):
            batches = list(get_rows("tok", "members", mock.Mock(), manager))

        # Members fan out over accounts keyed by the account slug, injected as account_slug.
        assert batches == [[{"id": "u1", "email": "a@b.co", "account_slug": "acme"}]]


class TestIterPagesCap:
    def test_stops_and_warns_at_max_pages(self) -> None:
        session = mock.Mock()
        # Always advertise a next page so only max_pages bounds the walk.
        session.get.return_value = _resp([{"id": "x"}], next_url=f"{BASE}/sites/s1/builds?page=99")
        logger = mock.Mock()
        pages = list(
            netlify._iter_pages(
                session, f"{BASE}/sites/s1/builds", {}, logger, max_pages=2, page_cap_context={"site_id": "s1"}
            )
        )
        assert len(pages) == 2
        logger.warning.assert_called_once()


class TestFetchPage:
    def test_returns_ok_response(self) -> None:
        session = mock.Mock()
        session.get.return_value = _resp([{"id": "a"}])
        assert netlify._fetch_page(session, f"{BASE}/sites", {}, mock.Mock()).status_code == 200

    def test_raises_on_client_error(self) -> None:
        session = mock.Mock()
        response = _resp({"code": 401, "message": "Access Denied"}, status=401)
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error")
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            netlify._fetch_page(session, f"{BASE}/sites", {}, mock.Mock())


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        session = mock.Mock()
        response = mock.Mock(status_code=status)
        session.get.return_value = response
        with mock.patch.object(netlify, "make_tracked_session", return_value=session):
            assert validate_credentials("tok") is expected

    def test_exception_is_false(self) -> None:
        session = mock.Mock()
        session.get.side_effect = requests.ConnectionError()
        with mock.patch.object(netlify, "make_tracked_session", return_value=session):
            assert validate_credentials("tok") is False


class TestNetlifySourceResponse:
    @parameterized.expand(list(NETLIFY_ENDPOINTS.keys()))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = NETLIFY_ENDPOINTS[endpoint]
        response = netlify_source("tok", endpoint, mock.Mock(), _manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        # Partition config is present only for endpoints with a stable creation-time field.
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
