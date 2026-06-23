import pytest
from unittest.mock import patch

from products.signals.backend.quota import is_team_signals_quota_limited


@pytest.mark.parametrize(
    ("limited", "expected"),
    [
        (True, True),
        (False, False),
    ],
)
def test_reflects_quota_limiter(limited, expected):
    with patch("products.signals.backend.quota.is_team_limited", return_value=limited) as mock_limited:
        assert is_team_signals_quota_limited("phc_token") is expected
    # Always queries the signals_credits resource for the given token.
    args = mock_limited.call_args.args
    assert args[0] == "phc_token"
    assert args[1].value == "signals_credits"


def test_fails_open_on_error():
    with patch("products.signals.backend.quota.is_team_limited", side_effect=RuntimeError("redis down")):
        assert is_team_signals_quota_limited("phc_token") is False
