import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from unittest.mock import patch

import fakeredis
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import REGISTRY

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


@contextmanager
def _rebuilds(error=None, skip_write=False, load_error=None):
    """Patch the batch DB-load + cache-write seam so rebuilds succeed (error=None) or
    fail with the given exception, without touching the DB or the real caches.
    `skip_write=True` makes the group-mapping-emptied guard veto every write.
    `load_error` makes the batch DB load raise (simulating a DB/query failure)."""

    def _load(teams):
        if load_error is not None:
            raise load_error
        return {t.id: {} for t in teams}

    with (
        patch.object(rebuild_queue, "Team") as team,
        patch.object(rebuild_queue, "_skip_write_if_group_mapping_emptied", return_value=skip_write),
        patch.object(rebuild_queue.flag_definitions_hypercache, "batch_load_fn", new=_load),
        patch.object(rebuild_queue.flag_definitions_hypercache, "set_cache_value", side_effect=error) as set_cache,
    ):
        team.objects.filter.side_effect = lambda id__in: [SimpleNamespace(id=int(t)) for t in id__in]
        yield set_cache


def _enqueue(client, team_id, score=0):
    client.zadd(REBUILD_REQUESTS_ZSET, {str(team_id): score})


def test_drain_rebuilds_queued_team_and_clears_it(fake_redis):
    _enqueue(fake_redis, 140414)
    with _rebuilds():
        stats = drain_rebuild_requests()

    assert stats["success"] == 1
    assert fake_redis.zcard(REBUILD_REQUESTS_ZSET) == 0


def test_invalid_member_is_discarded_without_rebuild(fake_redis):
    fake_redis.zadd(REBUILD_REQUESTS_ZSET, {"not-an-int": 0})
    with _rebuilds():
        stats = drain_rebuild_requests()

    assert fake_redis.zcard(REBUILD_REQUESTS_ZSET) == 0
    assert stats == {"success": 0, "failure": 0, "skipped_cooldown": 0, "circuit_open": 0}


def test_cooldown_prevents_a_second_rebuild_within_the_window(fake_redis):
    with _rebuilds():
        _enqueue(fake_redis, 1)
        first = drain_rebuild_requests()
        assert first["success"] == 1

        # Team is still missing, so its next miss re-enqueues it before the cooldown lapses.
        _enqueue(fake_redis, 1)
        stats = drain_rebuild_requests()

    assert stats["skipped_cooldown"] == 1
    assert stats["success"] == 0  # not retried during cooldown


def test_circuit_opens_after_repeated_failures_then_skips(fake_redis):
    team_id = 7
    with _rebuilds(error=Exception("boom")):
        for _ in range(CIRCUIT_OPEN_THRESHOLD):
            _enqueue(fake_redis, team_id)
            drain_rebuild_requests()
            # Simulate the per-team cooldown lapsing before the next miss re-enqueues.
            fake_redis.delete(COOLDOWN_KEY.format(team_id=team_id))

        # Circuit is now open: a further request is skipped instead of rebuilt again.
        _enqueue(fake_redis, team_id)
        stats = drain_rebuild_requests()

    assert stats["circuit_open"] == 1
    assert fake_redis.zscore(CIRCUIT_ZSET, str(team_id)) is not None


def test_successful_rebuild_after_circuit_expiry_clears_streak_and_circuit(fake_redis):
    team_id = 9
    with _rebuilds(error=Exception("boom")):
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
    with _rebuilds():
        stats = drain_rebuild_requests()

    assert stats["success"] == 1
    # The success path clears both the failure streak and any circuit membership.
    assert fake_redis.get(FAILURE_STREAK_KEY.format(team_id=team_id)) is None
    assert fake_redis.zscore(CIRCUIT_ZSET, str(team_id)) is None


def test_rebuild_exception_is_caught_and_counts_as_failure(fake_redis):
    _enqueue(fake_redis, 5)
    with _rebuilds(error=Exception("db error")):
        stats = drain_rebuild_requests()

    # A raised rebuild must be caught (not abort the whole drain) and counted as a failure
    # that advances the streak.
    assert stats["failure"] == 1
    assert fake_redis.get(FAILURE_STREAK_KEY.format(team_id=5)) == b"1"


def test_batch_load_failure_counts_every_team_as_failure(fake_redis):
    for team_id in (11, 12, 13):
        _enqueue(fake_redis, team_id)
    with _rebuilds(load_error=Exception("db down")):
        stats = drain_rebuild_requests()

    # If the batched DB load raises, the whole batch is recorded as failures (so a
    # persistent outage trips circuits normally instead of silently dropping teams).
    assert stats["failure"] == 3
    for team_id in (11, 12, 13):
        assert fake_redis.get(FAILURE_STREAK_KEY.format(team_id=team_id)) == b"1"


def test_group_mapping_guard_skips_write_without_counting_failure(fake_redis):
    _enqueue(fake_redis, 8)
    with _rebuilds(skip_write=True) as set_cache:
        stats = drain_rebuild_requests()

    # The guard vetoed the write (e.g. personhog lag would empty group_type_mapping):
    # no cache write, and neither success nor failure — so it can't trip the circuit.
    set_cache.assert_not_called()
    assert stats["success"] == 0 and stats["failure"] == 0
    assert fake_redis.get(FAILURE_STREAK_KEY.format(team_id=8)) is None
    # Cooldown released so the team retries next drain once the mapping is available.
    assert not fake_redis.exists(COOLDOWN_KEY.format(team_id=8))


def test_soft_time_limit_propagates_and_is_not_counted_as_failure(fake_redis):
    _enqueue(fake_redis, 3)
    with _rebuilds(error=SoftTimeLimitExceeded()):
        # The soft limit must wind the task down, not be swallowed as a team failure.
        with pytest.raises(SoftTimeLimitExceeded):
            drain_rebuild_requests()

    assert fake_redis.get(FAILURE_STREAK_KEY.format(team_id=3)) is None
    # Cooldown released on wind-down so the next drain retries promptly (~1 min).
    assert not fake_redis.exists(COOLDOWN_KEY.format(team_id=3))


def test_gauges_reflect_queue_and_circuit_state(fake_redis):
    # Oldest pending team enqueued ~3s ago (score is epoch millis); guards the /1000.0
    # ms→s conversion, which every other test leaves untested by enqueuing score=0.
    _enqueue(fake_redis, 42, score=(time.time() - 3.0) * 1000.0)
    # A team with an open (future-scored) circuit feeds the dead-letter gauge.
    fake_redis.zadd(CIRCUIT_ZSET, {"99": time.time() + 3600})

    with _rebuilds():
        drain_rebuild_requests()

    age = REGISTRY.get_sample_value("posthog_flag_definitions_rebuild_oldest_age_seconds")
    dead = REGISTRY.get_sample_value("posthog_flag_definitions_rebuild_dead_letter_teams")
    assert age is not None and 2.0 <= age <= 30.0
    assert dead == 1.0


def test_request_zset_key_matches_rust_contract():
    # Tripwire for the hand-synced cross-language key: a Python-side rename trips here
    # and prompts updating FLAG_DEFINITIONS_REBUILD_REQUESTS_ZSET in the Rust service.
    assert REBUILD_REQUESTS_ZSET == "flag_definitions:rebuild_requests"
