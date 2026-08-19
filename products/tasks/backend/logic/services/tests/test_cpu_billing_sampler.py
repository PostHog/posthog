from products.tasks.backend.sandbox.images.cpu_billing_sampler import billed_interval_usec


def test_billed_interval_uses_request_floor() -> None:
    assert billed_interval_usec(0.5, 1_000_000, 1_100_000, 1_000_000_000, 3_000_000_000) == 1_000_000


def test_billed_interval_uses_actual_cpu() -> None:
    assert billed_interval_usec(0.5, 1_000_000, 2_500_000, 1_000_000_000, 3_000_000_000) == 1_500_000
