"""Temporary owner overrides of ranking serving and promotion, read from one feature flag payload.

An owner sets the `inbox-ranking-overrides` payload only to intervene, and every payload expires on
its own. The scoring sweep reads `served`, and the training dag reads `pin` and `promotion`. Both
parse the payload here, so the two cannot disagree about what a payload means.

The parser is fail-safe. An absent, expired or invalid payload, or a failed flag lookup, gives
`NO_OVERRIDES`, and the sweep and the dag then run as they do with no flag. An invalid payload is
ignored as a whole and is never partly applied.
"""

import re
import json
import datetime
from collections.abc import Mapping
from dataclasses import field
from typing import Any, Literal

import pydantic
import structlog
import posthoganalytics

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

RANKING_OVERRIDES_FLAG = "inbox-ranking-overrides"
# The flag is evaluated once per pass or run for this id, so an override applies to every report.
RANKING_OVERRIDES_DISTINCT_ID = "internal_inbox_ranking_overrides"

# A forgotten override must not change serving or promotion for longer than this.
MAX_OVERRIDE_LIFETIME = datetime.timedelta(days=14)

PromotionGate = Literal["min_days", "ece", "min_holdout_positives"]

# A model key is also a path segment in the dataset bucket, so the format is strict.
_MODEL_KEY_PATTERN = re.compile(r"^[a-z0-9_]+@\d{4}-\d{2}-\d{2}$")


class InvalidOverrides(ValueError):
    pass


class _PromotionPayload(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    freeze: list[str] = []
    force: list[str] = []
    skip_gates: dict[str, list[PromotionGate]] = {}


class _OverridesPayload(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    expires_at: pydantic.AwareDatetime
    served: str | None = None
    pin: list[str] = []
    promotion: _PromotionPayload = _PromotionPayload()

    @pydantic.field_validator("served")
    @classmethod
    def served_is_a_model_key(cls, v: str | None) -> str | None:
        if v is not None and not _MODEL_KEY_PATTERN.match(v):
            raise ValueError(f"{v!r} is not a `<model_name>@<YYYY-MM-DD>` model key")
        return v

    @pydantic.field_validator("pin")
    @classmethod
    def pins_are_model_keys(cls, v: list[str]) -> list[str]:
        for key in v:
            if not _MODEL_KEY_PATTERN.match(key):
                raise ValueError(f"{key!r} is not a `<model_name>@<YYYY-MM-DD>` model key")
        return v


@frozen
class PromotionOverride:
    """One family's promotion override. `freeze` wins, so a frozen family has no force and no waived gate."""

    freeze: bool = False
    force: bool = False
    skip_gates: frozenset[str] = frozenset()


@frozen
class RankingOverrides:
    # None only on `NO_OVERRIDES`.
    expires_at: datetime.datetime | None = None
    served: str | None = None
    pin: tuple[str, ...] = ()
    freeze: frozenset[str] = frozenset()
    force: frozenset[str] = frozenset()
    skip_gates: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def promotion_for(self, family: str) -> PromotionOverride:
        if family in self.freeze:
            return PromotionOverride(freeze=True)
        return PromotionOverride(force=family in self.force, skip_gates=self.skip_gates.get(family, frozenset()))


NO_OVERRIDES = RankingOverrides()


def _validated(payload: Mapping[str, Any], now: datetime.datetime) -> RankingOverrides:
    try:
        parsed = _OverridesPayload.model_validate(payload)
    except pydantic.ValidationError as error:
        raise InvalidOverrides(str(error)) from error
    if parsed.expires_at > now + MAX_OVERRIDE_LIFETIME:
        raise InvalidOverrides(f"expires_at {parsed.expires_at.isoformat()} is more than 14 days ahead")
    return RankingOverrides(
        expires_at=parsed.expires_at,
        served=parsed.served,
        pin=tuple(dict.fromkeys(parsed.pin)),
        freeze=frozenset(parsed.promotion.freeze),
        force=frozenset(parsed.promotion.force),
        skip_gates={family: frozenset(gates) for family, gates in parsed.promotion.skip_gates.items()},
    )


def parse_overrides(payload: Any, *, now: datetime.datetime) -> RankingOverrides:
    """The overrides a payload sets, or `NO_OVERRIDES` when it is empty, expired or invalid."""
    if payload is None or payload == {}:
        return NO_OVERRIDES
    if not isinstance(payload, Mapping):
        logger.warning("inbox_ranking_override_invalid", reason="the payload is not a JSON object")
        return NO_OVERRIDES
    try:
        overrides = _validated(payload, now)
    except InvalidOverrides as error:
        logger.warning("inbox_ranking_override_invalid", reason=str(error))
        return NO_OVERRIDES
    if overrides.expires_at is not None and overrides.expires_at <= now:
        logger.warning("inbox_ranking_override_expired", expires_at=overrides.expires_at.isoformat())
        return NO_OVERRIDES
    return overrides


def read_ranking_overrides(now: datetime.datetime) -> RankingOverrides:
    """The current overrides. Blocks on the flag lookup, so call it off the event loop.

    The flag is evaluated, not only its payload read, so a disabled flag sets no override.
    """
    try:
        payload = posthoganalytics.get_feature_flag_payload(RANKING_OVERRIDES_FLAG, RANKING_OVERRIDES_DISTINCT_ID)
    except Exception as error:
        logger.warning("inbox_ranking_override_lookup_failed", error=repr(error))
        return NO_OVERRIDES
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            logger.warning("inbox_ranking_override_invalid", reason="the payload is not valid JSON")
            return NO_OVERRIDES
    return parse_overrides(payload, now=now)
