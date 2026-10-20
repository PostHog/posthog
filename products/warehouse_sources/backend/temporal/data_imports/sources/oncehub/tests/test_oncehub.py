from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.oncehub import (
    OncehubSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.oncehub import (
    PAGE_SIZE,
    OncehubResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.settings import (
    ENDPOINTS,
    ONCEHUB_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.source import OncehubSource


def _response(items: list[dict[str, Any]] | None, has_more: bool, *, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(
        status=status,
        json={"object": "list", "data": items if items is not None else [], "has_more": has_more},
    )


def _full_page(prefix: str) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}-{i}"} for i in range(PAGE_SIZE)]


def _driver() -> SourceDriver:
    return SourceDriver(OncehubSource(), OncehubSourceConfig(api_key="oncehub-key"))


class TestPagination:
    def test_follows_after_cursor_until_has_more_false(self) -> None:
        first_page = _full_page("BKNG")
        last_id = first_page[-1]["id"]
        result = _driver().run(
            "bookings",
            [_response(first_page, has_more=True), _response([{"id": "BKNG-final"}], has_more=False)],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        # First page carries only the limit; the second advances by the last item's id via `after`.
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        assert result.params("after") == [None, last_id]
        # State is saved once after the first page (cursor = last id), then the short page ends it.
        assert result.saved_states == [OncehubResumeConfig(cursor=last_id)]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "bookings",
            [_response([{"id": "BKNG-100"}], has_more=False)],
            resume_state=OncehubResumeConfig(cursor="BKNG-99"),
        )

        assert result.raised is None
        assert result.rows == [{"id": "BKNG-100"}]
        # The initial (cursor-less) page must never be fetched on resume: the first request carries `after`.
        assert len(result.requests) == 1
        assert result.params("limit") == [str(PAGE_SIZE)]
        assert result.params("after") == ["BKNG-99"]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int) -> None:
        result = _driver().run("bookings", always(_response([], has_more=False, status=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        # 429/5xx are retried by the client up to its attempt cap, then reraised.
        assert len(result.requests) == 5
        assert set(result.paths) == {"/v2/bookings"}

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _driver().run("bookings", [_response([], has_more=False, status=status)])

        assert isinstance(result.raised, requests.HTTPError)
        # Permanent 4xx is not retried.
        assert len(result.requests) == 1

    def test_non_list_body_raises_loudly(self) -> None:
        # A 200 payload that is a bare list (not the {"data": [...]} envelope) means the shape changed.
        result = _driver().run("bookings", [ScriptedResponse(json=[{"id": "BKNG-1"}])])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("bookings", [ScriptedResponse(json={"object": "list", "has_more": False})])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("oncehub-key") == (expected_valid, expected_message)

        assert {request.path for request in network.requests_log} == {"/v2/users"}
        assert {request.param("limit") for request in network.requests_log} == {"1"}

    def test_unreachable_probe_is_not_validated(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            assert validate_credentials("oncehub-key") == (False, "Could not validate OnceHub API key")

        assert {request.path for request in network.requests_log} == {"/v2/users"}


class TestOncehubSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([], has_more=False)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # Lists paginate newest-first with no stable ascending order, so we don't partition.
        assert result.response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in ONCEHUB_ENDPOINTS.values())
        assert set(ONCEHUB_ENDPOINTS) == set(ENDPOINTS)
