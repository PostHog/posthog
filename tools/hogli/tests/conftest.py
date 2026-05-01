"""Shared test fixtures for hogli framework tests."""

import pytest

from hogli import telemetry


@pytest.fixture(autouse=True)
def _clear_telemetry_queue():
    with telemetry._client._lock:
        telemetry._client._queue.clear()
    yield
    with telemetry._client._lock:
        telemetry._client._queue.clear()
