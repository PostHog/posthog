import time
from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.redis import get_client

from products.replay_vision.backend.enqueue_claims import (
    _RELEASE_GRACE_SECONDS,
    _scanner_key,
    _team_key,
    pending_enqueue_claims_for_scanner,
    pending_enqueue_claims_for_team,
    release_enqueue_claim,
    try_claim_enqueue_slot,
)


class TestEnqueueClaims(SimpleTestCase):
    def setUp(self) -> None:
        self.team_id = 990_001
        self.scanner_id = uuid4()
        self._flush()
        self.addCleanup(self._flush)

    def _flush(self) -> None:
        get_client().delete(_team_key(self.team_id), _scanner_key(self.scanner_id))

    def _claim(self, workflow_id: str, *, team_rows: int = 0, scanner_rows: int = 0) -> bool:
        return try_claim_enqueue_slot(
            team_id=self.team_id,
            scanner_id=self.scanner_id,
            workflow_id=workflow_id,
            team_in_flight_rows=team_rows,
            scanner_in_flight_rows=scanner_rows,
        )

    @parameterized.expand(
        [
            ("team_cap_binds", "MAX_IN_FLIGHT_APPLIES_PER_TEAM"),
            ("scanner_cap_binds", "MAX_IN_FLIGHT_APPLIES_PER_SCANNER"),
        ]
    )
    def test_claims_beyond_the_allowance_are_rejected(self, _name: str, cap_constant: str) -> None:
        # A read-then-write regression would admit both concurrent callers.
        with patch(f"products.replay_vision.backend.enqueue_claims.{cap_constant}", 1):
            assert self._claim("wf-1") is True
            assert self._claim("wf-2") is False

    def test_rows_count_against_the_allowance(self) -> None:
        # Persisted in-flight rows consume cap headroom before any claims do.
        with patch("products.replay_vision.backend.enqueue_claims.MAX_IN_FLIGHT_APPLIES_PER_TEAM", 2):
            assert self._claim("wf-1", team_rows=2) is False

    def test_reclaiming_the_same_workflow_id_consumes_no_new_slot(self) -> None:
        # Duplicate requests and retries re-claim the same member; consuming a slot would starve headroom.
        with patch("products.replay_vision.backend.enqueue_claims.MAX_IN_FLIGHT_APPLIES_PER_TEAM", 1):
            assert self._claim("wf-1") is True
            assert self._claim("wf-1") is True
            assert self._claim("wf-2") is False

    def test_release_decays_the_claim_instead_of_deleting_it(self) -> None:
        # Deleting on release would reopen the stale-row-count race; the slot frees after the grace.
        with patch("products.replay_vision.backend.enqueue_claims.MAX_IN_FLIGHT_APPLIES_PER_TEAM", 1):
            assert self._claim("wf-1") is True
            release_enqueue_claim(team_id=self.team_id, scanner_id=self.scanner_id, workflow_id="wf-1")
            assert self._claim("wf-2") is False
            with patch(
                "products.replay_vision.backend.enqueue_claims.time.time",
                return_value=time.time() + _RELEASE_GRACE_SECONDS + 1,
            ):
                assert self._claim("wf-2") is True

    def test_expired_claims_are_evicted_and_do_not_count(self) -> None:
        # The TTL score is the crash net: a claim whose workflow died must not hold its slot forever.
        client = get_client()
        client.zadd(_team_key(self.team_id), {"wf-dead": time.time() - 1})
        client.zadd(_scanner_key(self.scanner_id), {"wf-dead": time.time() - 1})
        with patch("products.replay_vision.backend.enqueue_claims.MAX_IN_FLIGHT_APPLIES_PER_TEAM", 1):
            assert self._claim("wf-live") is True
        assert pending_enqueue_claims_for_team(self.team_id) == 1
        assert pending_enqueue_claims_for_scanner(self.scanner_id) == 1

    def test_fails_open_when_redis_is_unavailable(self) -> None:
        # The caps are backstops, not billing: a Redis outage must never block scans.
        with patch("products.replay_vision.backend.enqueue_claims.redis.get_client", side_effect=RuntimeError("down")):
            assert self._claim("wf-1") is True
            release_enqueue_claim(team_id=self.team_id, scanner_id=self.scanner_id, workflow_id="wf-1")
            assert pending_enqueue_claims_for_team(self.team_id) == 0
