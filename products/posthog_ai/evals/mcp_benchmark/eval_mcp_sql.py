"""One-shot SQL suite ported from the MCP agent-experience benchmark.

The reference one-shot suite: each case is one Anthropic generation that must
produce a single HogQL query (forced through an ``execute_sql`` tool schema),
which is then executed in-process via ``execute_hogql_query`` against the
master Hedgebox team — no sandbox, no MCP server. The benchmark intents use
relative ranges ("last 7 days", "this month"), which hold on Hedgebox's ~120
days of seeded events.

To run:
    hogli evals:sandboxed mcp_benchmark
"""

from __future__ import annotations

import os
import json
import asyncio
from typing import Any

from anthropic import AsyncAnthropic

from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval
from products.posthog_ai.evals.mcp_benchmark.cases import load_benchmark_cases
from products.posthog_ai.evals.mcp_benchmark.scorers import QueryExecutes, SuccessCriteria

SUITE_KIND = SuiteKind.ONE_SHOT

MAX_OUTPUT_ROWS = 50

SYSTEM_PROMPT = (
    "You are a PostHog analytics agent. Answer the user's question by producing exactly one HogQL query "
    "via the execute_sql tool. HogQL is PostHog's ClickHouse-derived SQL dialect: events live in the `events` "
    "table with `event`, `timestamp`, `properties.*` (JSON access via dots), and `person_id`. Use relative "
    "time predicates like `timestamp > now() - INTERVAL 7 DAY`. Call the tool once with your best query."
)

EXECUTE_SQL_TOOL = {
    "name": "execute_sql",
    "description": "Run one HogQL (ClickHouse-flavored) SQL query against the project's analytics data.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "The HogQL query to run."}},
        "required": ["query"],
    },
}


def _run_query(team_id: int, query: str) -> dict[str, Any]:
    """Execute the generated HogQL against the master demo team. Sync — call via ``asyncio.to_thread``."""
    team = Team.objects.get(id=team_id)
    try:
        response = execute_hogql_query(query, team)
    except Exception as exc:
        return {"results": [], "columns": [], "error": str(exc)}
    # Normalize to JSON-safe values: the output dict round-trips through Braintrust.
    results = json.loads(json.dumps((response.results or [])[:MAX_OUTPUT_ROWS], default=str))
    columns = json.loads(json.dumps(response.columns or [], default=str))
    return {"results": results, "columns": columns, "error": str(response.error) if response.error else ""}


async def _generate_and_execute(client: AsyncAnthropic, case: BaseEvalCase, ctx: EvalContext) -> dict[str, Any]:
    message = await client.messages.create(
        model=ctx.agent_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": case.prompt}],
        tools=[EXECUTE_SQL_TOOL],  # type: ignore[arg-type]
        tool_choice={"type": "tool", "name": "execute_sql"},
    )
    query = next(
        (
            block.input.get("query")
            for block in message.content
            if block.type == "tool_use" and isinstance(block.input, dict)
        ),
        None,
    )
    output: dict[str, Any] = {
        "prompt": case.prompt,
        "query": query or "",
        "results": [],
        "columns": [],
        "error": "",
        "stop_reason": message.stop_reason,
    }
    if not isinstance(query, str) or not query.strip():
        output["error"] = "model produced no execute_sql call"
        output["last_message"] = output["error"]
        return output

    assert ctx.demo_data is not None  # guaranteed by SuiteKind.ONE_SHOT's DEMO_DATA requirement
    output.update(await asyncio.to_thread(_run_query, ctx.demo_data.master_team_id, query))
    outcome = output["error"] or f"{len(output['results'])} row(s)"
    output["last_message"] = f"{query}\n\n-- {outcome}"
    return output


async def eval_mcp_sql(ctx: EvalContext) -> None:
    client = AsyncAnthropic(api_key=os.environ["LLM_GATEWAY_ANTHROPIC_API_KEY"])

    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict[str, Any]:
        return await _generate_and_execute(client, case, task_ctx)

    await OneShotPrivateEval(
        experiment_name="mcp-benchmark-sql",
        cases=load_benchmark_cases("sql"),
        scorers=[QueryExecutes(), SuccessCriteria()],
        task=task,
        ctx=ctx,
    )
