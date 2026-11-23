"""Temporary owner overrides of ranking serving, read from one feature flag payload.

An owner sets the `inbox-ranking-overrides` payload only to intervene, and every payload expires on
its own. The scoring sweep reads `served`, and the training dag reads `pin` and
`hold_auto_promotion`. Both parse the payload here, so the two cannot disagree about what a payload
means. Promotion is not an override: the daily serving publish and `inbox_ranking_promote_job` write
the served pointer, and `hold_auto_promotion` only stops the publish from moving it.

The parser is fail-safe. An absent, expired or invalid payload, or a failed flag lookup, gives
`NO_OVERRIDES`, and the sweep and the dag then run as they do with no flag. An invalid payload is
ignored as a whole and is never partly applied.

The automatic promotion interval is not an override either, because it stays in place with no
expiry. The training dag reads it from the `inbox-ranking-auto-promotion` flag payload through
`read_auto_promotion_interval`, which falls back to `INBOX_RANKING_AUTO_PROMOTE_INTERVAL_DAYS` on
the same fail-safe terms.
"""

import re
import json
import datetime
from collections.abc import Mapping
from typing import Annotated, Any, Literal

import pydantic
import structlog
import posthoganalytics

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

RANKING_OVERRIDES_FLAG = "inbox-ranking-overrides"
AUTO_PROMOTION_FLAG = "inbox-ranking-auto-promotion"
# Both flags are evaluated once per pass or run for this id, so a value applies to every report.
RANKING_OVERRIDES_DISTINCT_ID = "internal_inbox_ranking_overrides"

# A forgotten override must not change serving for longer than this.
MAX_OVERRIDE_LIFETIME = datetime.timedelta(days=14)

# A model key is also a path segment in the dataset bucket, so the format is strict.
MODEL_KEY_PATTERN = re.compile(r"^[a-z0-9_]+@\d{4}-\d{2}-\d{2}$")


class InvalidOverrides(ValueError):
    pass


class _OverridesPayload(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    expires_at: pydantic.AwareDatetime
    served: str | None = None
    pin: list[str] = []
    hold_auto_promotion: bool = False

    @pydantic.field_validator("served")
    @classmethod
    def served_is_a_model_key(cls, v: str | None) -> str | None:
        if v is not None and not MODEL_KEY_PATTERN.match(v):
            raise ValueError(f"{v!r} is not a `<model_name>@<YYYY-MM-DD>` model key")
        return v

    @pydantic.field_validator("pin")
    @classmethod
    def pins_are_model_keys(cls, v: list[str]) -> list[str]:
        for key in v:
            if not MODEL_KEY_PATTERN.match(key):
                raise ValueError(f"{key!r} is not a `<model_name>@<YYYY-MM-DD>` model key")
        return v


@frozen
class RankingOverrides:
    # None only on `NO_OVERRIDES`.
    expires_at: datetime.datetime | None = None
    served: str | None = None
    pin: tuple[str, ...] = ()
    hold_auto_promotion: bool = False


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
        hold_auto_promotion=parsed.hold_auto_promotion,
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


class _AutoPromotionPayload(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    # Strict, so that `true` or `"3"` is refused and not read as 1 or 3.
    interval_days: Annotated[int, pydantic.Field(strict=True, ge=0)]


@frozen
class AutoPromotionInterval:
    days: int
    source: Literal["flag", "setting"]


def parse_auto_promotion_interval(payload: Any) -> int | None:
    """The `interval_days` a payload sets, or None when it is empty or invalid."""
    if payload is None or payload == {}:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            logger.warning("inbox_ranking_auto_promotion_invalid", reason="the payload is not valid JSON")
            return None
    if not isinstance(payload, Mapping):
        logger.warning("inbox_ranking_auto_promotion_invalid", reason="the payload is not a JSON object")
        return None
    try:
        return _AutoPromotionPayload.model_validate(payload).interval_days
    except pydantic.ValidationError as error:
        logger.warning("inbox_ranking_auto_promotion_invalid", reason=str(error))
        return None


def read_auto_promotion_interval(setting_days: int) -> AutoPromotionInterval:
    """The interval the automatic promotion step waits, from the flag payload or else `setting_days`.

    Blocks on the flag lookup. A disabled flag, an invalid payload or a failed lookup gives the
    setting, so the step never runs on a value nobody set.
    """
    try:
        payload = posthoganalytics.get_feature_flag_payload(AUTO_PROMOTION_FLAG, RANKING_OVERRIDES_DISTINCT_ID)
    except Exception as error:
        logger.warning("inbox_ranking_auto_promotion_lookup_failed", error=repr(error))
        payload = None
    days = parse_auto_promotion_interval(payload)
    if days is None:
        return AutoPromotionInterval(days=setting_days, source="setting")
    return AutoPromotionInterval(days=days, source="flag")
