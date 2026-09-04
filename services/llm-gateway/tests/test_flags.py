from unittest.mock import MagicMock, patch

import pytest

from llm_gateway import flags


@pytest.fixture(autouse=True)
def clear_flag_caches() -> None:
    flags._flag_cache.clear()
    flags._flag_unavailable_cache.clear()


def flag_snapshot(values: dict[str, bool]) -> MagicMock:
    snapshot = MagicMock()
    snapshot.keys = list(values)
    snapshot.is_enabled.side_effect = values.__getitem__
    return snapshot


@pytest.mark.parametrize("enabled", [True, False])
async def test_evaluate_flag_caches_definitive_answers(enabled: bool) -> None:
    # Both definitive answers must cache — False (flag disabled) is the normal rollout state, and
    # caching only True would re-hit /flags on every GLM request while the ramp is off.
    client = MagicMock()
    client.evaluate_flags.return_value = flag_snapshot({"some-flag": enabled})
    with patch("llm_gateway.flags._get_client", return_value=client):
        assert await flags.evaluate_flag("some-flag", "user-a") is enabled
        assert await flags.evaluate_flag("some-flag", "user-a") is enabled
    # One roundtrip per (flag, user) within the TTL — flag checks sit on the GLM hot path.
    assert client.evaluate_flags.call_count == 1


async def test_evaluate_flags_batches_uncached_keys() -> None:
    client = MagicMock()
    client.evaluate_flags.return_value = flag_snapshot({"flag-a": True, "flag-b": False})

    with patch("llm_gateway.flags._get_client", return_value=client):
        assert await flags.evaluate_flags(["flag-a", "flag-b"], "user-a") == {
            "flag-a": True,
            "flag-b": False,
        }

    client.evaluate_flags.assert_called_once_with("user-a", flag_keys=["flag-a", "flag-b"])


@pytest.mark.parametrize("failure_mode", ["sdk_error", "sdk_none"])
async def test_evaluate_flag_backs_off_globally_when_unavailable(failure_mode: str) -> None:
    # An outage (exception) and an SDK None result (flag missing / evaluation unavailable) hit the
    # backoff independently; neither must stack one blocking roundtrip per new user — after the
    # first miss everyone gets the fallback answer until the backoff expires.
    client = MagicMock()
    if failure_mode == "sdk_error":
        client.evaluate_flags.side_effect = RuntimeError("posthog down")
    else:
        client.evaluate_flags.return_value = flag_snapshot({})
    with patch("llm_gateway.flags._get_client", return_value=client):
        assert await flags.evaluate_flag("some-flag", "user-a") is None
        assert await flags.evaluate_flag("some-flag", "user-b") is None
    assert client.evaluate_flags.call_count == 1
