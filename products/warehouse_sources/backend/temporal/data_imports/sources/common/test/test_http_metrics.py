import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.metrics import status_class


@pytest.mark.parametrize(
    "code,expected",
    [
        (None, "error"),
        (199, "other"),
        (200, "2xx"),
        (204, "2xx"),
        (299, "2xx"),
        (300, "3xx"),
        (399, "3xx"),
        (400, "4xx"),
        (404, "4xx"),
        (429, "4xx"),
        (499, "4xx"),
        (500, "5xx"),
        (599, "5xx"),
        (600, "other"),
        (700, "other"),
    ],
)
def test_status_class(code: int | None, expected: str):
    assert status_class(code) == expected
