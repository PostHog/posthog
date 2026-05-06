import json
import base64
from datetime import UTC, datetime

from django.apps import apps

from products.tracing.backend.presentation.views import _encode_trace_spans_cursor


def test_tracing_app_is_installed():
    assert apps.is_installed("products.tracing.backend")


def test_encode_trace_spans_cursor_roundtrip_shape():
    row = {"timestamp": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "uuid": "abc-uuid"}
    cursor = _encode_trace_spans_cursor(row)
    decoded = json.loads(base64.b64decode(cursor).decode("utf-8"))
    assert decoded["uuid"] == "abc-uuid"
    assert decoded["timestamp"] == "2026-01-02T03:04:05+00:00"
