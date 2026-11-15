import pytest

# The suite lives outside a test module, where pytest does not show the two sides of a failed assert.
pytest.register_assert_rewrite(f"{__name__}.conformance_suite")
