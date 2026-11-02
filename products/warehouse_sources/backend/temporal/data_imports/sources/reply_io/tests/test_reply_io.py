from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.replyio import (
    ReplyIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.reply_io import (
    PAGE_SIZE,
    ReplyIoResumeConfig,
    check_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.settings import (
    ENDPOINTS,
    REPLY_IO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.source import ReplyIoSource


def _driver() -> SourceDriver:
    return SourceDriver(ReplyIoSource(), ReplyIoSourceConfig(api_key="reply-key"))


def _paged(items: list[dict[str, Any]], has_more: bool) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items, "hasMore": has_more})


def _bare(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestPagination:
    def test_follows_offset_pagination_until_hasmore_false(self) -> None:
        # A short page (< PAGE_SIZE) with hasMore=True must continue — Reply's hasMore is
        # authoritative, so unlike the built-in OffsetPaginator we don't stop on a short page.
        result = _driver().run(
            "contacts",
            [_paged([{"id": 1}, {"id": 2}, {"id": 3}], has_more=True), _paged([{"id": 4}, {"id": 5}], has_more=False)],
        )

        assert [r["id"] for r in result.rows] == [1, 2, 3, 4, 5]
        assert dict(result.requests[0].query) == {"top": (str(PAGE_SIZE),), "skip": ("0",)}
        # Offset advances by rows RECEIVED (3), not PAGE_SIZE — robust to a server-side page cap.
        assert result.requests[1].param("skip") == "3"
        # Checkpoint saved once after the first page (points at the next page); hasMore=false ends it.
        assert result.saved_states == [ReplyIoResumeConfig(skip=3)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "contacts",
            [_paged([{"id": 201}], has_more=False)],
            resume_state=ReplyIoResumeConfig(skip=200),
        )

        assert [r["id"] for r in result.rows] == [201]
        # The initial (skip=0) page is never fetched on resume.
        assert result.params("skip") == ["200"]

    @parameterized.expand([("custom_fields",), ("email_template_folders",)])
    def test_unpaginated_endpoint_fetches_bare_array_once_without_state(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_bare([{"id": 1}, {"id": 2}])])

        assert [r["id"] for r in result.rows] == [1, 2]
        assert len(result.requests) == 1
        # Bare-array endpoints take no pagination params and never persist resume state.
        assert "top" not in result.requests[0].query and "skip" not in result.requests[0].query
        assert result.saved_states == []

    def test_malformed_body_exhausts_retries_and_raises_retryable(self) -> None:
        result = _driver().run("contacts", always(_bare([{"id": 1}])))

        assert isinstance(result.raised, RESTClientRetryableError)

    def test_unpaginated_non_array_body_is_retryable(self) -> None:
        result = _driver().run("custom_fields", always(_bare({"items": []})))

        assert isinstance(result.raised, RESTClientRetryableError)


class TestCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Reply API key"),
            ("forbidden", 403, False, "Invalid Reply API key"),
            ("server_error", 500, False, "Reply returned HTTP 500"),
        ]
    )
    def test_validate_credentials_at_source_create(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert validate_credentials("reply-key") == (expected_valid, expected_message)

    def test_validate_credentials_for_endpoint_names_missing_scope(self) -> None:
        with scripted_network(always(ScriptedResponse(status=403, json={}))):
            valid, message = validate_credentials("reply-key", endpoint="sequences")
        assert valid is False
        assert message == "Your Reply API key is missing the `sequences:read` scope"


class TestEndpointPermissions:
    @parameterized.expand(
        [
            ("throttled", always(ScriptedResponse(status=429, json={}))),
            ("server_error", always(ScriptedResponse(status=500, json={}))),
            ("connection_error", always(requests.ConnectionError("boom"))),
        ]
    )
    def test_transient_errors_do_not_block_the_picker(self, _name: str, script: Script) -> None:
        with scripted_network(script):
            results = check_endpoint_permissions("reply-key", ["contacts"])
        assert results == {"contacts": None}

    def test_unknown_endpoint_reported_reachable_without_probe(self) -> None:
        with scripted_network([]) as network:
            results = check_endpoint_permissions("reply-key", ["not_a_table"])
        assert results == {"not_a_table": None}
        assert network.requests_log == []


class TestReplyIoSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        empty = _paged([], has_more=False) if REPLY_IO_ENDPOINTS[endpoint].paginated else _bare([])
        result = _driver().run(endpoint, [empty])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # Most Reply resources expose no stable creation timestamp, so we don't partition.
        assert result.response.partition_mode is None
