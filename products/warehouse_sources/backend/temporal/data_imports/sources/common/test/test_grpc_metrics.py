import pytest

import grpc

from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.metrics import status_class


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
