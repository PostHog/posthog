import pytest


class FakePhClient:
    """In-memory stand-in for the real PostHog client used by `ph_scoped_capture`.

    Collects every `capture(...)` kwargs dict into `self.captured` so tests can
    assert on events without hitting the network. `shutdown` is a no-op so the
    `with ph_scoped_capture()` context manager exits cleanly.
    """

    def __init__(self) -> None:
        self.captured: list[dict] = []

    def capture(self, **kwargs) -> None:
        self.captured.append(kwargs)

    def shutdown(self) -> None:
        pass


@pytest.fixture
def fake_ph_client(monkeypatch) -> FakePhClient:
    """Mock the two seams (`is_cloud` + `get_client`) that gate `ph_scoped_capture`."""
    client = FakePhClient()
    monkeypatch.setattr("posthog.ph_client.is_cloud", lambda: True)
    monkeypatch.setattr("posthog.ph_client.get_client", lambda *a, **kw: client)
    return client
