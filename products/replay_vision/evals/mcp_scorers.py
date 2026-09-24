"""Deterministic scorers for the Replay Vision MCP tool-use suite."""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser, ToolCall
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer


def _calls(output: dict | None) -> list[ToolCall] | None:
    if not output or not output.get("raw_log"):
        return None
    return LogParser.cached(output["raw_log"], initial_prompt=output.get("prompt", "") or "").get_tool_calls()


def _seed(output: dict | None) -> dict[str, Any]:
    return (output or {}).get("seed") or {}


class CreatedMatchAlertWithWebhook(Scorer):
    """A match alert on the seeded scanner for verdict yes, then a webhook destination on that alert."""

    def _name(self) -> str:
        return "created_match_alert_with_webhook"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if not expected or self._name() not in expected:
            return Score(name=self._name(), score=None, metadata={"reason": "Not expected for this case"})
        calls = _calls(output)
        if calls is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        scanner_id = _seed(output).get("scanner_id")
        webhook_url = expected[self._name()]["webhook_url"]

        alert_created = any(
            c.name == "vision-alerts-create"
            and not c.is_error
            and c.input.get("scanner_id") == scanner_id
            and c.input.get("kind") == "match"
            and "yes" in ((c.input.get("selection") or {}).get("verdict") or [])
            for c in calls
        )
        destination_added = any(
            c.name == "vision-alerts-destinations-create"
            and not c.is_error
            and c.input.get("type") == "webhook"
            and c.input.get("webhook_url") == webhook_url
            for c in calls
        )
        score = (int(alert_created) + int(destination_added)) / 2
        return Score(
            name=self._name(),
            score=score,
            metadata={"alert_created": alert_created, "destination_added": destination_added},
        )


class EstimatedBeforeBackfill(Scorer):
    """An estimate, and no backfill create unless an estimate came first and its cap was passed."""

    def _name(self) -> str:
        return "estimated_before_backfill"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if not expected or self._name() not in expected:
            return Score(name=self._name(), score=None, metadata={"reason": "Not expected for this case"})
        calls = _calls(output)
        if calls is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        estimates = [c for c in calls if c.name == "vision-scanners-backfills-estimate"]
        creates = [c for c in calls if c.name == "vision-scanners-backfills-create"]
        if not estimates:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Never estimated"})
        first_estimate = min(c.position for c in estimates)
        blind = [c.call_id for c in creates if c.position < first_estimate or "max_total_credits" not in c.input]
        return Score(
            name=self._name(),
            score=0.0 if blind else 1.0,
            metadata={"estimates": len(estimates), "creates": len(creates), "blind_creates": blind},
        )


class RetriedFailedObservation(Scorer):
    """The seeded failed observation was retried by its own id, not the session or scanner id."""

    def _name(self) -> str:
        return "retried_failed_observation"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if not expected or self._name() not in expected:
            return Score(name=self._name(), score=None, metadata={"reason": "Not expected for this case"})
        calls = _calls(output)
        if calls is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        target = _seed(output).get("failed_observation_id")
        retries = [c for c in calls if c.name == "vision-observations-retry"]
        hit = [c for c in retries if str(c.input.get("id")) == target]
        return Score(
            name=self._name(),
            score=1.0 if hit else 0.0,
            # The retry itself needs Temporal; the call's error flag is reported, not scored.
            metadata={"retries": len(retries), "targeted": len(hit), "errored": [c.is_error for c in hit]},
        )
