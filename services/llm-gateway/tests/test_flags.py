from unittest.mock import MagicMock, patch

import pytest

from llm_gateway import flags


@pytest.fixture(autouse=True)
def clear_flag_caches() -> None:
    flags._flag_cache.clear()
    flags._flag_unavailable_cache.clear()


@pytest.mark.parametrize("enabled", [True, False])
async def test_evaluate_flag_caches_definitive_answers(enabled: bool) -> None:
    # Both definitive answers must cache — False (flag disabled) is the normal rollout state, and
    # caching only True would re-hit /flags on every GLM request while the ramp is off.
    client = MagicMock()
    client.feature_enabled.return_value = enabled
    with patch("llm_gateway.flags._get_client", return_value=client):
        assert await flags.evaluate_flag("some-flag", "user-a") is enabled
        assert await flags.evaluate_flag("some-flag", "user-a") is enabled
    # One roundtrip per (flag, user) within the TTL — flag checks sit on the GLM hot path.
    assert client.feature_enabled.call_count == 1
    # sync_mode would otherwise block each uncached evaluation on a $feature_flag_called upload.
    assert client.feature_enabled.call_args.kwargs["send_feature_flag_events"] is False


@pytest.mark.parametrize("failure_mode", ["sdk_error", "sdk_none"])
async def test_evaluate_flag_backs_off_globally_when_unavailable(failure_mode: str) -> None:
    # An outage (exception) and an SDK None result (flag missing / evaluation unavailable) hit the
    # backoff independently; neither must stack one blocking roundtrip per new user — after the
    # first miss everyone gets the fallback answer until the backoff expires.
    client = MagicMock()
    if failure_mode == "sdk_error":
        client.feature_enabled.side_effect = RuntimeError("posthog down")
    else:
        client.feature_enabled.return_value = None
    with patch("llm_gateway.flags._get_client", return_value=client):
        assert await flags.evaluate_flag("some-flag", "user-a") is None
        assert await flags.evaluate_flag("some-flag", "user-b") is None
    assert client.feature_enabled.call_count == 1
