"""Which review engine a run uses, chosen per pull request by the ``stamphog-engine-channel`` flag.

The flag is evaluated with ``<owner>/<name>#<number>`` as the distinct id, so every run of one PR lands
in the same variant. Anything other than a known variant, an absent flag and a failed evaluation
included, falls back to the stable engine: a flag outage must never move a review onto the beta.
"""

from __future__ import annotations

from enum import StrEnum

import structlog

from posthog.ph_client import get_feature_flag_or_none

logger = structlog.get_logger(__name__)

ENGINE_CHANNEL_FLAG = "stamphog-engine-channel"


class EngineChannel(StrEnum):
    STABLE = "stable"
    BETA_SHADOW = "beta-shadow"
    BETA_LIVE = "beta-live"


def engine_channel_distinct_id(repository: str, pr_number: int) -> str:
    return f"{repository}#{pr_number}"


def parse_engine_channel(value: object) -> EngineChannel:
    """The channel a stored or evaluated value names, or stable for anything unknown."""
    if isinstance(value, str) and value in EngineChannel:
        return EngineChannel(value)
    return EngineChannel.STABLE


def evaluate_engine_channel(*, repository: str, pr_number: int, run_id: str) -> EngineChannel:
    # get_feature_flag_or_none catches and logs evaluation errors, and returns None for them.
    variant = get_feature_flag_or_none(ENGINE_CHANNEL_FLAG, engine_channel_distinct_id(repository, pr_number))
    channel = parse_engine_channel(variant)
    # None and False mean the flag is absent or did not match this PR, which is the normal stable case.
    if variant not in (None, False) and channel != variant:
        logger.warning("stamphog_unknown_engine_channel", run_id=run_id, variant=str(variant))
    return channel
