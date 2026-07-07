from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.lago import lago as lago_module
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.lago import (
    LagoHostNotAllowedError,
    LagoResumeConfig,
    get_rows,
    lago_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.settings import LAGO_ENDPOINTS


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (301, 302, 303, 307, 308)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = {}
    return response


def _page(rows: list[dict[str, Any]], next_page: Optional[int]) -> mock.MagicMock:
    return _response(json_data={"customers": rows, "meta": {"next_page": next_page}})


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://api.getlago.com/api/v1"),
            ("", "https://api.getlago.com/api/v1"),
            ("   ", "https://api.getlago.com/api/v1"),
            ("https://api.getlago.com", "https://api.getlago.com/api/v1"),
            ("https://api.getlago.com/", "https://api.getlago.com/api/v1"),
            ("https://api.getlago.com/api/v1", "https://api.getlago.com/api/v1"),
            ("billing.example.com", "https://billing.example.com/api/v1"),
            ("http://billing.example.com/", "http://billing.example.com/api/v1"),
            ("https://billing.example.com/api/v2", "https://billing.example.com/api/v1"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(lago_module, "make_tracked_session", return_value=session)

    def test_success(self):
        with self._patch_session(_response(status_code=200)):
            assert validate_credentials(None, "key") == (True, None)

    def test_invalid_key(self):
        with self._patch_session(_response(status_code=401)):
            valid, msg = validate_credentials(None, "key")
            assert valid is False
            assert msg == "Invalid Lago API key"

    def test_403_at_source_create_is_accepted(self):
        with self._patch_session(_response(status_code=403)):
            assert validate_credentials(None, "key", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with self._patch_session(_response(status_code=403)):
            valid, msg = validate_credentials(None, "key", schema_name="invoices")
            assert valid is False
            assert msg is not None

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials(None, "key")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials(None, "key")
            assert valid is False
            assert msg == lago_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(lago_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("http://10.0.0.1", "key", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_probe_hits_configured_host(self):
        with self._patch_session(_response(status_code=200)) as patched:
            validate_credentials("https://billing.example.com", "key")
            url = patched.return_value.get.call_args.args[0]
            assert url.startswith("https://billing.example.com/api/v1/customers")


class TestLagoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(LAGO_ENDPOINTS.keys()))
    def test_response_shape(self, endpoint):
        response = lago_source(
            api_url=None,
            api_key="key",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == ["lago_id"]
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"


class TestGetRows:
    def _run(self, manager, responses, team_id=1, api_url=None):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with mock.patch.object(lago_module, "make_tracked_session", return_value=session):
            rows: list[dict[str, Any]] = []
            for batch in get_rows(
                api_url=api_url,
                api_key="key",
                endpoint="customers",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=team_id,
            ):
                rows.extend(batch)
        return rows, session

    def test_paginates_via_meta_next_page(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _page([{"lago_id": "1"}, {"lago_id": "2"}], next_page=2)
        page2 = _page([{"lago_id": "3"}], next_page=None)
        rows, session = self._run(manager, [page1, page2])

        assert [r["lago_id"] for r in rows] == ["1", "2", "3"]
        # First request page=1, second request page=2 (from meta.next_page).
        first_qs = parse_qs(urlparse(session.get.call_args_list[0].args[0]).query)
        second_qs = parse_qs(urlparse(session.get.call_args_list[1].args[0]).query)
        assert first_qs["page"] == ["1"]
        assert second_qs["page"] == ["2"]

    def test_saves_next_page_after_yielding(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _page([{"lago_id": "1"}], next_page=2)
        page2 = _page([{"lago_id": "2"}], next_page=None)
        self._run(manager, [page1, page2])

        # State is saved once (after page 1, pointing at page 2); the last page has no next_page.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, LagoResumeConfig)
        assert saved.next_page == 2

    def test_resumes_from_saved_state(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = LagoResumeConfig(next_page=3)
        rows, session = self._run(manager, [_page([{"lago_id": "9"}], next_page=None)])

        first_qs = parse_qs(urlparse(session.get.call_args_list[0].args[0]).query)
        assert first_qs["page"] == ["3"]
        assert [r["lago_id"] for r in rows] == ["9"]

    def test_empty_page_terminates(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        rows, session = self._run(manager, [_page([], next_page=2)])
        assert rows == []
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_does_not_follow_redirects(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with pytest.raises(LagoHostNotAllowedError):
            self._run(manager, [_response(status_code=302)])

    def test_passes_allow_redirects_false(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        _rows, session = self._run(manager, [_page([{"lago_id": "1"}], next_page=None)])
        assert session.get.call_args.kwargs["allow_redirects"] is False

    def test_raises_when_host_not_allowed(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with mock.patch.object(lago_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(LagoHostNotAllowedError):
                self._run(manager, [_page([{"lago_id": "1"}], next_page=None)])

    @pytest.mark.parametrize("status_code", [429, 503])
    def test_retries_retryable_status_then_succeeds(self, status_code):
        # End-to-end: a retryable status raises LagoRetryableError, tenacity retries, and the
        # subsequent 200 yields rows. Guards against accidentally dropping the retry predicate.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        responses = [_response(status_code=status_code), _page([{"lago_id": "r1"}], next_page=None)]
        with mock.patch.object(lago_module, "_retry_wait", return_value=0):
            rows, session = self._run(manager, responses)
        assert [r["lago_id"] for r in rows] == ["r1"]
        assert session.get.call_count == 2


class TestRetryAfter:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "  9 "}, 9.0),
            ({"Retry-After": "100000"}, 60.0),
            ({"Retry-After": "Wed, 21 Oct 2025 07:28:00 GMT"}, None),
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, header, expected):
        from products.warehouse_sources.backend.temporal.data_imports.sources.lago.lago import _parse_retry_after

        response = mock.MagicMock()
        response.headers = header
        assert _parse_retry_after(response) == expected

    def test_retry_wait_prefers_retry_after(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.lago.lago import (
            LagoRetryableError,
            _retry_wait,
        )

        state = mock.MagicMock()
        state.outcome.exception.return_value = LagoRetryableError("rate limited", retry_after=7.0)
        assert _retry_wait(state) == 7.0
