import pytest

from kev_vllm.pending import PendingRequests


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_an_entry_nobody_takes_expires_when_a_later_request_arrives() -> None:
    clock = Clock()
    pending = PendingRequests[str](max_age_seconds=300, clock=clock)
    pending.put("rejected-with-503", "left behind")
    clock.now = 301.0
    pending.put("served", "answer")
    with pytest.raises(ValueError, match="expired"):
        pending.take("rejected-with-503")
    assert pending.take("served") == "answer"


def test_a_reused_id_never_hands_out_an_expired_entry() -> None:
    clock = Clock()
    pending = PendingRequests[str](max_age_seconds=300, clock=clock)
    pending.put("a", "stale")
    clock.now = 299.0
    pending.put("a", "fresh")
    clock.now = 302.0
    assert pending.take("a") == "fresh"
    with pytest.raises(ValueError, match="expired"):
        pending.take("a")
