import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign import (
    PAGE_SIZE,
    ActiveCampaignPaginator,
    ActiveCampaignResumeConfig,
    _normalize_base_url,
    active_campaign_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.settings import (
    ACTIVE_CAMPAIGN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


def _full_page() -> list[dict[str, Any]]:
    return [{"id": str(i)} for i in range(PAGE_SIZE)]


def _meta_response(total: Any) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"meta": {"total": total}}
    return response


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://acme.api-us1.com", "https://acme.api-us1.com"),
            ("https://acme.api-us1.com/", "https://acme.api-us1.com"),
            ("https://acme.api-us1.com/api/3", "https://acme.api-us1.com"),
            ("https://acme.api-us1.com/api/3/", "https://acme.api-us1.com"),
            ("  https://acme.api-us1.com  ", "https://acme.api-us1.com"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert _normalize_base_url(raw) == expected


class TestActiveCampaignPaginator:
    def test_initial_state(self) -> None:
        paginator = ActiveCampaignPaginator()
        assert paginator.offset == 0
        assert paginator.limit == PAGE_SIZE
        assert paginator.has_next_page is True

    def test_init_request_emits_offset_and_limit(self) -> None:
        paginator = ActiveCampaignPaginator()
        request = Request(method="GET", url="https://acme.api-us1.com/api/3/contacts")
        paginator.init_request(request)
        assert request.params["offset"] == 0
        assert request.params["limit"] == PAGE_SIZE

    def test_advances_offset_on_full_page(self) -> None:
        paginator = ActiveCampaignPaginator()
        paginator.update_state(_meta_response(1000), _full_page())
        assert paginator.offset == PAGE_SIZE
        assert paginator.has_next_page is True

    def test_stops_on_short_page(self) -> None:
        paginator = ActiveCampaignPaginator()
        paginator.update_state(_meta_response(1000), [{"id": "1"}])
        assert paginator.has_next_page is False

    def test_stops_on_empty_page(self) -> None:
        paginator = ActiveCampaignPaginator()
        paginator.update_state(_meta_response(1000), [])
        assert paginator.has_next_page is False

    def test_stops_when_offset_reaches_int_total(self) -> None:
        paginator = ActiveCampaignPaginator()
        # A full page but meta.total says we've now covered everything.
        paginator.update_state(_meta_response(PAGE_SIZE), _full_page())
        assert paginator.has_next_page is False

    def test_string_total_falls_back_to_page_length(self) -> None:
        # ActiveCampaign sometimes returns meta.total as a string; the int-only
        # early-exit is skipped, so a full page must still advance.
        paginator = ActiveCampaignPaginator()
        paginator.update_state(_meta_response("1000"), _full_page())
        assert paginator.has_next_page is True
        assert paginator.offset == PAGE_SIZE

    def test_get_resume_state_when_next_page(self) -> None:
        paginator = ActiveCampaignPaginator()
        paginator.update_state(_meta_response(1000), _full_page())
        assert paginator.get_resume_state() == {"offset": PAGE_SIZE}

    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = ActiveCampaignPaginator()
        paginator.update_state(_meta_response(1000), [])
        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = ActiveCampaignPaginator()
        paginator.set_resume_state({"offset": 300})
        assert paginator.offset == 300
        assert paginator.has_next_page is True

        request = Request(method="GET", url="https://acme.api-us1.com/api/3/contacts")
        paginator.init_request(request)
        assert request.params["offset"] == 300

    def test_set_resume_state_ignores_missing_offset(self) -> None:
        paginator = ActiveCampaignPaginator()
        paginator.set_resume_state({})
        assert paginator.offset == 0


class TestGetResource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_resource_shape(self, endpoint: str) -> None:
        resource = get_resource(endpoint)
        config = ACTIVE_CAMPAIGN_ENDPOINTS[endpoint]

        assert resource["name"] == endpoint
        assert resource["table_name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"

        endpoint_def = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_def["path"] == config.path
        assert endpoint_def["path"].startswith("/")
        assert endpoint_def["data_selector"] == config.data_selector

    def test_contacts_orders_by_id_for_stable_pagination(self) -> None:
        resource = get_resource("contacts")
        endpoint_def = cast(dict[str, Any], resource["endpoint"])
        assert endpoint_def["params"].get("orders[id]") == "ASC"


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestActiveCampaignSourceResumeBehavior:
    """End-to-end resume behaviour of ``active_campaign_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with (
            # The pipeline path builds its own (no-redirect) session and hands it to
            # RESTClient via config, so patch the factory where the source imports it.
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.make_tracked_session"
            ) as MockSession,
            # The SSRF guard runs real DNS resolution when DEBUG=False (as in CI); the
            # fake account host here isn't an SSRF test, so allow it deterministically.
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.is_url_allowed",
                return_value=(True, None),
            ),
        ):
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source = active_campaign_source(
                api_url="https://acme.api-us1.com",
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], source.items()))
            return mock_session, sent_params

    def _page_body(self, endpoint: str, items: list[dict[str, Any]], total: Any) -> dict[str, Any]:
        selector = ACTIVE_CAMPAIGN_ENDPOINTS[endpoint].data_selector
        return {selector: items, "meta": {"total": total}}

    @pytest.mark.parametrize("endpoint", ["contacts", "deals", "lists", "campaigns"])
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body(endpoint, _full_page(), 150)),
            _make_http_response(self._page_body(endpoint, [{"id": "x"}], 150)),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        # First request starts at offset 0; the second carries the advanced offset.
        assert [p.get("offset") for p in sent_params] == [0, PAGE_SIZE]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ActiveCampaignResumeConfig(offset=PAGE_SIZE)]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ActiveCampaignResumeConfig(offset=PAGE_SIZE)

        responses = [
            _make_http_response(self._page_body("contacts", [{"id": "resumed"}], 150)),
        ]
        _, sent_params = self._drive("contacts", manager, responses)

        assert [p.get("offset") for p in sent_params] == [PAGE_SIZE]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body("contacts", [{"id": "only"}], 1)),
        ]
        self._drive("contacts", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(self._page_body("contacts", [{"id": "a"}], 1)),
        ]
        self._drive("contacts", manager, responses)

        manager.load_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        # Isolate status-code handling from the SSRF guard (which does real DNS when DEBUG=False).
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.make_tracked_session"
            ) as MockSession,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.is_url_allowed",
                return_value=(True, None),
            ),
        ):
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = status_code
            response.is_redirect = False
            mock_session.get.return_value = response

            valid, error = validate_credentials("https://acme.api-us1.com", "test-key")
            assert valid is expected_valid
            if expected_valid:
                assert error is None
            else:
                assert error is not None

    def test_rejects_non_https_url(self) -> None:
        valid, error = validate_credentials("http://acme.api-us1.com", "test-key")
        assert valid is False
        assert error is not None and "https" in error

    def test_network_error_returns_message(self) -> None:
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.make_tracked_session"
            ) as MockSession,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.is_url_allowed",
                return_value=(True, None),
            ),
        ):
            MockSession.return_value.get.side_effect = Exception("boom")
            valid, error = validate_credentials("https://acme.api-us1.com", "test-key")
            assert valid is False
            assert error == "boom"

    def test_does_not_follow_redirects(self) -> None:
        # Redirect-based SSRF guard: even a host that passes validation must not be
        # allowed to 3xx-redirect onto an internal host, so the request disables it.
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.make_tracked_session"
            ) as MockSession,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.is_url_allowed",
                return_value=(True, None),
            ),
        ):
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = 302
            response.is_redirect = True
            mock_session.get.return_value = response

            valid, error = validate_credentials("https://acme.api-us1.com", "test-key")

            assert valid is False
            assert error is not None
            assert mock_session.get.call_args.kwargs["allow_redirects"] is False

    def test_redirect_returns_actionable_account_name_message(self) -> None:
        # A redirect means the account name in the URL is likely wrong — surface that
        # instead of a bare status code.
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.make_tracked_session"
            ) as MockSession,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.is_url_allowed",
                return_value=(True, None),
            ),
        ):
            mock_session = MockSession.return_value
            response = MagicMock()
            response.status_code = 302
            response.is_redirect = True
            mock_session.get.return_value = response

            valid, error = validate_credentials("https://acme.api-us1.com", "test-key")

            assert valid is False
            assert error is not None and "account name" in error
            assert "status code" not in error


class TestSsrfProtection:
    """The user-supplied api_url must not be usable to reach internal/metadata hosts."""

    def test_validate_credentials_blocks_internal_host(self) -> None:
        with patch("posthog.security.url_validation.is_dev_mode", return_value=False):
            valid, error = validate_credentials("https://169.254.169.254", "test-key")
        assert valid is False
        assert error is not None and "not allowed" in error

    def test_source_for_pipeline_blocks_internal_host(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with (
            patch("posthog.security.url_validation.is_dev_mode", return_value=False),
            pytest.raises(ValueError, match="not allowed"),
        ):
            active_campaign_source(
                api_url="https://169.254.169.254",
                api_key="test-key",
                endpoint="contacts",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )

    def test_source_for_pipeline_disables_redirects(self) -> None:
        # The sync path hands RESTClient a session built with redirects off, so a
        # 3xx to an internal host can't be followed during a sync either.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.make_tracked_session"
            ) as MockSession,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign.is_url_allowed",
                return_value=(True, None),
            ),
        ):
            active_campaign_source(
                api_url="https://acme.api-us1.com",
                api_key="test-key",
                endpoint="contacts",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )

            assert MockSession.call_args.kwargs["allow_redirects"] is False
