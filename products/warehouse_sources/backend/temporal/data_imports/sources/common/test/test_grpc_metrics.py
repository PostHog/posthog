import pytest
from unittest.mock import patch

import grpc

from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.metrics import (
    _NullCounter,
    _NullHistogram,
    _reset_cache_for_tests,
    get_grpc_latency_histogram,
    get_grpc_requests_counter,
    get_grpc_response_bytes_histogram,
    status_class,
)


@pytest.fixture(autouse=True)
def _reset_instrument_cache():
    """The instrument cache is process-global; clear it between tests."""
    _reset_cache_for_tests()
    yield
    _reset_cache_for_tests()


@pytest.mark.parametrize(
    "code,expected",
    [
        (None, "error"),
        (grpc.StatusCode.OK, "ok"),
        (grpc.StatusCode.RESOURCE_EXHAUSTED, "resource_exhausted"),
        (grpc.StatusCode.INVALID_ARGUMENT, "client_error"),
        (grpc.StatusCode.NOT_FOUND, "client_error"),
        (grpc.StatusCode.ALREADY_EXISTS, "client_error"),
        (grpc.StatusCode.PERMISSION_DENIED, "client_error"),
        (grpc.StatusCode.UNAUTHENTICATED, "client_error"),
        (grpc.StatusCode.FAILED_PRECONDITION, "client_error"),
        (grpc.StatusCode.OUT_OF_RANGE, "client_error"),
        (grpc.StatusCode.DEADLINE_EXCEEDED, "unavailable"),
        (grpc.StatusCode.UNAVAILABLE, "unavailable"),
        (grpc.StatusCode.ABORTED, "unavailable"),
        (grpc.StatusCode.CANCELLED, "server_error"),
        (grpc.StatusCode.UNKNOWN, "server_error"),
        (grpc.StatusCode.UNIMPLEMENTED, "server_error"),
        (grpc.StatusCode.INTERNAL, "server_error"),
        (grpc.StatusCode.DATA_LOSS, "server_error"),
    ],
)
def test_status_class(code, expected: str):
    assert status_class(code) == expected


def test_status_class_covers_every_code():
    """Every grpc.StatusCode must map to a known low-cardinality bucket."""
    valid = {"ok", "client_error", "resource_exhausted", "unavailable", "server_error", "error"}
    for code in grpc.StatusCode:
        assert status_class(code) in valid


def test_null_counter_is_no_op():
    c = _NullCounter()
    c.add(1)
    c.add(0, {"method": "/x/Y"})


def test_null_histogram_is_no_op():
    h = _NullHistogram()
    h.record(0)
    h.record(123, {"method": "/x/Y"})


def test_get_counter_outside_workflow_returns_null():
    counter = get_grpc_requests_counter(team_id=1, source_type="google_ads")
    counter.add(1, {"method": "/x/Y", "status_class": "ok"})


def test_get_histograms_outside_workflow_return_null():
    latency = get_grpc_latency_histogram(team_id=1, source_type="google_ads")
    bytes_ = get_grpc_response_bytes_histogram(team_id=1, source_type="google_ads")
    latency.record(123)
    bytes_.record(456)


def test_meter_attributes_include_team_and_source():
    captured: list[dict] = []

    class FakeMeter:
        def with_additional_attributes(self, attrs):
            captured.append(attrs)
            return self

        def create_counter(self, name, desc):
            return object()

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.metrics._safe_metric_meter",
        return_value=FakeMeter(),
    ):
        get_grpc_requests_counter(team_id=42, source_type="google_ads")

    assert captured == [{"team_id": "42", "source_type": "google_ads"}]


def test_get_counter_caches_per_team_and_source():
    creates: list[tuple[str, str]] = []

    class FakeMeter:
        def with_additional_attributes(self, attrs):
            return self

        def create_counter(self, name, desc):
            creates.append((name, desc))
            return object()

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.metrics._safe_metric_meter",
        return_value=FakeMeter(),
    ):
        first = get_grpc_requests_counter(team_id=42, source_type="google_ads")
        second = get_grpc_requests_counter(team_id=42, source_type="google_ads")
        third = get_grpc_requests_counter(team_id=42, source_type="bigquery")

    assert first is second
    assert first is not third
    assert len(creates) == 2


def test_get_histogram_caches_per_team_and_source():
    creates: list[tuple[str, str]] = []

    class FakeMeter:
        def with_additional_attributes(self, attrs):
            return self

        def create_histogram(self, name, desc, unit):
            creates.append((name, desc))
            return object()

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.metrics._safe_metric_meter",
        return_value=FakeMeter(),
    ):
        a = get_grpc_latency_histogram(team_id=1, source_type="google_ads")
        b = get_grpc_latency_histogram(team_id=1, source_type="google_ads")
        c = get_grpc_response_bytes_histogram(team_id=1, source_type="google_ads")
        d = get_grpc_response_bytes_histogram(team_id=1, source_type="google_ads")

    assert a is b
    assert c is d
    assert len(creates) == 2


def test_null_recorders_are_also_cached():
    first = get_grpc_requests_counter(team_id=1, source_type="google_ads")
    second = get_grpc_requests_counter(team_id=1, source_type="google_ads")
    assert first is second
