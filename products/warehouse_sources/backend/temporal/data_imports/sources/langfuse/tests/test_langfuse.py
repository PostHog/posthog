from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.langfuse import (
    LangfuseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse import langfuse as langfuse_module
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.langfuse import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    LangfuseResumeConfig,
    LangfuseRetryableError,
    _from_filter_value,
    _parse_retry_after,
    _retry_wait,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import LANGFUSE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source import LangfuseSource


def _response(*, status_code: int = 200, headers: Any = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    return response


def _page(items: list[dict[str, Any]], *, page: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "meta": {"page": page, "limit": 50, "totalPages": total_pages}})


def _trace(trace_id: str, timestamp: str) -> dict[str, Any]:
    return {"id": trace_id, "timestamp": timestamp}


def _not_found() -> ScriptedResponse:
    return ScriptedResponse(status=404, body=b"Not found")


def _cursor_page(items: list[dict[str, Any]], *, cursor: Optional[str]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "meta": {"cursor": cursor}})


def _driver(host: str = "https://cloud.langfuse.com") -> SourceDriver:
    return SourceDriver(LangfuseSource(), LangfuseSourceConfig(host=host, public_key="pk-lf-x", secret_key="sk-lf-x"))


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://cloud.langfuse.com"),
            ("", "https://cloud.langfuse.com"),
            ("us.cloud.langfuse.com", "https://us.cloud.langfuse.com"),
            ("https://cloud.langfuse.com/", "https://cloud.langfuse.com"),
            ("  langfuse.example.com  ", "https://langfuse.example.com"),
            ("http://langfuse.example.com:3000/", "http://langfuse.example.com:3000"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestFromFilterValue:
    def test_date_value_is_supported(self):
        value = _from_filter_value(
            LANGFUSE_ENDPOINTS["traces"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 3, 4),
            incremental_field="timestamp",
        )
        assert value == "2026-03-03T23:00:00Z"

    def test_unsupported_incremental_field_raises(self):
        with pytest.raises(ValueError):
            _from_filter_value(
                LANGFUSE_ENDPOINTS["traces"],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                incremental_field="updatedAt",
            )

    def test_full_refresh_endpoint_never_filters(self):
        value = _from_filter_value(
            LANGFUSE_ENDPOINTS["datasets"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field=None,
        )
        assert value is None


class TestValidateCredentials:
    def _patch_session(self, response=None, raises=None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = response
        return mock.patch.object(langfuse_module, "make_tracked_session", return_value=session)

    @pytest.mark.parametrize(
        "public_key, secret_key, expected_msg",
        [
            ("", "sk-lf-x", "Missing public key"),
            ("pk-lf-x", "  ", "Missing secret key"),
        ],
    )
    def test_missing_keys_short_circuit(self, public_key, secret_key, expected_msg):
        valid, msg = validate_credentials("https://cloud.langfuse.com", public_key, secret_key)
        assert valid is False
        assert msg == expected_msg

    def test_uses_basic_auth_and_no_redirects(self):
        with self._patch_session(_response(status_code=200)) as patched:
            validate_credentials("https://cloud.langfuse.com", " pk-lf-x ", " sk-lf-x ", team_id=None)
            kwargs = patched.return_value.get.call_args.kwargs
            assert kwargs["auth"] == ("pk-lf-x", "sk-lf-x")
            assert kwargs["allow_redirects"] is False
            # Adapter-level retries must stay disabled: urllib3 honors Retry-After uncapped, so a
            # hostile host could park the worker before the bounded tenacity policy runs.
            assert patched.call_args.kwargs["retry"].total == 0

    def test_rejects_redirect_response(self):
        with scripted_network([ScriptedResponse(status=302, headers={"Location": "https://example.com"})]) as network:
            valid, msg = validate_credentials("https://cloud.langfuse.com", "pk-lf-x", "sk-lf-x")
        assert valid is False
        assert "unexpected redirect" in (msg or "")
        assert [request.path for request in network.requests_log] == ["/api/public/projects"]

    def test_rejects_plaintext_http(self):
        with scripted_network([]) as network:
            valid, msg = validate_credentials("http://langfuse.example.com", "pk-lf-x", "sk-lf-x")
        assert valid is False
        assert msg == HTTP_NOT_ALLOWED_ERROR
        assert network.requests_log == []

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(langfuse_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([]) as network,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", "pk-lf-x", "sk-lf-x", team_id=99)
        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []


class TestLangfuseSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key, sort_mode",
        [
            ("traces", ["id"], "timestamp", "asc"),
            ("observations", ["id"], "startTime", "desc"),
            ("scores", ["id"], "timestamp", "desc"),
            ("sessions", ["id"], "createdAt", "desc"),
            ("prompts", ["name"], None, "desc"),
            ("datasets", ["id"], None, "desc"),
            ("dataset_items", ["id"], "createdAt", "desc"),
            ("models", ["id"], None, "desc"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key, sort_mode):
        result = _driver().run(
            endpoint, [ScriptedResponse(json={"data": [], "meta": {"totalPages": 1}})], api_version="v1"
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    def test_whole_number_costs_are_emitted_as_floats(self):
        # The oldest traces are fetched first and often carry a flat 0 cost. Left as ints they
        # create an integer column, and the first fractional cost then fails the whole sync.
        result = _driver().run(
            "traces",
            [_page([{"id": "t1", "totalCost": 0, "latency": 2}], page=1, total_pages=1)],
            api_version="v1",
        )
        rows = result.rows
        assert result.raised is None
        assert isinstance(rows[0]["totalCost"], float)
        assert isinstance(rows[0]["latency"], float)
        assert rows[0]["totalCost"] == 0.0
        assert rows[0]["latency"] == 2.0

    def test_fields_outside_float_fields_keep_their_type(self):
        # scores.value is numeric only for NUMERIC scores, so it must not be widened.
        result = _driver().run(
            "scores",
            [_cursor_page([{"id": "s1", "value": 1}, {"id": "s2", "value": "misc"}], cursor=None)],
        )
        rows = result.rows
        assert result.raised is None
        assert rows[0]["value"] == 1
        assert not isinstance(rows[0]["value"], float)
        assert rows[1]["value"] == "misc"

    def test_resume_from_saved_cursor(self):
        result = _driver().run(
            "observations",
            [_cursor_page([{"id": "o9"}], cursor=None)],
            resume_state=LangfuseResumeConfig(cursor="saved-cursor"),
        )
        assert result.params("cursor") == ["saved-cursor"]
        assert [r["id"] for r in result.rows] == ["o9"]
        assert result.raised is None

    @pytest.mark.parametrize(
        "endpoint, last_value, incremental_field, expected_from",
        [
            ("experiments", None, None, "1970-01-01T00:00:00Z"),
            ("experiment_items", None, None, "1970-01-01T00:00:00Z"),
            (
                "experiment_items",
                datetime(2026, 3, 4, 10, 0, 0, tzinfo=UTC),
                "startTime",
                "2026-03-04T09:00:00Z",
            ),
        ],
    )
    def test_experiment_endpoints_send_a_lower_bound_on_every_page(
        self, endpoint, last_value, incremental_field, expected_from
    ):
        # Both endpoints reject a request without fromStartTime, so a full sync must send one too.
        result = _driver().run(
            endpoint,
            [
                _cursor_page([{"id": "e1", "experimentId": "x1"}], cursor="next"),
                _cursor_page([{"id": "e2", "experimentId": "x1"}], cursor=None),
            ],
            db_incremental_field_last_value=last_value,
            incremental_field=incremental_field,
        )
        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["e1", "e2"]
        assert result.params("fromStartTime") == [expected_from, expected_from]
        assert result.params("cursor") == [None, "next"]

    def test_rejects_plaintext_http_before_request(self):
        result = _driver("http://langfuse.example.com").run("traces", [], api_version="v1")
        assert isinstance(result.raised, langfuse_module.LangfuseHostNotAllowedError)
        assert HTTP_NOT_ALLOWED_ERROR in str(result.raised)
        assert result.requests == []

    def test_unsafe_host_error_is_marked_non_retryable(self):
        with mock.patch.object(langfuse_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("traces", [], api_version="v1")
        assert isinstance(result.raised, langfuse_module.LangfuseHostNotAllowedError)
        assert HOST_NOT_ALLOWED_ERROR in str(result.raised)
        assert result.requests == []

    def test_redirect_response_is_refused(self):
        result = _driver().run(
            "traces", [ScriptedResponse(status=302, headers={"Location": "https://example.com"})], api_version="v1"
        )
        assert isinstance(result.raised, langfuse_module.LangfuseHostNotAllowedError)
        assert HOST_NOT_ALLOWED_ERROR in str(result.raised)
        assert len(result.requests) == 1

    @pytest.mark.parametrize(
        "attr, value, chunks",
        [
            ("MAX_RESPONSE_BYTES", 4, [b"aaaa", b"aaaa"]),  # decoded body past the byte cap
            ("MAX_TRANSFER_SECONDS", -1, [b"a"]),  # transfer past the wall-clock deadline
        ],
    )
    def test_response_over_limit_raises_non_retryable(self, attr, value, chunks):
        # A hostile/self-hosted host could stream an unbounded or slow-drip body and pin a shared
        # worker. The read must abort past either cap before parsing JSON, with a non-retryable
        # error (retrying can't shrink or speed up the body). A single queued response also proves
        # no retry happens: another request would end the scripted run with UnexpectedRequest.
        with mock.patch.object(langfuse_module, attr, value):
            result = _driver().run("traces", [ScriptedResponse(body=b"".join(chunks))], api_version="v1")
        assert isinstance(result.raised, langfuse_module.LangfuseResponseTooLargeError)
        assert langfuse_module.RESPONSE_LIMIT_ERROR in str(result.raised)
        assert len(result.requests) == 1

    def test_repeated_cursor_raises_without_checkpointing_it(self):
        # A hostile host that echoes back the cursor it was given would otherwise re-fetch the same
        # page until the activity timeout. The run must abort (non-retryable) and never checkpoint
        # the poisoned cursor — a saved checkpoint would make every retry loop on it too.
        result = _driver().run(
            "observations",
            [
                _cursor_page([{"id": "o1"}], cursor="loop"),
                _cursor_page([{"id": "o2"}], cursor="loop"),
            ],
        )
        assert isinstance(result.raised, langfuse_module.LangfusePaginationError)
        assert langfuse_module.REPEATED_CURSOR_ERROR in str(result.raised)
        # Only the first page's (legitimate) continuation was saved.
        assert result.saved_states == [LangfuseResumeConfig(cursor="loop")]

    def test_resource_limit_422_is_retried_then_recovers(self):
        # Langfuse maps a transient ClickHouse resource/timeout to 422 (validation errors are 400).
        # A 422 must flow through the backoff and recover, not surface as a fatal HTTPError that
        # fails the sync.
        result = _driver().run(
            "traces",
            [
                ScriptedResponse(status=422, json={"error": "Request timed out"}),
                _page([{"id": "t1"}], page=1, total_pages=1),
            ],
            api_version="v1",
        )
        assert [r["id"] for r in result.rows] == ["t1"]
        assert len(result.requests) == 2
        assert result.raised is None

    def test_keyset_checkpoint_carries_the_advanced_filter(self):
        # Resume reuses the saved from_value verbatim, so a checkpoint that kept the ORIGINAL bound
        # next to page 1 would restart the whole walk on the next activity attempt.
        result = _driver().run(
            "traces",
            [
                _page([_trace("t1", "2026-03-04T10:05:00Z")], page=1, total_pages=900),
                _page([_trace("t1", "2026-03-04T10:05:00Z")], page=1, total_pages=1),
            ],
            db_incremental_field_last_value=datetime(2026, 3, 4, 10, 0, 0, tzinfo=UTC),
            incremental_field="timestamp",
            api_version="v1",
        )
        assert result.raised is None
        saved = result.saved_states[-1]
        assert saved.page == 1
        assert saved.from_value == "2026-03-04T10:05:00Z"

    def test_keyset_falls_back_to_offset_when_the_bound_cannot_move(self):
        # Every row on the page sits on the current bound. Resetting to page 1 would re-issue the
        # same query forever, so the walk must keep incrementing the offset to get past them.
        result = _driver().run(
            "traces",
            [
                _page([_trace("t1", "2026-03-04T11:00:00Z")], page=1, total_pages=3),
                _page([_trace("t2", "2026-03-04T11:00:00Z")], page=2, total_pages=3),
                _page([_trace("t3", "2026-03-04T11:00:00Z")], page=3, total_pages=3),
            ],
            db_incremental_field_last_value=datetime(2026, 3, 4, 12, 0, 0, tzinfo=UTC),
            incremental_field="timestamp",
            api_version="v1",
        )
        assert result.params("page") == ["1", "2", "3"]
        assert result.raised is None

    def test_page_limit_raises_after_checkpointing_next_page(self):
        # A hostile host reporting ever-more totalPages would otherwise keep the loop alive until
        # the activity timeout. The run must abort at the cap — retryably, with the next page
        # already checkpointed, so a legitimately huge sync continues on the next attempt.
        with mock.patch.object(langfuse_module, "MAX_PAGES_PER_RUN", 2):
            result = _driver().run(
                "traces",
                [
                    _page([{"id": "t1"}], page=1, total_pages=10),
                    _page([{"id": "t2"}], page=2, total_pages=10),
                ],
                api_version="v1",
            )
        assert isinstance(result.raised, langfuse_module.LangfusePaginationError)
        assert langfuse_module.PAGE_LIMIT_ERROR in str(result.raised)
        assert result.saved_states[-1].page == 3

    def test_parent_id_listing_over_byte_budget_raises_non_retryable(self):
        # Parent ids are all buffered before the first child row is yielded, so a hostile host
        # streaming unique large ids must be cut off at the budget rather than grow worker memory.
        with mock.patch.object(langfuse_module, "MAX_PARENT_ID_BYTES", 100):
            result = _driver().run(
                "annotation_queue_items",
                [_page([{"id": "q-aaaaaa"}, {"id": "q-bbbbbb"}], page=1, total_pages=1)],
            )
        assert isinstance(result.raised, langfuse_module.LangfuseResponseTooLargeError)
        assert langfuse_module.RESPONSE_LIMIT_ERROR in str(result.raised)

    def test_fan_out_walks_every_parent_and_checkpoints_the_next_one(self):
        result = _driver().run(
            "annotation_queue_items",
            [
                _page([{"id": "q-c"}, {"id": "q/a"}], page=1, total_pages=2),
                _page([{"id": "q-b"}], page=2, total_pages=2),
                _page([{"id": "i1", "queueId": "q-b"}], page=1, total_pages=2),
                _page([{"id": "i2", "queueId": "q-b"}], page=2, total_pages=2),
                _not_found(),
                _page([{"id": "i3", "queueId": "q/a"}], page=1, total_pages=1),
            ],
        )

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["i1", "i2", "i3"]
        assert result.paths[2:] == [
            "/api/public/annotation-queues/q-b/items",
            "/api/public/annotation-queues/q-b/items",
            "/api/public/annotation-queues/q-c/items",
            "/api/public/annotation-queues/q%2Fa/items",
        ]
        saved = [(state.parent_id, state.page) for state in result.saved_states]
        assert saved == [("q-b", 2), ("q-c", 1), ("q/a", 1)]

    @pytest.mark.parametrize(
        "saved_parent, expected_url_parent, expected_page",
        [
            ("q-b", "q-b", 3),
            # The saved parent was deleted, so its successor starts from its first page.
            ("q-bb", "q-c", 1),
        ],
    )
    def test_fan_out_resumes_from_saved_parent(self, saved_parent, expected_url_parent, expected_page):
        result = _driver().run(
            "annotation_queue_items",
            [
                _page([{"id": "q-a"}, {"id": "q-b"}, {"id": "q-c"}], page=1, total_pages=1),
                _page([{"id": "i9", "queueId": expected_url_parent}], page=expected_page, total_pages=expected_page),
                _page([], page=1, total_pages=0),
            ],
            resume_state=LangfuseResumeConfig(page=3, parent_id=saved_parent),
        )

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["i9"]
        assert result.requests[1].path.endswith(f"/annotation-queues/{expected_url_parent}/items")
        assert result.requests[1].param("page") == str(expected_page)


class TestRetryBehavior:
    @pytest.mark.parametrize(
        "headers, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "100000"}, 120.0),  # capped
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),  # HTTP-date ignored
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, headers, expected):
        assert _parse_retry_after(_response(headers=headers)) == expected

    def test_retry_wait_prefers_retry_after(self):
        state = mock.MagicMock()
        state.outcome.exception.return_value = LangfuseRetryableError("rate limited", retry_after=7.0)
        assert _retry_wait(state) == 7.0
