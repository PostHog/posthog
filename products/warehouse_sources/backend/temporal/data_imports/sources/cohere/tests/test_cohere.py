from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.cohere import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.settings import (
    COHERE_ENDPOINTS,
    RETIRED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.source import CohereSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cohere import CohereSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(CohereSource(), CohereSourceConfig(api_key="key"))


def _response(
    data_key: str | None, items: list[dict[str, Any]] | None, extra: dict[str, Any] | None = None
) -> ScriptedResponse:
    body: dict[str, Any] = dict(extra or {})
    if data_key is not None:
        body[data_key] = items or []
    return ScriptedResponse(json=body)


class TestOffsetPagination:
    def test_paginates_and_progresses(self) -> None:
        full_page = [{"id": f"d_{i}"} for i in range(100)]
        result = _driver().run(
            "datasets", [_response("datasets", full_page), _response("datasets", [{"id": "d_last"}])]
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [*(f"d_{i}" for i in range(100)), "d_last"]
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]
        # A full page advances the offset; the short second page ends pagination without a third request.
        assert len(result.requests) == 2


class TestPageTokenPagination:
    @pytest.mark.parametrize(
        "endpoint, key, expected_path, expected_order_by",
        [
            ("models", "name", "/v1/models", [None, None]),
            # Batches exist only on /v2/; a /v1/ request would 404 on every sync.
            ("batches", "id", "/v2/batches", ["created_at", "created_at"]),
        ],
    )
    def test_follows_next_page_token(
        self, endpoint: str, key: str, expected_path: str, expected_order_by: list[str | None]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response(endpoint, [{key: "first"}], extra={"next_page_token": "t2"}),
                _response(endpoint, [{key: "second"}]),
            ],
        )

        assert result.raised is None
        assert [row[key] for row in result.rows] == ["first", "second"]
        assert {request.path for request in result.requests} == {expected_path}
        # First request carries the page size but no token; the second carries the token from the
        # first response. Absence of a token in the second response ends pagination. Both endpoints
        # cap page_size at 1000.
        assert result.params("page_size") == ["1000", "1000"]
        assert result.params("page_token") == [None, "t2"]
        assert result.params("order_by") == expected_order_by
        assert len(result.requests) == 2


class TestSinglePage:
    def test_unpaginated_endpoint_makes_single_request(self) -> None:
        result = _driver().run("embed_jobs", [_response("embed_jobs", [{"job_id": "j1"}, {"job_id": "j2"}])])

        assert result.raised is None
        assert [row["job_id"] for row in result.rows] == ["j1", "j2"]
        assert len(result.requests) == 1


class TestFailLoud:
    def test_missing_envelope_key_raises_instead_of_emptying(self) -> None:
        # A 200 body whose shape lacks the envelope key must fail loud, not be treated as an empty
        # page that clears the full-refresh table.
        result = _driver().run("datasets", [_response("unexpected", [])])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    def test_empty_body_yields_nothing(self) -> None:
        # Cohere returns a bare {} for an empty collection (an account with no datasets) rather than
        # {"datasets": []}; that empty body is a valid 0-row page, not a shape change.
        result = _driver().run("datasets", [_response(None, None)])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1


class TestSourceResponseShape:
    @pytest.mark.parametrize("endpoint", list(COHERE_ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        config = COHERE_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_response(None, None)])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            assert response.partition_count == 1
            assert response.partition_size == 1
        else:
            # The model catalog has no creation timestamp, so it must stay fully unpartitioned.
            # partition_count/size are left None too: a stray count makes the writer fall back to
            # primary_keys and md5-partition by name.
            assert response.partition_mode is None
            assert response.partition_keys is None
            assert response.partition_count is None
            assert response.partition_size is None


class TestValidateCredentials:
    def test_network_error_is_false(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("key") is False

        assert {request.path for request in network.requests_log} == {"/v1/models"}

    def test_session_redacts_api_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("secret-key") is True

        assert network.session_options[0]["redact_values"] == ("secret-key",)
        assert network.requests_log[0].headers["authorization"] == "Bearer secret-key"


class TestRetiredEndpoints:
    @pytest.mark.parametrize("endpoint", sorted(RETIRED_ENDPOINTS))
    def test_retired_endpoint_explains_itself_without_calling_cohere(self, endpoint: str) -> None:
        # Cohere removed both routes, so a request could only ever 404 and burn the retry budget of
        # a schema that was created while the endpoint still existed.
        result = _driver().run(endpoint, [])

        assert isinstance(result.raised, ValueError)
        assert "Turn off syncing for this table" in str(result.raised)
        assert result.requests == []
