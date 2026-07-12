import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _no_error_tracking_capture():
    # ProcessTaskError.__init__ calls capture_exception on construction, so any test that
    # raises a sandbox/snapshot error would otherwise ship its fake exception to production
    # error tracking whenever an api_key is configured (e.g. in CI). Stub it out for the whole
    # package. Tests asserting on capture behavior patch this same target locally, which nests
    # cleanly over the stub.
    with patch("products.tasks.backend.exceptions.capture_exception"):
        yield
