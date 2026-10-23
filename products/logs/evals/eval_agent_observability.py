from __future__ import annotations

import json
import uuid
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.clickhouse.client import sync_execute

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

RUN_ID = "run-7f3a9c"
NEW_ERROR = "card vault handshake timed out"
SILENT = "ledger-sync"

REQUEST_ID = "req-4b81e2"
REQUEST_ERROR = "reservation rejected: sku locked"
DEPLOY_VERSION = "2.4.1"
DEPLOY_ERROR = "refund rejected: idempotency key missing"
SLOW_ROUTE = "/api/search"
FAILING_REGION = "ap-southeast-2"
REGION_ERROR = "tax quote unavailable"


def _row(team_id: int, at: datetime, service: str, body: str, severity: str = "info", **attributes: str) -> dict:
    stamp = at.strftime("%Y-%m-%d %H:%M:%S.%f")
    return {
        "team_id": team_id,
        "uuid": str(uuid.uuid4()),
        "timestamp": stamp,
        "observed_timestamp": stamp,
        "body": body,
        "severity_text": severity,
        "service_name": service,
        "attributes_map_str": {f"{key}__str": value for key, value in attributes.items()},
    }


def _insert(rows: list[dict]) -> None:
    sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "".join(json.dumps(row) + "\n" for row in rows))


def seed_observability_logs(context: CustomPromptSandboxContext) -> dict[str, Any]:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    spike_start = now - timedelta(minutes=40)

    def log(at: datetime, service: str, body: str, severity: str = "info", **attributes: str) -> dict:
        return _row(context.team_id, at, service, body, severity, **attributes)

    rows = [log(now - timedelta(minutes=m), "checkout", f"order {m} placed") for m in range(0, 24 * 60, 10)]
    rows += [log(now - timedelta(days=1, minutes=m), SILENT, "ledger batch synced") for m in range(0, 600, 10)]
    rows += [log(spike_start + timedelta(seconds=s), "checkout", NEW_ERROR, "error") for s in range(0, 2400, 5)]
    rows += [
        log(now - timedelta(hours=2, seconds=s), service, body, severity, workflow_run_id=RUN_ID)
        for s, service, body, severity in (
            (60, "scheduler", "run queued", "info"),
            (50, "worker", "step upload started", "info"),
            (20, "worker", "step upload failed: quota exceeded", "error"),
        )
    ]
    _insert(rows)
    return {"spike_hhmm": spike_start.strftime("%H:%M")}


def seed_incident_logs(context: CustomPromptSandboxContext) -> dict[str, Any]:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    deploy_at = now - timedelta(minutes=90)
    rng = random.Random(7)

    def log(at: datetime, service: str, body: str, severity: str = "info", **attributes: str) -> dict:
        return _row(context.team_id, at, service, body, severity, **attributes)

    rows: list[dict] = []
    for step in range(0, 6 * 3600, 15):
        at = now - timedelta(seconds=step)
        recent = step < 3600
        for service in ("api", "inventory"):
            rows.append(log(at, service, "request handled", request_id=f"req-{rng.getrandbits(24):06x}"))
        for route in (SLOW_ROUTE, "/api/suggest"):
            millis = rng.randint(800, 1200) if recent and route == SLOW_ROUTE else rng.randint(30, 90)
            rows.append(log(at, "search", f"GET {route} completed", route=route, duration_ms=str(millis)))
        version = DEPLOY_VERSION if at >= deploy_at else "2.4.0"
        if version == DEPLOY_VERSION and step % 45 == 0:
            rows.append(log(at, "payments", DEPLOY_ERROR, "error", version=version))
        else:
            rows.append(log(at, "payments", "refund processed", version=version))
        region = ("us-east-1", "eu-west-1", FAILING_REGION)[step // 15 % 3]
        if region == FAILING_REGION and step < 2 * 3600:
            rows.append(log(at, "billing", REGION_ERROR, "error", region=region))
        else:
            rows.append(log(at, "billing", "invoice finalized", region=region))

    failed_at = now - timedelta(minutes=75)
    rows += [
        log(failed_at + timedelta(milliseconds=ms), service, body, severity, request_id=REQUEST_ID)
        for ms, service, body, severity in (
            (0, "api", "POST /api/orders received", "info"),
            (40, "inventory", REQUEST_ERROR, "error"),
            (55, "api", "POST /api/orders failed with status 409", "warn"),
        )
    ]
    _insert(rows)
    return {}


class AnswerMentions(Scorer):
    def _name(self) -> str:
        return "answer_mentions"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        parser = LogParser.cached(output["raw_log"]) if output and output.get("raw_log") else None
        message = ((parser.get_final_agent_message() if parser else None) or "").lower()
        seed = (output or {}).get("seed") or {}
        expected_terms = (expected or {}).get(self._name()) or []
        terms = [str(seed.get(term[5:], term)) if term.startswith("seed:") else term for term in expected_terms]
        found = [term for term in terms if term.lower() in message]
        return Score(name=self._name(), score=len(found) / len(terms) if terms else None, metadata={"found": found})


class CallBudget(Scorer):
    def _name(self) -> str:
        return "call_budget"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        budget = (expected or {}).get(self._name())
        if not budget or not output or not output.get("raw_log"):
            return Score(name=self._name(), score=None if not budget else 0.0)
        calls = sum(1 for call in LogParser.cached(output["raw_log"]).get_tool_calls() if not call.is_error)
        return Score(name=self._name(), score=min(1.0, budget / max(calls, 1)), metadata={"calls": calls})


CASES = [
    ("daily_health", "Write a health report of my services for the last 24h of logs.", ["checkout", SILENT], 4),
    ("silent_service", "Did a service stop sending logs in the last 24h, compared with the day before?", [SILENT], 2),
    ("new_error_pattern", "Which error messages are new in the logs in the last 24h?", [NEW_ERROR, "checkout"], 2),
    ("logs_for_one_run", f"Workflow run {RUN_ID} failed about 2h ago. What happened?", ["quota exceeded", "worker"], 3),
    ("spike_onset", "Checkout errors spiked in the last 2h. When did the spike start, in UTC?", ["seed:spike_hhmm"], 3),
]

INCIDENT_CASES = [
    (
        "request_trace",
        f"A customer says request {REQUEST_ID} failed about an hour ago. Which service caused it and why?",
        ["inventory", "sku locked"],
        2,
    ),
    (
        "deploy_regression",
        "Did anything get worse after the most recent payments deploy? Name the version and what broke.",
        [DEPLOY_VERSION, "idempotency key"],
        4,
    ),
    (
        "latency_regression",
        "One route in the search service got slower in the last hour. Which route is it?",
        [SLOW_ROUTE],
        3,
    ),
    (
        "segmented_errors",
        "Billing errors went up in the last 2h. Is it every customer, or only some of them?",
        [FAILING_REGION, "tax quote"],
        4,
    ),
]


async def eval_agent_observability(ctx: EvalContext) -> None:
    await SandboxedPublicEval(
        experiment_name="sandboxed-logs-agent-observability-cli",
        cases=[
            SandboxedEvalCase(
                name=name,
                prompt=prompt,
                expected={"answer_mentions": terms, "call_budget": budget},
                setup=setup,
            )
            for cases, setup in ((CASES, seed_observability_logs), (INCIDENT_CASES, seed_incident_logs))
            for name, prompt, terms, budget in cases
        ],
        scorers=[AnswerMentions(), CallBudget()],
        ctx=ctx,
    )
