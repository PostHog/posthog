import time

from prometheus_client import Gauge

from posthog.metrics import pushed_metrics_registry

from products.replay_vision.backend.temporal.jev_watch_rank.constants import JUDGE_TOKENS_PER_SECOND, SWEEP_TIME_BUDGET
from products.replay_vision.backend.temporal.jev_watch_rank.types import JevWatchRankSweepResult


def push_sweep_metrics(result: JevWatchRankSweepResult) -> None:
    # Each worker can run the singleton sweep, so replace one regional snapshot instead of retaining per-worker gauges.
    with pushed_metrics_registry("replay_vision_jev_watch_rank_sweep") as registry:
        values = {
            "last_run_timestamp_seconds": (time.time(), "Unix time the last sweep returned"),
            "duration_seconds": (result.duration_seconds, "Duration of the last sweep"),
            "estimated_prompt_tokens": (
                result.estimated_prompt_tokens,
                "Estimated prompt tokens attempted in judgment and reason requests; excludes unsent pacing reservations",
            ),
            "token_budget": (
                JUDGE_TOKENS_PER_SECOND * SWEEP_TIME_BUDGET.total_seconds(),
                "Nominal estimated token envelope; request latency and backoff reduce the achievable work",
            ),
            "teams_evaluated": (result.teams_evaluated, "Teams whose ranking flag was evaluated in the last sweep"),
            "teams_enrolled": (result.teams_enrolled, "Teams enrolled with AI consent in the last sweep"),
            "teams_without_consent": (result.teams_without_consent, "Enrolled teams skipped without AI consent"),
            "scanners_seen": (result.scanners_seen, "Scanner turns queued in the last sweep"),
            "scanners_inspected": (result.scanners_inspected, "Scanner windows whose pending work was inspected"),
            "scanners_window_capped": (result.scanners_window_capped, "Scanner windows at the row limit"),
            "pending_observations": (
                result.pending_observations,
                "Unjudged rows remaining in inspected bounded windows; a lower bound unless backlog_complete is one",
            ),
            "oldest_pending_age_seconds": (
                result.oldest_pending_age_seconds,
                "Age of the oldest pending row in inspected bounded windows at inspection time",
            ),
            "backlog_complete": (result.backlog_complete, "One when every enrolled scanner window was fully inspected"),
            "observations_judged": (result.observations_judged, "Observations judged in the last sweep"),
            "observations_given_up": (
                result.observations_given_up,
                "Observations abandoned after repeated batch faults",
            ),
            "cache_errors": (result.cache_errors, "Cache failures in the last sweep"),
            "failed_chunks": (result.failed_chunks, "Failed judgment requests in the last sweep"),
            "failed_reason_chunks": (result.failed_reason_chunks, "Failed reason requests in the last sweep"),
            "scanners_rate_limited": (result.scanners_rate_limited, "Scanner turns with a rate-limited request"),
            "scanners_backed_off": (result.scanners_backed_off, "Scanner turns skipped after repeated rate limits"),
            "hit_time_budget": (result.hit_time_budget, "One when the last sweep reached its time limit"),
            "hit_team_cap": (result.hit_team_cap, "One when the last sweep reached its team limit"),
            "hit_scanner_cap": (result.hit_scanner_cap, "One when the last sweep reached its scanner limit"),
            "decisions_unavailable": (result.decisions_unavailable, "One when the decision service was unavailable"),
        }
        for name, (value, help_text) in values.items():
            Gauge(f"replay_vision_jev_watch_rank_sweep_{name}", help_text, registry=registry).set(value)
