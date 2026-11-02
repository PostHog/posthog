import json

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

REMOTE_CONFIG_KEY = "error-tracking-grouping-judge"
REMOTE_CONFIG_DISTINCT_ID = "error_tracking_grouping_judge"


@frozen
class JudgeConfig:
    sample_rate: float = 0.0
    # Empty means every team.
    team_ids: frozenset[int] = frozenset()

    def is_enabled_for(self, team_id: int) -> bool:
        return self.sample_rate > 0 and (not self.team_ids or team_id in self.team_ids)


JUDGE_OFF = JudgeConfig()


def parse_judge_config(payload: object, region: str | None) -> JudgeConfig:
    """Read this region's entry, e.g. `{"EU": {"sample_rate": 0.01, "team_ids": []}}`.

    Team ids repeat across regions, so each region has its own entry. Anything missing or malformed is off.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return JUDGE_OFF
    if not isinstance(payload, dict) or region is None:
        return JUDGE_OFF
    entry = payload.get(region)
    if not isinstance(entry, dict):
        return JUDGE_OFF
    sample_rate = entry.get("sample_rate", 0)
    team_ids = entry.get("team_ids", [])
    if (
        isinstance(sample_rate, bool)
        or not isinstance(sample_rate, int | float)
        or not 0 <= sample_rate <= 1
        or not isinstance(team_ids, list)
        or not all(isinstance(team_id, int) and not isinstance(team_id, bool) for team_id in team_ids)
    ):
        logger.warning("error_tracking.grouping_judge.invalid_remote_config", region=region)
        return JUDGE_OFF
    return JudgeConfig(sample_rate=float(sample_rate), team_ids=frozenset(team_ids))


def current_judge_config() -> JudgeConfig:
    # Reads the payload from the locally evaluated flag definitions, so the merge activity makes no network call.
    # A missing or disabled flag returns None, which turns the judge off.
    try:
        # With no definitions loaded, the SDK loads them with a blocking network call even for a
        # local-only read, so the judge stays off until the background poller loads them.
        if posthoganalytics.feature_flag_definitions() is None:
            return JUDGE_OFF
        payload = posthoganalytics.get_feature_flag_payload(
            REMOTE_CONFIG_KEY, REMOTE_CONFIG_DISTINCT_ID, only_evaluate_locally=True, send_feature_flag_events=False
        )
    except Exception:
        logger.exception("error_tracking.grouping_judge.remote_config_failed")
        return JUDGE_OFF
    return parse_judge_config(payload, get_instance_region())
