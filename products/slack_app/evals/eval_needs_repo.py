"""Which Slack mentions need the team's code, and which PostHog can answer without a repository?

Behind `slack-app-jev-needs-repo`, every mention from a person with a connected repository
reaches `classify_needs_repo_with_jev`, which asks Jev, a System One decision model, one
yes/no question. At or above `NEEDS_REPO_MIN_PROBABILITY` the run gets a repository.

A false yes clones a repository the run never reads. A false no starts the run without one,
and the agent clones mid-run, so tune the threshold toward no.

To run:
    hogli evals eval_needs_repo
    hogli evals eval_needs_repo --eval weekly_signups
"""

from __future__ import annotations

import asyncio

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotEval
from products.slack_app.backend.services.slack_messages import SlackThreadMessage
from products.slack_app.backend.temporal.activities import classifiers
from products.slack_app.evals.offline_config import offline_suite
from products.slack_app.evals.scorers import NEEDS_REPO_KEY, NeedsRepoMatch

SUITE_KIND = SuiteKind.ONE_SHOT


def _needs_repo(needs_repo: bool) -> dict:
    return {NEEDS_REPO_KEY: {"needs_repo": needs_repo}}


CODE_CASES = [
    BaseEvalCase(
        name="fix_upload_bug",
        prompt="the upload button does nothing on Safari, can you fix it and open a PR?",
        expected=_needs_repo(True),
    ),
    BaseEvalCase(
        name="where_event_is_sent",
        prompt="which file sends the shared_folder_created event?",
        expected=_needs_repo(True),
    ),
    BaseEvalCase(
        name="flaky_test",
        prompt="test_invite_flow keeps failing in CI, is it flaky or did someone break it?",
        expected=_needs_repo(True),
    ),
    BaseEvalCase(
        name="explain_code",
        prompt="how does our billing retry logic decide when to give up?",
        expected=_needs_repo(True),
    ),
    BaseEvalCase(
        name="add_tracking",
        prompt="add a tracking call when someone renames a folder",
        expected=_needs_repo(True),
    ),
    BaseEvalCase(
        name="review_pr",
        prompt="can you review https://github.com/example-org/web-app/pull/42 for me?",
        expected=_needs_repo(True),
    ),
    # Asks how the team's own system behaves without saying "code".
    BaseEvalCase(
        name="own_job_behavior",
        prompt="why does the export job retry three times before it fails?",
        expected=_needs_repo(True),
    ),
    # Asks to track something new without naming an API, which reads like a data request.
    BaseEvalCase(
        name="start_tracking",
        prompt="can we start tracking an event when someone invites a teammate?",
        expected=_needs_repo(True),
    ),
    BaseEvalCase(
        name="stop_tracking",
        prompt="stop sending the page_scrolled event, it's too noisy",
        expected=_needs_repo(True),
    ),
]

DATA_CASES = [
    BaseEvalCase(name="weekly_signups", prompt="how many people signed up last week?", expected=_needs_repo(False)),
    BaseEvalCase(
        name="funnel_drop",
        prompt="why did signup to first upload conversion drop yesterday?",
        expected=_needs_repo(False),
    ),
    BaseEvalCase(
        name="flag_rollout",
        prompt="is the new-onboarding flag rolled out to everyone yet?",
        expected=_needs_repo(False),
    ),
    BaseEvalCase(
        name="error_count",
        prompt="are there more errors on the file upload page since this morning?",
        expected=_needs_repo(False),
    ),
    BaseEvalCase(
        name="build_dashboard",
        prompt="make me a dashboard with WAU, retention and the activation funnel",
        expected=_needs_repo(False),
    ),
    BaseEvalCase(
        name="watch_replays",
        prompt="find a few recordings of people who gave up on checkout",
        expected=_needs_repo(False),
    ),
    BaseEvalCase(
        name="how_to_use_posthog",
        prompt="how do I set up a survey that only shows to paying users?",
        expected=_needs_repo(False),
    ),
    # Names a page of the team's app, but the answer is in error tracking.
    BaseEvalCase(
        name="errors_on_own_page",
        prompt="why does our checkout page throw so many errors today?",
        expected=_needs_repo(False),
    ),
    # Tracking that PostHog can set up without code.
    BaseEvalCase(
        name="track_without_code",
        prompt="can I track clicks on the pricing button without code, like with an action?",
        expected=_needs_repo(False),
    ),
    BaseEvalCase(name="thanks", prompt="thanks, that's perfect!", expected=_needs_repo(False)),
]


async def eval_needs_repo(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        model = classifiers.NEEDS_REPO_DECISION_MODEL
        if task_ctx.demo_data is None:
            return {"decision_model": model, "needs_repo": None, "error": "No demo data team to bill the call to"}
        try:
            # Sync and blocking on the gateway, so off the event loop.
            verdict = await asyncio.to_thread(
                classifiers.classify_needs_repo_with_jev,
                case.prompt,
                [SlackThreadMessage(user="U1", text=case.prompt)],
                routing_rules=[],
                team_id=task_ctx.demo_data.master_team_id,
                distinct_id=None,
            )
        except Exception as error:
            return {"decision_model": model, "needs_repo": None, "error": f"{type(error).__name__}: {error}"}
        return {
            "decision_model": model,
            "needs_repo": verdict.needs_repo,
            "probability": verdict.probability,
            "last_message": f"{model}: needs_repo={verdict.needs_repo} ({verdict.probability:.2f})",
        }

    await OneShotEval(
        experiment_name="slack-app-needs-repo",
        offline_suite=offline_suite(
            "slack_app/eval_needs_repo::eval_needs_repo",
            metrics=[NEEDS_REPO_KEY],
            suite_kind=SUITE_KIND,
        ),
        cases=[*CODE_CASES, *DATA_CASES],
        scorers=[NeedsRepoMatch()],
        task=task,
        ctx=ctx,
    )
