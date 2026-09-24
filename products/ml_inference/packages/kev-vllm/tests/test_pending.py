import pytest

from kev_vllm.pending import PendingRequests


def test_an_entry_nobody_takes_expires_when_a_later_request_arrives():
    now = 0.0
    pending = PendingRequests[str](max_age_seconds=300, clock=lambda: now)
    pending.put("rejected-with-503", "left behind")
    now = 301.0
    pending.put("served", "answer")
    with pytest.raises(ValueError, match="expired"):
        pending.take("rejected-with-503")
    assert pending.take("served") == "answer"
