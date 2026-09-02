import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.beehiiv import (
    BeehiivResumeConfig,
    beehiiv_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.settings import (
    ENDPOINTS,
    MAX_PAGE,
    PAGE_SIZE,
    PUBLICATION_PATH_PLACEHOLDER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REST_CLIENT_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source"
    ".rest_client.make_tracked_session"
)
TRANSPORT_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.beehiiv.make_tracked_session"
)

CURSOR_ENDPOINTS = [name for name, config in ENDPOINTS.items() if config.pagination == "cursor"]
PAGE_ENDPOINTS = [name for name, config in ENDPOINTS.items() if config.pagination == "page"]


def _http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _drive(
    endpoint: str,
    manager: Any,
    responses: list[Response],
    publication_id: str = "pub_123",
) -> list[dict[str, Any]]:
    """Run ``beehiiv_source`` against a mocked session.

    Returns the per-request query params, copied at send time because the paginator
    mutates the Request in place between pages.
    """
    sent_params: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_params.append(dict(request.params or {}))
        return next(response_iter)

    with patch(REST_CLIENT_SESSION) as mock_make_session:
        session = mock_make_session.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: request
        session.send.side_effect = fake_send

        source_response = beehiiv_source(
            api_key="test-key",
            publication_id=publication_id,
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            api_version="v2",
            resumable_source_manager=manager,
        )
        list(cast(Iterable[Any], source_response.items()))

    return sent_params


def _fresh_manager() -> Any:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


class TestBeehiivResourceConfig:
    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_publication_placeholder_is_always_substituted(self, endpoint: str) -> None:
        resource = get_resource(endpoint, "pub_abc")
        endpoint_config = cast(dict[str, Any], resource["endpoint"])

        assert PUBLICATION_PATH_PLACEHOLDER not in endpoint_config["path"]

    def test_publication_id_is_url_quoted_into_the_path(self) -> None:
        # The publication id is user-supplied and lands in the URL path; an unescaped
        # value could reach a different beehiiv endpoint than the one we configured.
        resource = get_resource("Subscriptions", "pub_a b/../webhooks")
        endpoint_config = cast(dict[str, Any], resource["endpoint"])

        assert endpoint_config["path"] == "/publications/pub_a%20b%2F..%2Fwebhooks/subscriptions"

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_every_endpoint_requests_full_pages_from_the_data_envelope(self, endpoint: str) -> None:
        # Without an explicit limit beehiiv returns 10 rows a page, and without a required
        # `data` selector a changed response shape would silently sync zero rows.
        resource = get_resource(endpoint, "pub_abc")
        endpoint_config = cast(dict[str, Any], resource["endpoint"])

        assert cast(dict[str, Any], endpoint_config["params"])["limit"] == PAGE_SIZE
        assert endpoint_config["data_selector"] == "data"
        assert endpoint_config["data_selector_required"] is True


class TestBeehiivCursorPagination:
    @pytest.mark.parametrize("endpoint", CURSOR_ENDPOINTS)
    def test_follows_next_cursor_and_checkpoints_each_non_terminal_page(self, endpoint: str) -> None:
        manager = _fresh_manager()
        responses = [
            _http_response({"data": [{"id": "a"}], "has_more": True, "next_cursor": "cur-1"}),
            _http_response({"data": [{"id": "b"}], "has_more": True, "next_cursor": "cur-2"}),
            _http_response({"data": [{"id": "c"}], "has_more": False, "next_cursor": None}),
        ]

        sent_params = _drive(endpoint, manager, responses)

        assert [params.get("cursor") for params in sent_params] == [None, "cur-1", "cur-2"]
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            BeehiivResumeConfig(paginator_state={"cursor": "cur-1"}),
            BeehiivResumeConfig(paginator_state={"cursor": "cur-2"}),
        ]

    def test_resume_seeds_the_saved_cursor_on_the_first_request(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BeehiivResumeConfig(paginator_state={"cursor": "cur-saved"})

        sent_params = _drive(
            "Subscriptions",
            manager,
            [_http_response({"data": [{"id": "a"}], "has_more": False, "next_cursor": None})],
        )

        assert [params.get("cursor") for params in sent_params] == ["cur-saved"]

    def test_terminal_page_does_not_checkpoint(self) -> None:
        manager = _fresh_manager()

        _drive(
            "Subscriptions",
            manager,
            [_http_response({"data": [{"id": "a"}], "has_more": False, "next_cursor": None})],
        )

        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()


class TestBeehiivPageNumberPagination:
    @pytest.mark.parametrize("endpoint", PAGE_ENDPOINTS)
    def test_walks_pages_and_stops_at_total_pages(self, endpoint: str) -> None:
        # beehiiv reports total_pages, so the last page must not be followed by a wasted
        # request for an empty page.
        manager = _fresh_manager()
        responses = [
            _http_response({"data": [{"id": "a"}], "page": 1, "total_pages": 2}),
            _http_response({"data": [{"id": "b"}], "page": 2, "total_pages": 2}),
        ]

        sent_params = _drive(endpoint, manager, responses)

        assert [params.get("page") for params in sent_params] == [1, 2]
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            BeehiivResumeConfig(paginator_state={"page": 2}),
        ]

    def test_stops_at_the_hundred_page_offset_cap(self) -> None:
        # beehiiv rejects offset pagination past page 100, so a publication reporting more
        # pages must stop rather than error the whole sync out.
        manager = _fresh_manager()
        responses = [
            _http_response({"data": [{"id": str(page)}], "page": page, "total_pages": 500})
            for page in range(1, MAX_PAGE + 1)
        ]

        sent_params = _drive("Posts", manager, responses)

        assert [params.get("page") for params in sent_params] == list(range(1, MAX_PAGE + 1))

    def test_resume_seeds_the_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BeehiivResumeConfig(paginator_state={"page": 7})

        sent_params = _drive(
            "Posts",
            manager,
            [_http_response({"data": [{"id": "a"}], "page": 7, "total_pages": 7})],
        )

        assert [params.get("page") for params in sent_params] == [7]


class TestBeehiivValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "allow_missing_scope", "expected_ok"),
        [
            (200, True, True),
            (200, False, True),
            (401, True, False),
            (401, False, False),
            # A beehiiv key scoped to subscriptions only cannot read the publication object;
            # that must not block source creation, but it must fail a per-table check.
            (403, True, True),
            (403, False, False),
            (404, True, False),
            (500, True, False),
        ],
    )
    def test_status_code_maps_to_credential_result(
        self, status_code: int, allow_missing_scope: bool, expected_ok: bool
    ) -> None:
        with patch(TRANSPORT_SESSION) as mock_make_session:
            mock_make_session.return_value.get.return_value = _http_response({}, status_code=status_code)

            is_valid, error = validate_credentials(
                api_key="key",
                publication_id="pub_1",
                api_version="v2",
                allow_missing_scope=allow_missing_scope,
            )

        assert is_valid is expected_ok
        assert (error is None) is expected_ok

    def test_transport_failure_is_reported_not_raised(self) -> None:
        with patch(TRANSPORT_SESSION) as mock_make_session:
            mock_make_session.return_value.get.side_effect = OSError("connection reset")

            is_valid, error = validate_credentials(
                api_key="key",
                publication_id="pub_1",
                api_version="v2",
                allow_missing_scope=True,
            )

        assert is_valid is False
        assert error == "connection reset"

    def test_api_key_is_registered_for_redaction(self) -> None:
        # The key rides an Authorization header on a tracked session; without redaction it
        # can land in captured request samples.
        with patch(TRANSPORT_SESSION) as mock_make_session:
            mock_make_session.return_value.get.return_value = _http_response({}, status_code=200)

            validate_credentials(
                api_key="super-secret",
                publication_id="pub_1",
                api_version="v2",
                allow_missing_scope=True,
            )

        assert mock_make_session.call_args.kwargs["redact_values"] == ("super-secret",)
