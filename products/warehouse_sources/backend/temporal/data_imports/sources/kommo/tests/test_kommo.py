import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.kommo import (
    KommoResumeConfig,
    get_resource,
    kommo_source,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.settings import (
    ENDPOINT_CONFIG,
    ENDPOINTS,
    PAGE_LIMIT,
)

SESSION_FACTORY = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _http_response(body: dict[str, Any] | None, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response.url = "https://acme.kommo.com/api/v4/leads"
    if body is None:
        response._content = b""
    else:
        response._content = json.dumps(body).encode()
        response.headers["Content-Type"] = "application/hal+json"
    return response


def _leads_page(ids: list[int], page: int, page_count: int) -> dict[str, Any]:
    return {
        "_page": page,
        "_page_count": page_count,
        "_embedded": {"leads": [{"id": lead_id, "updated_at": 1700000000 + lead_id} for lead_id in ids]},
    }


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("acme", "acme"),
            ("  ACME  ", "acme"),
            ("acme.kommo.com", "acme"),
            ("https://acme.kommo.com", "acme"),
            ("https://acme.kommo.com/leads", "acme"),
            ("http://acme.kommo.com/", "acme"),
            ("my-acme-2", "my-acme-2"),
        ],
    )
    def test_accepts_and_reduces_valid_account_references(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "acme.amocrm.ru",
            "evil.example.com",
            "acme.kommo.com.evil.example.com",
            "acme..kommo.com",
            "-acme",
            "acme-",
            "acme_corp",
            "acme:8080",
            "10.0.0.1",
            "acme kommo",
        ],
    )
    def test_rejects_anything_that_is_not_a_single_kommo_label(self, raw: str) -> None:
        # The subdomain picks the host the access token is sent to, so a value that
        # smuggles another host through must be rejected rather than normalized.
        assert normalize_subdomain(raw) is None


class TestGetResource:
    def test_every_declared_endpoint_builds_a_resource(self) -> None:
        for name in ENDPOINTS:
            resource = get_resource(name, should_use_incremental_field=False)
            endpoint = cast(dict[str, Any], resource["endpoint"])

            assert resource["name"] == name
            assert resource["primary_key"] == ENDPOINT_CONFIG[name].primary_key
            assert endpoint["path"].startswith("/api/v4/")
            assert endpoint["data_selector"].startswith("_embedded.")

    @pytest.mark.parametrize("name", ["Leads", "Contacts", "Companies", "LeadNotes", "ContactNotes", "CompanyNotes"])
    def test_incremental_endpoints_bind_the_updated_at_filter_and_merge(self, name: str) -> None:
        resource = get_resource(name, should_use_incremental_field=True)
        params = cast(dict[str, Any], resource["endpoint"])["params"]

        assert params["filter[updated_at][from]"] == {
            "type": "incremental",
            "cursor_path": "updated_at",
            "initial_value": 0,
        }
        assert params["order[updated_at]"] == "asc"
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @pytest.mark.parametrize("name", ["Tasks", "Events", "Pipelines", "Users", "Catalogs", "LeadTags"])
    def test_full_refresh_endpoints_never_bind_a_filter_even_when_asked(self, name: str) -> None:
        # Tasks and Events do expose a server-side timestamp filter but no ordering parameter for
        # it, so they must stay full refresh: an unordered incremental sync corrupts the watermark.
        resource = get_resource(name, should_use_incremental_field=True)
        params = cast(dict[str, Any], resource["endpoint"])["params"]

        assert not any(key.startswith("filter[") for key in params)
        assert resource["write_disposition"] == "replace"

    @pytest.mark.parametrize("name", ["Leads", "Tasks", "Users"])
    def test_paginated_endpoints_request_the_maximum_page_size(self, name: str) -> None:
        # Kommo allows 7 requests/second per account, so under-filling pages costs real throughput.
        resource = get_resource(name, should_use_incremental_field=False)
        endpoint = cast(dict[str, Any], resource["endpoint"])

        assert endpoint["params"]["limit"] == PAGE_LIMIT
        assert isinstance(endpoint["paginator"], PageNumberPaginator)

    def test_unpaginated_endpoint_uses_a_single_page_paginator(self) -> None:
        resource = get_resource("Pipelines", should_use_incremental_field=False)
        endpoint = cast(dict[str, Any], resource["endpoint"])

        assert isinstance(endpoint["paginator"], SinglePagePaginator)
        assert "limit" not in endpoint["params"]


class TestKommoSourceTransport:
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        *,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> list[dict[str, Any]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(SESSION_FACTORY) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = kommo_source(
                api_key="test-token",
                subdomain="acme",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            )
            list(cast(Iterable[Any], resource))

        return sent_params

    def test_pages_through_until_the_empty_no_content_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _http_response(_leads_page([1, 2], page=1, page_count=3)),
            _http_response(_leads_page([3, 4], page=2, page_count=3)),
            _http_response(_leads_page([5], page=3, page_count=3)),
        ]
        sent_params = self._drive("Leads", manager, responses)

        assert [params["page"] for params in sent_params] == [1, 2, 3]

    def test_stops_on_a_204_style_empty_body_when_page_count_is_absent(self) -> None:
        # Kommo answers 204 with no body once you page past the end; a JSON decode of that
        # body would blow up if the client did not treat it as an empty page.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _http_response({"_page": 1, "_embedded": {"tags": [{"id": 1, "name": "vip"}]}}),
            _http_response(None, status_code=204),
        ]
        sent_params = self._drive("LeadTags", manager, responses)

        assert [params["page"] for params in sent_params] == [1, 2]

    def test_full_refresh_run_checkpoints_the_next_page_after_each_batch(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _http_response(_leads_page([1], page=1, page_count=3)),
            _http_response(_leads_page([2], page=2, page_count=3)),
            _http_response(_leads_page([3], page=3, page_count=3)),
        ]
        self._drive("Leads", manager, responses)

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [KommoResumeConfig(page=2), KommoResumeConfig(page=3)]

    def test_full_refresh_run_resumes_from_the_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = KommoResumeConfig(page=7)

        responses = [_http_response(_leads_page([9], page=7, page_count=7))]
        sent_params = self._drive("Leads", manager, responses)

        assert [params["page"] for params in sent_params] == [7]

    def test_incremental_run_neither_saves_nor_loads_a_page(self) -> None:
        # The watermark moves after every batch, so page N of a resumed incremental query is not
        # page N of the interrupted one. Resuming by page there would skip rows.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = KommoResumeConfig(page=7)

        responses = [
            _http_response(_leads_page([1], page=1, page_count=2)),
            _http_response(_leads_page([2], page=2, page_count=2)),
        ]
        sent_params = self._drive(
            "Leads",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1699999999,
        )

        assert [params["page"] for params in sent_params] == [1, 2]
        manager.load_state.assert_not_called()
        manager.save_state.assert_not_called()

    def test_incremental_run_sends_the_stored_watermark_as_the_filter_lower_bound(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_http_response(_leads_page([1], page=1, page_count=1))]
        sent_params = self._drive(
            "Leads",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1699999999,
        )

        assert sent_params[0]["filter[updated_at][from]"] == 1699999999
        assert sent_params[0]["order[updated_at]"] == "asc"

    def test_full_refresh_run_sends_no_filter(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_http_response(_leads_page([1], page=1, page_count=1))]
        sent_params = self._drive("Leads", manager, responses)

        assert not any(key.startswith("filter[") for key in sent_params[0])


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_ok", "expected_message_fragment"),
        [
            (200, True, None),
            (401, False, "rejected the access token"),
            (403, False, "cannot access the account"),
            (402, False, "not paid up"),
            (404, False, "acme.kommo.com"),
            (500, False, "unexpected 500"),
        ],
    )
    def test_maps_status_codes_to_actionable_results(
        self, status_code: int, expected_ok: bool, expected_message_fragment: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.kommo.kommo.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _http_response({}, status_code=status_code)

            is_valid, message = validate_credentials("test-token", "acme")

        assert is_valid is expected_ok
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message

    def test_probes_the_account_endpoint_on_the_accounts_own_host(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.kommo.kommo.make_tracked_session"
        ) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _http_response({}, status_code=200)

            validate_credentials("test-token", "acme")

        url = session.get.call_args.args[0]
        assert url == "https://acme.kommo.com/api/v4/account"
        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"
