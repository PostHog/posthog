from types import SimpleNamespace

import pytest

from llm_gateway.request_context import (
    RequestContext,
    _parse_traceparent_trace_id,
    apply_posthog_context_from_headers,
    get_traceparent_trace_id,
    rebuild_request_context,
    set_request_context,
)

VALID_TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
VALID_TRACE_UUID = "0af76519-16cd-43dd-8448-eb211c80319c"


class TestParseTraceparentTraceId:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (VALID_TRACEPARENT, VALID_TRACE_UUID),
            # Unknown versions are tolerated per W3C — only the trace-id field is read.
            ("cc-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01", VALID_TRACE_UUID),
            (None, None),
            ("", None),
            ("garbage", None),
            ("00-shorttraceid-b7ad6b7169203331-01", None),
            ("00-zzf7651916cd43dd8448eb211c80319z-b7ad6b7169203331-01", None),
            ("00-00000000000000000000000000000000-b7ad6b7169203331-01", None),
            ("00-0af7651916cd43dd8448eb211c80319c", None),
        ],
    )
    def test_parses_or_rejects(self, value, expected):
        assert _parse_traceparent_trace_id(value) == expected


class TestApplyCapturesTraceparent:
    def test_traceparent_lands_in_context(self):
        set_request_context(RequestContext(request_id="r1"))
        request = SimpleNamespace(headers={"traceparent": VALID_TRACEPARENT})
        apply_posthog_context_from_headers(request)
        assert get_traceparent_trace_id() == VALID_TRACE_UUID

    def test_absent_header_leaves_none(self):
        set_request_context(RequestContext(request_id="r2"))
        apply_posthog_context_from_headers(SimpleNamespace(headers={}))
        assert get_traceparent_trace_id() is None

    def test_malformed_header_leaves_none(self):
        set_request_context(RequestContext(request_id="r3"))
        apply_posthog_context_from_headers(SimpleNamespace(headers={"traceparent": "nonsense"}))
        assert get_traceparent_trace_id() is None


class TestRebuildRequestContextCarriesTraceparent:
    def test_survives_the_handler_rebuild(self):
        # handler.py replaces the context mid-request; the traceparent must survive it.
        set_request_context(RequestContext(request_id="r4"))
        request = SimpleNamespace(headers={"traceparent": VALID_TRACEPARENT})
        apply_posthog_context_from_headers(request)

        rebuild_request_context("llm_gateway")

        assert get_traceparent_trace_id() == VALID_TRACE_UUID

        rebuild_request_context("llm_gateway")

        assert get_traceparent_trace_id() == VALID_TRACE_UUID
