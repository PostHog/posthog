from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.beehiiv import (
    BeehiivResumeConfig,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.settings import ENDPOINTS, MAX_PAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.source import BeehiivSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.beehiiv import (
    BeehiivSourceConfig,
)

CURSOR_ENDPOINTS = [name for name, config in ENDPOINTS.items() if config.pagination == "cursor"]
PAGE_ENDPOINTS = [name for name, config in ENDPOINTS.items() if config.pagination == "page"]


def _driver(publication_id: str = "pub_123") -> SourceDriver:
    return SourceDriver(BeehiivSource(), BeehiivSourceConfig(api_key="test-key", publication_id=publication_id))


class TestBeehiivResourceConfig:
    def test_publication_id_is_url_quoted_into_the_path(self) -> None:
        # The publication id is user-supplied and lands in the URL path; an unescaped
        # value could reach a different beehiiv endpoint than the one we configured.
        resource = get_resource("Subscriptions", "pub_a b/../webhooks")
        endpoint_config = cast(dict[str, Any], resource["endpoint"])

        assert endpoint_config["path"] == "/publications/pub_a%20b%2F..%2Fwebhooks/subscriptions"


class TestBeehiivCursorPagination:
    @pytest.mark.parametrize("endpoint", CURSOR_ENDPOINTS)
    def test_follows_next_cursor_and_checkpoints_each_non_terminal_page(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": "a"}], "has_more": True, "next_cursor": "cur-1"}),
                ScriptedResponse(json={"data": [{"id": "b"}], "has_more": True, "next_cursor": "cur-2"}),
                ScriptedResponse(json={"data": [{"id": "c"}], "has_more": False, "next_cursor": None}),
            ],
        )

        assert result.raised is None
        assert result.params("cursor") == [None, "cur-1", "cur-2"]
        assert result.rows == [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        assert result.saved_states == [
            BeehiivResumeConfig(paginator_state={"cursor": "cur-1"}),
            BeehiivResumeConfig(paginator_state={"cursor": "cur-2"}),
        ]

    def test_resume_seeds_the_saved_cursor_on_the_first_request(self) -> None:
        result = _driver().run(
            "Subscriptions",
            [ScriptedResponse(json={"data": [{"id": "a"}], "has_more": False, "next_cursor": None})],
            resume_state=BeehiivResumeConfig(paginator_state={"cursor": "cur-saved"}),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cur-saved"]


class TestBeehiivPageNumberPagination:
    @pytest.mark.parametrize("endpoint", PAGE_ENDPOINTS)
    def test_walks_pages_and_stops_at_total_pages(self, endpoint: str) -> None:
        # beehiiv reports total_pages, so the last page must not be followed by a wasted
        # request for an empty page.
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": "a"}], "page": 1, "total_pages": 2}),
                ScriptedResponse(json={"data": [{"id": "b"}], "page": 2, "total_pages": 2}),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.rows == [{"id": "a"}, {"id": "b"}]
        assert result.saved_states == [BeehiivResumeConfig(paginator_state={"page": 2})]

    def test_stops_at_the_hundred_page_offset_cap(self) -> None:
        # beehiiv rejects offset pagination past page 100, so a publication reporting more
        # pages must stop rather than error the whole sync out.
        result = _driver().run(
            "Posts",
            [
                ScriptedResponse(json={"data": [{"id": str(page)}], "page": page, "total_pages": 500})
                for page in range(1, MAX_PAGE + 1)
            ],
        )

        assert result.raised is None
        assert result.params("page") == [str(page) for page in range(1, MAX_PAGE + 1)]
        assert len(result.rows) == MAX_PAGE

    def test_resume_seeds_the_saved_page(self) -> None:
        result = _driver().run(
            "Posts",
            [ScriptedResponse(json={"data": [{"id": "a"}], "page": 7, "total_pages": 7})],
            resume_state=BeehiivResumeConfig(paginator_state={"page": 7}),
        )

        assert result.raised is None
        assert result.params("page") == ["7"]


class TestBeehiivValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "allow_missing_scope", "expected_ok"),
        [
            # A beehiiv key scoped to subscriptions only cannot read the publication object;
            # that must not block source creation, but it must fail a per-table check.
            (403, True, True),
            (403, False, False),
            (404, True, False),
        ],
    )
    def test_status_code_maps_to_credential_result(
        self, status_code: int, allow_missing_scope: bool, expected_ok: bool
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, error = validate_credentials(
                api_key="key",
                publication_id="pub_1",
                api_version="v2",
                allow_missing_scope=allow_missing_scope,
            )

        assert is_valid is expected_ok
        assert (error is None) is expected_ok
        assert {request.path for request in network.requests_log} == {"/v2/publications/pub_1"}

    def test_transport_failure_is_reported_not_raised(self) -> None:
        with scripted_network(always(ConnectionResetError("connection reset"))) as network:
            is_valid, error = validate_credentials(
                api_key="key",
                publication_id="pub_1",
                api_version="v2",
                allow_missing_scope=True,
            )

        assert is_valid is False
        assert error is not None and "connection reset" in error
        assert {request.path for request in network.requests_log} == {"/v2/publications/pub_1"}

    def test_api_key_is_registered_for_redaction(self) -> None:
        # The key rides an Authorization header on a tracked session; without redaction it
        # can land in captured request samples.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials(
                api_key="super-secret",
                publication_id="pub_1",
                api_version="v2",
                allow_missing_scope=True,
            )

        assert network.session_options[0]["redact_values"] == ("super-secret",)
