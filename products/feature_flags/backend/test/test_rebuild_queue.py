import pytest
from unittest.mock import patch

import fakeredis
from celery.exceptions import SoftTimeLimitExceeded

from products.feature_flags.backend import rebuild_queue
from products.feature_flags.backend.rebuild_queue import (
    CIRCUIT_OPEN_THRESHOLD,
    CIRCUIT_ZSET,
    COOLDOWN_KEY,
    FAILURE_STREAK_KEY,
    REBUILD_REQUESTS_ZSET,
    drain_rebuild_requests,
)


@pytest.fixture
def fake_redis():
    client = fakeredis.FakeRedis()
    with patch.object(rebuild_queue, "get_client", return_value=client):
        yield client


def _enqueue(client, team_id, score=0):
    client.zadd(REBUILD_REQUESTS_ZSET, {str(team_id): score})


def test_drain_rebuilds_queued_team_and_clears_it(fake_redis):
    _enqueue(fake_redis, 140414)
    with patch.object(rebuild_queue, "update_flag_definitions_cache", return_value=True) as rebuild:
        stats = drain_rebuild_requests()

    rebuild.assert_called_once_with(140414)
    assert stats["success"] == 1
    assert fake_redis.zcard(REBUILD_REQUESTS_ZSET) == 0


def test_invalid_member_is_discarded_without_rebuild(fake_redis):
    fake_redis.zadd(REBUILD_REQUESTS_ZSET, {"not-an-int": 0})
    with patch.object(rebuild_queue, "update_flag_definitions_cache") as rebuild:
        stats = drain_rebuild_requests()

    rebuild.assert_not_called()
    assert fake_redis.zcard(REBUILD_REQUESTS_ZSET) == 0
    assert stats == {"success": 0, "failure": 0, "skipped_cooldown": 0, "circuit_open": 0}


def test_cooldown_prevents_a_second_rebuild_within_the_window(fake_redis):
    with patch.object(rebuild_queue, "update_flag_definitions_cache", return_value=True) as rebuild:
        _enqueue(fake_redis, 1)
        drain_rebuild_requests()
        assert rebuild.call_count == 1

        # Team is still missing, so its next miss re-enqueues it before the cooldown lapses.
        _enqueue(fake_redis, 1)
        stats = drain_rebuild_requests()

    assert stats["skipped_cooldown"] == 1
    assert rebuild.call_count == 1  # not retried during cooldown


def test_circuit_opens_after_repeated_failures_then_skips(fake_redis):
    team_id = 7
    with patch.object(rebuild_queue, "update_flag_definitions_cache", return_value=False) as rebuild:
        for _ in range(CIRCUIT_OPEN_THRESHOLD):
            _enqueue(fake_redis, team_id)
            drain_rebuild_requests()
            # Simulate the per-team cooldown lapsing before the next miss re-enqueues.
            fake_redis.delete(COOLDOWN_KEY.format(team_id=team_id))
        assert rebuild.call_count == CIRCUIT_OPEN_THRESHOLD

        # Circuit is now open: a further request is skipped instead of rebuilt again.
        _enqueue(fake_redis, team_id)
        stats = drain_rebuild_requests()

    assert stats["circuit_open"] == 1
    assert rebuild.call_count == CIRCUIT_OPEN_THRESHOLD
    assert fake_redis.zscore(CIRCUIT_ZSET, str(team_id)) is not None


def test_successful_rebuild_after_circuit_expiry_clears_streak_and_circuit(fake_redis):
    team_id = 9
    with patch.object(rebuild_queue, "update_flag_definitions_cache", return_value=False):
        for _ in range(CIRCUIT_OPEN_THRESHOLD):
            _enqueue(fake_redis, team_id)
            drain_rebuild_requests()
            fake_redis.delete(COOLDOWN_KEY.format(team_id=team_id))
    assert fake_redis.zscore(CIRCUIT_ZSET, str(team_id)) is not None
    assert fake_redis.get(FAILURE_STREAK_KEY.format(team_id=team_id)) is not None

    # Expire the circuit (score in the past) so the drain prunes it and retries, rather
    # than the test clearing it — otherwise this wouldn't exercise the success cleanup.
    fake_redis.zadd(CIRCUIT_ZSET, {str(team_id): 1.0})
    fake_redis.delete(COOLDOWN_KEY.format(team_id=team_id))
    _enqueue(fake_redis, team_id)
    with patch.object(rebuild_queue, "update_flag_definitions_cache", return_value=True) as rebuild:
        stats = drain_rebuild_requests()

    rebuild.assert_called_once_with(team_id)
    assert stats["success"] == 1
    # The success path clears both the failure streak and any circuit membership.
    assert fake_redis.get(FAILURE_STREAK_KEY.format(team_id=team_id)) is None
    assert fake_redis.zscore(CIRCUIT_ZSET, str(team_id)) is None


def test_rebuild_exception_is_caught_and_counts_as_failure(fake_redis):
    _enqueue(fake_redis, 5)
    with patch.object(rebuild_queue, "update_flag_definitions_cache", side_effect=Exception("db error")) as rebuild:
        stats = drain_rebuild_requests()

    # A raised rebuild must be caught (not abort the whole drain) and counted as a failure
    # that advances the streak — same path as a False return.
    rebuild.assert_called_once_with(5)
    assert stats["failure"] == 1
    assert fake_redis.get(FAILURE_STREAK_KEY.format(team_id=5)) == b"1"


def test_soft_time_limit_propagates_and_is_not_counted_as_failure(fake_redis):
    _enqueue(fake_redis, 3)
    with patch.object(rebuild_queue, "update_flag_definitions_cache", side_effect=SoftTimeLimitExceeded()):
        # The soft limit must wind the task down, not be swallowed as a team failure.
        with pytest.raises(SoftTimeLimitExceeded):
            drain_rebuild_requests()

    assert fake_redis.get(FAILURE_STREAK_KEY.format(team_id=3)) is None


def test_request_zset_key_matches_rust_contract():
    # Tripwire for the hand-synced cross-language key: a Python-side rename trips here
    # and prompts updating FLAG_DEFINITIONS_REBUILD_REQUESTS_ZSET in the Rust service.
    assert REBUILD_REQUESTS_ZSET == "flag_definitions:rebuild_requests"
