import time
from collections.abc import Generator
from typing import SupportsIndex

import pytest

from posthog.conftest import *  # noqa: F401, F403  # the fixtures products/conftest.py gives the vendors in the product

from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import isolated_job_context

_real_sleep = time.sleep


def _capped_sleep(seconds: SupportsIndex | float, /) -> None:
    _real_sleep(min(float(seconds), 0.001))


@pytest.fixture(autouse=True)
def _isolate_job_context() -> Generator[None]:
    with isolated_job_context():
        yield


@pytest.fixture(autouse=True)
def _cap_backoff_sleeps() -> Generator[None]:
    """Cap time.sleep so retry/backoff waits don't run at real duration.

    Nearly every source wraps its HTTP calls in tenacity retries (or hand-rolled
    loops) with multi-second exponential backoff, and time.sleep is the only wait
    primitive they use. Tests that exercise those retry paths otherwise spend real
    minutes asleep. Capping (rather than fully no-oping) keeps sleep()-based thread
    yields working. Tests that patch time.sleep themselves are unaffected: their
    patch layers over this one and restores it on exit.

    A plain attribute swap rather than mock.patch: this runs for every test in the
    sources tree, and MagicMock construction is measurable at that volume.
    """
    time.sleep = _capped_sleep  # ty: ignore[invalid-assignment]
    try:
        yield
    finally:
        time.sleep = _real_sleep
