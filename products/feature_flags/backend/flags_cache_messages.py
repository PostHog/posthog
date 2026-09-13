"""Wire schema for flags_cache_invalidation Kafka messages.

Producer: Django signal handlers in products/feature_flags/backend/flags_cache.py.
Consumer: rust/feature-flags flags-cache-builder.

The fixture at rust/feature-flags/tests/fixtures/flags_cache_invalidation_v1.json
is the contract. The Python side round-trips against it in
products/feature_flags/backend/test/test_flags_cache_messages.py. The Rust consumer
round-trips against the same fixture so schema drift fails the build on either
side. Bumping `version` requires running both producers (old + new) and both
consumers (old + new) in parallel during the migration — do not bump it without
a written rollout plan.

The optional ``shadow: bool`` field (fixture:
flags_cache_invalidation_v1_shadow.json) marks a parity-telemetry message. On
``shadow: true`` the Rust consumer builds the team's payload but never writes
the cache, and diffs the build against the live entry instead. Django produces
these for teams the Celery builder still owns, behind the shadow gate in
flags_cache.py. ``shadow=False`` is omitted from the wire, so a real
invalidation stays byte-identical to v1 and any consumer that predates the
field can still read it.
"""

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, SerializerFunctionWrapHandler, StrictBool, model_serializer


class FlagsCacheInvalidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    team_id: int
    operation: Literal["invalidate"] = "invalidate"
    # AwareDatetime rejects naive datetimes — the wire contract is UTC and the
    # Rust consumer expects a timezone offset.
    emitted_at: AwareDatetime
    # StrictBool, not bool: pydantic's lax mode reads `1` as True, and the Rust
    # consumer rejects a non-bool `shadow`. Both sides must reject the same
    # payloads, because this field decides whether a build writes the cache.
    shadow: StrictBool = False

    @model_serializer(mode="wrap")
    def _omit_default_shadow(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Pydantic has no per-field `skip_serializing_if`, so the omission lives on
        # the model to cover every dump rather than one call site.
        data = handler(self)
        if not self.shadow:
            data.pop("shadow", None)
        return data
