import time
from collections.abc import Generator
from typing import SupportsIndex

import pytest

_real_sleep = time.sleep


def _capped_sleep(seconds: SupportsIndex | float, /) -> None:
    _real_sleep(min(float(seconds), 0.001))


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
