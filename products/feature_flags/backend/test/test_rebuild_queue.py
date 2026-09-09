import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

import fakeredis
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import REGISTRY

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS

from products.feature_flags.backend import rebuild_queue
from products.feature_flags.backend.local_evaluation import _build_flag_definitions_hypercache
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


DEDICATED_REDIS_URL = "redis://flags-dedicated:6379/"


@contextmanager
def _dedicated_cache(registered: bool) -> Iterator[None]:
    """Force the dedicated flags cache alias on or off, then rebuild the hypercache so the
    real cache_alias derivation runs rather than a patched URL. Both cases are pinned
    because FLAGS_REDIS_URL decides this and a developer's environment may set it while CI
    does not. Without the alias the hypercache URL collapses onto settings.REDIS_URL, which
    makes a split between the producer's cluster and the consumer's unrepresentable."""
    caches = {alias: cache for alias, cache in settings.CACHES.items() if alias != FLAGS_DEDICATED_CACHE_ALIAS}
    if registered:
        caches[FLAGS_DEDICATED_CACHE_ALIAS] = {**settings.CACHES["default"], "LOCATION": DEDICATED_REDIS_URL}
    with (
        override_settings(CACHES=caches),
        patch.object(rebuild_queue, "flag_definitions_hypercache", _build_flag_definitions_hypercache()),
    ):
        yield


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


def test_drain_reads_the_dedicated_cluster_and_ignores_the_shared_one():
    # Rust enqueues on the dedicated cluster whenever FLAGS_REDIS_URL is configured
    # (State::flags_namespace_redis_client), so a drain that reads the shared one finds an
    # empty set while misses pile up unseen.
    dedicated, shared = fakeredis.FakeRedis(), fakeredis.FakeRedis()
    clients = {DEDICATED_REDIS_URL: dedicated, settings.REDIS_URL: shared}

    with _dedicated_cache(registered=True):
        _enqueue(dedicated, 140414)
        _enqueue(shared, 999999)
        with (
            patch.object(rebuild_queue, "get_client", side_effect=lambda url: clients[url]),
            _rebuilds() as set_cache,
        ):
            stats = drain_rebuild_requests()

    assert stats["success"] == 1
    assert [call.args[0].id for call in set_cache.call_args_list] == [140414]
    assert dedicated.zcard(REBUILD_REQUESTS_ZSET) == 0
    assert shared.zrange(REBUILD_REQUESTS_ZSET, 0, -1) == [b"999999"]


def test_unread_cluster_gauge_reports_the_other_cluster_depth():
    # Every other gauge follows the cluster the drain resolved, so a producer and consumer
    # split reads zero on all of them. This one is the signal that the split happened, and
    # the one that shows the post-deploy cleanup worked.
    dedicated, shared = fakeredis.FakeRedis(), fakeredis.FakeRedis()
    clients = {DEDICATED_REDIS_URL: dedicated, settings.REDIS_URL: shared}

    with _dedicated_cache(registered=True):
        _enqueue(shared, 999999)
        _enqueue(shared, 999998)
        with (
            patch.object(rebuild_queue, "get_client", side_effect=lambda url: clients[url]),
            _rebuilds(),
        ):
            drain_rebuild_requests()

    assert REGISTRY.get_sample_value("posthog_flag_definitions_rebuild_unread_cluster_depth") == 2.0


def test_unread_cluster_gauge_is_zero_when_both_ends_agree():
    # Self-hosted resolves both ends to one cluster, where "the other cluster" does not
    # exist. The gauge must read 0 rather than repeat the live queue depth.
    with _dedicated_cache(registered=False):
        with patch.object(rebuild_queue, "get_client", return_value=fakeredis.FakeRedis()), _rebuilds():
            drain_rebuild_requests()

    assert REGISTRY.get_sample_value("posthog_flag_definitions_rebuild_unread_cluster_depth") == 0.0


def test_drain_falls_back_to_the_shared_cluster_without_the_alias():
    # Self-hosted installs leave FLAGS_REDIS_URL unset, so the alias never registers and
    # both ends stay on the shared cluster. A derivation that hardcodes the dedicated URL
    # points every self-hosted drain at a cluster that does not exist.
    with (
        _dedicated_cache(registered=False),
        patch.object(rebuild_queue, "get_client") as get_client_mock,
    ):
        rebuild_queue._redis()
    get_client_mock.assert_called_once_with(settings.REDIS_URL)
