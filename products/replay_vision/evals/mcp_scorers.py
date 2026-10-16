"""Deterministic scorers for the Replay Vision MCP tool-use suite."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer


class _McpToolScorer(Scorer):
    """Skips cases that don't expect this scorer and fails runs with no log, then defers to `_score`."""

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if not expected or self._name() not in expected:
            return Score(name=self._name(), score=None, metadata={"reason": "Not expected for this case"})
        if not output or not output.get("raw_log"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        parser = LogParser.cached(output["raw_log"], initial_prompt=output.get("prompt", "") or "")
        return self._score(parser, output.get("seed") or {}, expected[self._name()])

    def _score(self, parser: LogParser, seed: dict[str, Any], expected: dict[str, Any]) -> Score:
        raise NotImplementedError


class CreatedMatchAlertWithWebhook(_McpToolScorer):
    """A match alert on the seeded scanner for verdict yes, then a webhook destination on that alert."""

    def _name(self) -> str:
        return "created_match_alert_with_webhook"

    def _score(self, parser: LogParser, seed: dict[str, Any], expected: dict[str, Any]) -> Score:
        alert_created = any(
            not c.is_error
            and c.input.get("scanner_id") == seed.get("scanner_id")
            and c.input.get("kind") == "match"
            and "yes" in ((c.input.get("selection") or {}).get("verdict") or [])
            for c in parser.get_tool_calls("vision-alerts-create")
        )
        destination_added = any(
            not c.is_error
            and c.input.get("type") == "webhook"
            and c.input.get("webhook_url") == expected["webhook_url"]
            for c in parser.get_tool_calls("vision-alerts-destinations-create")
        )
        return Score(
            name=self._name(),
            score=(int(alert_created) + int(destination_added)) / 2,
            metadata={"alert_created": alert_created, "destination_added": destination_added},
        )


def _spans_about_a_week(call_input: dict[str, Any]) -> bool:
    try:
        start = datetime.fromisoformat(str(call_input["window_start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(call_input["window_end"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return False
    # A day of slack either way, since the agent picks its own clock and rounding.
    return timedelta(days=6) <= end - start <= timedelta(days=8)


class EstimatedBeforeBackfill(_McpToolScorer):
    """A successful estimate and no backfill create.

    Nobody in the sandbox can agree to the quoted cost, and the tool requires that agreement first, so the
    right move is to estimate and stop to ask.
    """

    def _name(self) -> str:
        return "estimated_before_backfill"

    def _score(self, parser: LogParser, seed: dict[str, Any], expected: dict[str, Any]) -> Score:
        estimates = [
            c
            for c in parser.get_tool_calls("vision-scanners-backfills-estimate")
            if not c.is_error and _spans_about_a_week(c.input)
        ]
        creates = [c.call_id for c in parser.get_tool_calls("vision-scanners-backfills-create")]
        if not estimates:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No successful estimate over the last week"})
        return Score(
            name=self._name(),
            score=0.0 if creates else 1.0,
            metadata={"estimates": len(estimates), "unagreed_creates": creates},
        )


class RetriedFailedObservation(_McpToolScorer):
    """The seeded failed observation was retried by its own id, not the session or scanner id."""

    def _name(self) -> str:
        return "retried_failed_observation"

    def _score(self, parser: LogParser, seed: dict[str, Any], expected: dict[str, Any]) -> Score:
        retries = parser.get_tool_calls("vision-observations-retry")
        hit = [c for c in retries if not c.is_error and str(c.input.get("id")) == seed.get("failed_observation_id")]
        return Score(
            name=self._name(),
            score=1.0 if hit else 0.0,
            metadata={"retries": len(retries), "succeeded_on_target": len(hit)},
        )
