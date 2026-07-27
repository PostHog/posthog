"""Wire schema for flags_cache_invalidation Kafka messages.

Producer: Django signal handlers in products/feature_flags/backend/flags_cache.py.
Consumer: rust/feature-flags flags-cache-builder.

The fixture at rust/feature-flags/tests/fixtures/flags_cache_invalidation_v1.json
is the contract. The Python side round-trips against it in
products/feature_flags/backend/test/test_flags_cache_messages.py. The Rust consumer
(PR 2) will round-trip against the same fixture so schema drift fails the build
on either side. Bumping `version` requires running both producers (old + new)
and both consumers (old + new) in parallel during the migration — do not bump
it without a written rollout plan.
"""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict


class FlagsCacheInvalidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    team_id: int
    operation: Literal["invalidate"] = "invalidate"
    # AwareDatetime rejects naive datetimes — the wire contract is UTC and the
    # Rust consumer expects a timezone offset.
    emitted_at: AwareDatetime
