import json
from datetime import UTC, datetime

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.redis import get_client

from products.security.backend.logic import snapshot
from products.security.backend.logic.snapshot import (
    EMPTY_SNAPSHOT,
    Snapshot,
    current_snapshot,
    last_synced_at,
    mark_synced,
    reset_memo,
    stored_version,
    write_snapshot,
)

RULE = {
    "id": "r1",
    "targetType": "email",
    "targetValue": "x@example.com",
    "effect": "block",
    "scope": "signup",
    "expiresAt": None,
}


class TestSnapshot(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        reset_memo()

    def test_empty_until_written(self) -> None:
        assert current_snapshot().rule_count == 0
        assert stored_version() is None

    def test_write_counts_readable_rules_and_skips_the_rest(self) -> None:
        outcome = write_snapshot("v1", [RULE, "junk", {"id": "r2"}])
        assert (outcome.applied, outcome.rule_count) == (True, 1)
        assert stored_version() == "v1"
        assert current_snapshot().rule_count == 1

    def test_memo_rechecks_the_version_every_30_seconds(self) -> None:
        with time_machine.travel("2026-09-17T12:00:00Z", tick=False) as frozen:
            write_snapshot("v1", [RULE])
            assert current_snapshot().version == "v1"
            write_snapshot("v2", [RULE, {**RULE, "id": "r2"}])
            assert current_snapshot().version == "v1"
            frozen.shift(31)
            assert current_snapshot().version == "v2"
            assert current_snapshot().rule_count == 2

    def test_redis_errors_and_flushes_keep_the_memo(self) -> None:
        with time_machine.travel("2026-09-17T12:00:00Z", tick=False) as frozen:
            write_snapshot("v1", [RULE])
            assert current_snapshot().version == "v1"
            get_client().flushdb()
            frozen.shift(31)
            assert current_snapshot().version == "v1"
            frozen.shift(31)
            with patch.object(snapshot, "get_client", side_effect=ConnectionError("down")):
                assert current_snapshot().version == "v1"

    def test_last_synced_at_round_trip(self) -> None:
        assert last_synced_at() is None
        when = datetime(2026, 9, 17, 12, tzinfo=UTC)
        mark_synced(when)
        assert last_synced_at() == when

    def test_stored_payload_is_json(self) -> None:
        write_snapshot("v1", [RULE])
        raw = get_client().get(snapshot.SNAPSHOT_KEY)
        assert raw is not None
        payload = json.loads(raw)
        assert payload == {"version": "v1", "rules": [RULE]}

    def test_older_generated_at_does_not_clobber_the_newer_snapshot(self) -> None:
        write_snapshot("v1", [RULE], generated_at_ms=2000)
        # The dropped write parses a different rule count than the stored one, so this also
        # proves a dropped write's rule_count is None rather than the rejected value.
        outcome = write_snapshot("v0", [], generated_at_ms=1000)
        assert (outcome.applied, outcome.rule_count) == (False, None)
        assert stored_version() == "v1"
        assert current_snapshot().rule_count == 1

    def test_equal_generated_at_applies_idempotently(self) -> None:
        write_snapshot("v1", [RULE], generated_at_ms=2000)
        outcome = write_snapshot("v1", [RULE], generated_at_ms=2000)
        assert outcome.applied is True
        assert stored_version() == "v1"

    def test_flushed_generated_at_key_applies_the_next_write_regardless_of_its_value(self) -> None:
        write_snapshot("v1", [RULE], generated_at_ms=5000)
        get_client().delete(snapshot.GENERATED_AT_KEY)
        outcome = write_snapshot("v2", [RULE], generated_at_ms=1000)
        assert outcome.applied is True
        assert stored_version() == "v2"

    def test_slow_refresh_does_not_clobber_a_memo_another_thread_already_installed(self) -> None:
        with time_machine.travel("2026-09-17T12:00:00Z", tick=False) as frozen:
            write_snapshot("v1", [RULE])
            assert current_snapshot().version == "v1"
            frozen.shift(31)

            concurrent_memo = Snapshot(version="v2", index=EMPTY_SNAPSHOT.index, rule_count=9)

            def install_concurrent_memo(*args: object, **kwargs: object) -> None:
                snapshot._memo = concurrent_memo

            with patch.object(snapshot, "last_synced_at", side_effect=install_concurrent_memo):
                result = current_snapshot()

            assert result is concurrent_memo
            assert snapshot._memo is concurrent_memo
