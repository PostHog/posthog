from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja import (
    invoiceninja as invoiceninja_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.invoiceninja import (
    InvoiceNinjaHostNotAllowedError,
    InvoiceNinjaResumeConfig,
    get_rows,
    invoiceninja_source,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.settings import (
    INVOICENINJA_ENDPOINTS,
)


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


def _page(rows: list[dict[str, Any]], *, current_page: int, total_pages: int) -> mock.MagicMock:
    return _response(
        json_data={"data": rows, "meta": {"pagination": {"current_page": current_page, "total_pages": total_pages}}}
    )


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://invoicing.co/api/v1"),
            ("", "https://invoicing.co/api/v1"),
            ("   ", "https://invoicing.co/api/v1"),
            ("https://invoicing.co", "https://invoicing.co/api/v1"),
            ("https://invoicing.co/", "https://invoicing.co/api/v1"),
            ("https://invoicing.co/api/v1", "https://invoicing.co/api/v1"),
            ("invoices.example.com", "https://invoices.example.com/api/v1"),
            ("http://invoices.example.com/", "http://invoices.example.com/api/v1"),
            ("https://invoices.example.com/api/v5", "https://invoices.example.com/api/v1"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestHostOf:
    @pytest.mark.parametrize(
        "url, expected_host",
        [
            ("https://invoices.example.com/api/v1", "invoices.example.com"),
            # Backslash (and its %5c encoding) is userinfo to urlparse but a path separator to
            # requests/urllib3 — the host must reflect the address the request actually reaches, or
            # the SSRF check validates a decoy host while the token goes elsewhere.
            ("https://127.0.0.1\\@example.com/api/v1", "127.0.0.1"),
            ("https://127.0.0.1%5c@example.com/api/v1", "127.0.0.1"),
            ("https://127.0.0.1%5C@example.com/api/v1", "127.0.0.1"),
        ],
    )
    def test_host_reflects_real_connect_target(self, url, expected_host):
        assert invoiceninja_module._host_of(url) == expected_host


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(invoiceninja_module, "make_tracked_session", return_value=session)

    def test_success(self):
        with self._patch_session(_response(status_code=200)):
            assert validate_credentials(None, "tok") == (True, None)

    def test_invalid_token_401(self):
        with self._patch_session(_response(status_code=401)):
            valid, msg = validate_credentials(None, "tok")
            assert valid is False
            assert msg == "Invalid Invoice Ninja API token"

    def test_invalid_token_403_message_always_fails(self):
        # A bad Invoice Ninja token returns 403 {"message": "Invalid token"} — reject it even at create.
        response = _response(status_code=403, json_data={"message": "Invalid token"})
        with self._patch_session(response):
            valid, msg = validate_credentials(None, "tok", schema_name=None)
            assert valid is False
            assert msg == "Invalid Invoice Ninja API token"

    def test_permission_403_at_source_create_is_accepted(self):
        # A 403 without the "Invalid token" message is a restricted (enterprise) token, not a bad one.
        response = _response(status_code=403, json_data={"message": "This action is unauthorized."})
        with self._patch_session(response):
            assert validate_credentials(None, "tok", schema_name=None) == (True, None)

    def test_permission_403_for_scoped_probe_fails(self):
        response = _response(status_code=403, json_data={"message": "This action is unauthorized."})
        with self._patch_session(response):
            valid, msg = validate_credentials(None, "tok", schema_name="invoices")
            assert valid is False
            assert msg is not None

    def test_request_exception_returns_failure(self):
        import requests

        with self._patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials(None, "tok")
            assert valid is False
            assert "boom" in (msg or "")

    def test_rejects_redirect_response(self):
        with self._patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials(None, "tok")
            assert valid is False
            assert msg == invoiceninja_module.HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(invoiceninja_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("http://10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_probe_hits_configured_host_with_required_headers(self):
        with self._patch_session(_response(status_code=200)) as patched:
            validate_credentials("https://invoices.example.com", "tok")
            call = patched.return_value.get.call_args
            assert call.args[0].startswith("https://invoices.example.com/api/v1/clients")
            headers = call.kwargs["headers"]
            assert headers["X-API-TOKEN"] == "tok"
            assert headers["X-Requested-With"] == "XMLHttpRequest"

    def test_redacts_token_in_telemetry(self):
        # The token rides in X-API-TOKEN, which the transport's name-based scrubber doesn't cover, so
        # it must be passed as a redact value to keep it out of captured HTTP samples.
        with self._patch_session(_response(status_code=200)) as patched:
            validate_credentials(None, "tok")
            assert patched.call_args.kwargs["redact_values"] == ("tok",)

    def test_rejects_plaintext_http_before_sending_token(self):
        # A plaintext http:// URL would expose the X-API-TOKEN on the wire, so reject it without
        # ever issuing the token-bearing request.
        with self._patch_session(_response(status_code=200)) as patched:
            valid, msg = validate_credentials("http://invoices.example.com", "tok")
            assert valid is False
            assert msg == invoiceninja_module.HTTP_NOT_ALLOWED_ERROR
            patched.return_value.get.assert_not_called()


class TestInvoiceNinjaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(INVOICENINJA_ENDPOINTS.keys()))
    def test_response_shape(self, endpoint):
        response = invoiceninja_source(
            base_url=None,
            api_token="tok",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        # Integer unix timestamps aren't datetime-partitionable, so no partitioning is applied.
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestGetRows:
    def _run(self, manager, responses, team_id=1, base_url=None):
        session = mock.MagicMock()
        session.get.side_effect = responses
        with mock.patch.object(invoiceninja_module, "make_tracked_session", return_value=session):
            rows: list[dict[str, Any]] = []
            for batch in get_rows(
                base_url=base_url,
                api_token="tok",
                endpoint="clients",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=team_id,
            ):
                rows.extend(batch)
        return rows, session

    def test_paginates_via_meta_pagination(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _page([{"id": "1"}, {"id": "2"}], current_page=1, total_pages=2)
        page2 = _page([{"id": "3"}], current_page=2, total_pages=2)
        rows, session = self._run(manager, [page1, page2])

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        first_qs = parse_qs(urlparse(session.get.call_args_list[0].args[0]).query)
        second_qs = parse_qs(urlparse(session.get.call_args_list[1].args[0]).query)
        assert first_qs["page"] == ["1"]
        assert second_qs["page"] == ["2"]

    def test_saves_next_page_after_yielding(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _page([{"id": "1"}], current_page=1, total_pages=2)
        page2 = _page([{"id": "2"}], current_page=2, total_pages=2)
        self._run(manager, [page1, page2])

        # State is saved once (after page 1, pointing at page 2); the last page is terminal.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, InvoiceNinjaResumeConfig)
        assert saved.next_page == 2

    def test_resumes_from_saved_state(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = InvoiceNinjaResumeConfig(next_page=3)
        rows, session = self._run(manager, [_page([{"id": "9"}], current_page=3, total_pages=3)])

        first_qs = parse_qs(urlparse(session.get.call_args_list[0].args[0]).query)
        assert first_qs["page"] == ["3"]
        assert [r["id"] for r in rows] == ["9"]

    def test_paginates_via_links_next_when_page_counts_absent(self):
        # Some deployments only expose `links.next` without current/total page counts.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        page1 = _response(
            json_data={"data": [{"id": "1"}], "meta": {"pagination": {"links": {"next": "https://next"}}}}
        )
        page2 = _response(json_data={"data": [{"id": "2"}], "meta": {"pagination": {"links": {"next": None}}}})
        rows, session = self._run(manager, [page1, page2])
        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.get.call_count == 2
        second_qs = parse_qs(urlparse(session.get.call_args_list[1].args[0]).query)
        assert second_qs["page"] == ["2"]

    def test_empty_page_terminates(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        rows, session = self._run(manager, [_page([], current_page=1, total_pages=5)])
        assert rows == []
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_missing_pagination_terminates_after_first_page(self):
        # A response with no pagination block must not loop forever.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        rows, session = self._run(manager, [_response(json_data={"data": [{"id": "1"}]})])
        assert [r["id"] for r in rows] == ["1"]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_does_not_follow_redirects(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with pytest.raises(InvoiceNinjaHostNotAllowedError):
            self._run(manager, [_response(status_code=302)])

    def test_passes_allow_redirects_false(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        _rows, session = self._run(manager, [_page([{"id": "1"}], current_page=1, total_pages=1)])
        assert session.get.call_args.kwargs["allow_redirects"] is False

    def test_sends_required_headers(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        _rows, session = self._run(manager, [_page([{"id": "1"}], current_page=1, total_pages=1)])
        headers = session.get.call_args.kwargs["headers"]
        assert headers["X-API-TOKEN"] == "tok"
        assert headers["X-Requested-With"] == "XMLHttpRequest"

    def test_redacts_token_in_telemetry(self):
        # The token rides in X-API-TOKEN, which the transport's name-based scrubber doesn't cover, so
        # it must be passed as a redact value to keep it out of captured HTTP samples.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": "1"}], current_page=1, total_pages=1)]
        with mock.patch.object(invoiceninja_module, "make_tracked_session", return_value=session) as mts:
            list(
                get_rows(
                    base_url=None,
                    api_token="tok",
                    endpoint="clients",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                )
            )
        assert mts.call_args.kwargs["redact_values"] == ("tok",)

    def test_raises_when_host_not_allowed(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with mock.patch.object(invoiceninja_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(InvoiceNinjaHostNotAllowedError):
                self._run(manager, [_page([{"id": "1"}], current_page=1, total_pages=1)])

    def test_raises_on_plaintext_http(self):
        # A plaintext http:// URL must fail before the token-bearing request goes out.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        with pytest.raises(InvoiceNinjaHostNotAllowedError):
            self._run(
                manager, [_page([{"id": "1"}], current_page=1, total_pages=1)], base_url="http://invoices.example.com"
            )

    @pytest.mark.parametrize("status_code", [429, 503])
    def test_retries_retryable_status_then_succeeds(self, status_code):
        # End-to-end: a retryable status raises, tenacity retries, and the subsequent 200 yields rows.
        manager = mock.MagicMock()
        manager.can_resume.return_value = False
        responses = [_response(status_code=status_code), _page([{"id": "r1"}], current_page=1, total_pages=1)]
        with mock.patch.object(invoiceninja_module, "_retry_wait", return_value=0):
            rows, session = self._run(manager, responses)
        assert [r["id"] for r in rows] == ["r1"]
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.invoiceninja import (
            _parse_retry_after,
        )

        response = mock.MagicMock()
        response.headers = header
        assert _parse_retry_after(response) == expected

    def test_retry_wait_prefers_retry_after(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.invoiceninja import (
            InvoiceNinjaRetryableError,
            _retry_wait,
        )

        state = mock.MagicMock()
        state.outcome.exception.return_value = InvoiceNinjaRetryableError("rate limited", retry_after=7.0)
        assert _retry_wait(state) == 7.0
