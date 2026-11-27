"""End-to-end routing for a Slack `@PostHog` mention: does the cascade, then the needs-repo
classifier, then the discovery agent stop at the right stage with the right outcome?

Each case gets an isolated team with the synthetic `fernhill` catalog and the case's routing
rules, so no case depends on a real team's connected repositories. The classifier runs its
production model through the eval AI gateway. The selector runs on the harness's
`--agent-runtime`/`--agent-model`; compare selector models with `tasks/eval_repo_selection`,
which holds the classifier out of the measurement.

    hogli evals slack_app/eval_repo_selection_routing --agent-model claude-sonnet-5-5
    hogli evals slack_app/eval_repo_selection_routing --eval explicit_mention
"""

from __future__ import annotations

import time
import asyncio
from collections.abc import Awaitable, Callable

from posthog.egress.limiter.policies import Priority

from products.posthog_ai.eval_harness.base import SandboxedEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.providers import SandboxProviderStrategy
from products.posthog_ai.eval_harness.runner import EvalCaseResult
from products.slack_app.backend.services.slack_messages import SlackThreadMessage
from products.slack_app.backend.task_profiles import REPO_SELECTION
from products.slack_app.backend.temporal.activities.classifiers import (
    CLASSIFIER_MODEL,
    classify_task_needs_repo,
    team_routing_rule_lines,
)
from products.slack_app.backend.temporal.activities.repo_selection import _resolve_explicit_repo
from products.slack_app.evals.offline_config import offline_suite
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, TurnPollTimeout
from products.tasks.evals.repo_selection.fixtures import (
    FIXTURE_VERSION,
    REPOSITORY_NAMES,
    ROUTING_CASES,
    RepoSelectionScenario,
    fixture_fingerprint,
)
from products.tasks.evals.repo_selection.runner import RepoSelectionArtifacts, run_selector
from products.tasks.evals.repo_selection.scorers import ROUTING_SCORERS, routing_expected
from products.tasks.evals.repo_selection.seeders import scenario_seeder

EXPERIMENT_NAME = "slack-repo-selection-routing"

_SCENARIOS: dict[str, RepoSelectionScenario] = {case.scenario.name: case.scenario for case in ROUTING_CASES}


def _thread(scenario: RepoSelectionScenario) -> list[SlackThreadMessage]:
    return [SlackThreadMessage(user=message.user, text=message.text) for message in scenario.thread]


def _classify(scenario: RepoSelectionScenario, team_id: int) -> bool:
    candidates = {repo.lower() for repo in REPOSITORY_NAMES}
    return classify_task_needs_repo(
        scenario.mention_text,
        _thread(scenario),
        routing_rules=team_routing_rule_lines(team_id, candidate_repos=candidates),
        team_id=team_id,
    )


async def run_routing_case(
    case: SandboxedEvalCase,
    context: CustomPromptSandboxContext,
    *,
    provider: SandboxProviderStrategy,
    on_cleanup: Callable[[], Awaitable[None]] | None = None,
    timeout_seconds: float | None = None,
    on_poll_timeout: Callable[[TurnPollTimeout], None] | None = None,
) -> EvalCaseResult:
    scenario = _SCENARIOS[case.name]
    started = time.monotonic()
    artifacts = RepoSelectionArtifacts(exit_code=0, stage="cascade")

    # The production cascade's explicit-mention tiers, with the mention and the thread around it.
    cascade = _resolve_explicit_repo(
        scenario.mention_text, _thread(scenario), [repo.lower() for repo in REPOSITORY_NAMES]
    )
    artifacts.cascade_reason = cascade.reason
    if cascade.mode == "auto":
        artifacts.outcome, artifacts.selected_repository = "auto", cascade.repository
        artifacts.duration_seconds = time.monotonic() - started
        return EvalCaseResult(artifacts=artifacts)

    artifacts.stage = "classifier"
    needs_repo = await asyncio.to_thread(_classify, scenario, context.team_id)
    artifacts.classifier_needs_repo = needs_repo
    if not needs_repo:
        artifacts.outcome = "no_repo"
        artifacts.duration_seconds = time.monotonic() - started
        return EvalCaseResult(artifacts=artifacts)

    artifacts.stage = "selector"
    remaining = None if timeout_seconds is None else timeout_seconds - (time.monotonic() - started)
    return await run_selector(
        scenario,
        context,
        profile=REPO_SELECTION,
        # A person waits in the Slack thread for the answer.
        priority=Priority.NORMAL,
        provider=provider,
        on_cleanup=on_cleanup,
        timeout_seconds=remaining,
        artifacts=artifacts,
    )


async def eval_repo_selection_routing(ctx: EvalContext) -> None:
    await SandboxedEval(
        offline_suite=offline_suite(
            "slack_app/eval_repo_selection_routing::eval_repo_selection_routing",
            metrics=[scorer()._name() for scorer in ROUTING_SCORERS],
        ),
        send_to_posthog=True,
        experiment_name=EXPERIMENT_NAME,
        cases=[
            SandboxedEvalCase(
                name=case.scenario.name,
                prompt=case.scenario.context_block,
                setup=scenario_seeder(case.scenario),
                expected=routing_expected(case.expected),
                metadata={
                    "expected_stage": case.expected.stage,
                    "classifier_model": CLASSIFIER_MODEL,
                    "fixture_version": FIXTURE_VERSION,
                    "fixture_fingerprint": fixture_fingerprint(),
                    "note": case.note,
                },
                inherit_demo_data=False,
            )
            for case in ROUTING_CASES
        ],
        scorers=[scorer() for scorer in ROUTING_SCORERS],
        case_runner=run_routing_case,
        ctx=ctx,
    )
