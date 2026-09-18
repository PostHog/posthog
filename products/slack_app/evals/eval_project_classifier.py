"""Does the project classifier pick the project a person in the thread would have?

A Slack workspace connected to several PostHog projects answers every mention from one
saved default, so a question about another project is answered from the wrong data. The
classifier reads the project out of the message that opens a thread. The unit tests around
`classify_slack_app_project_route` cover parsing and the schema; this suite covers the only
part they can't, which is whether the model can tell "answer this from staging" from a
sentence that merely says the word.

A missed project falls back to the default, which is today's behavior, and the author
rephrases. An invented project answers a different question in a shape that reads like an
answer to this one. `NoUnaskedProjectSwitch` is therefore the number to watch, not the
overall rate.

The projects below are invented, and the phrasings with them. No customer's project names
or messages appear here.

Every case is held out of the prompt on purpose. An earlier revision paraphrased the
prompt's own few-shot examples, which measures whether the model repeats them rather than
whether it reads an unseen sentence — and it scored 100% doing so. When adding a case,
check it against `project_route.md.j2` first.

To run:
    hogli evals eval_project_classifier
    hogli evals eval_project_classifier --eval project_named_in_a_config_value
"""

from __future__ import annotations

import asyncio

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.temporal.ai.slack_app.activities import classifiers

from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPublicEval
from products.slack_app.evals.scorers import PROJECT_ROUTE_KEY, NoUnaskedProjectSwitch, ProjectRouteMatch

SUITE_KIND = SuiteKind.ONE_SHOT


def _project(*, team_id: int, integration_id: int, name: str) -> Integration:
    """An unsaved `Integration` row, which is all the classifier reads."""
    return Integration(
        id=integration_id,
        kind="slack",
        team=Team(id=team_id, name=name, organization=Organization(name="Northwind")),
    )


# An environment pair differing by one word, plus a project whose name is also an ordinary
# noun: the two shapes that make the task hard. Team ids and integration ids differ so a
# case fails if the two are ever swapped.
STAGING = _project(team_id=41, integration_id=410, name="Staging")
PRODUCTION = _project(team_id=42, integration_id=420, name="Production")
WEBSITE = _project(team_id=43, integration_id=430, name="Website")
PROJECTS = [STAGING, PRODUCTION, WEBSITE]


def _routes_to(project: Integration | None = None) -> dict:
    return {PROJECT_ROUTE_KEY: {"integration_id": project.id if project else None}}


ROUTING_CASES = [
    BaseEvalCase(
        name="explicit_on_project",
        prompt="@PostHog how many signups did we get on Northwind staging yesterday?",
        expected=_routes_to(STAGING),
    ),
    BaseEvalCase(
        name="project_as_a_prefix",
        prompt="@PostHog on website: what share of sessions bounce off the pricing page?",
        expected=_routes_to(WEBSITE),
    ),
    # The rule that inverts the model classifier: a model named as the subject of a
    # question is never an instruction, a project named as the subject is where the
    # answer comes from.
    BaseEvalCase(
        name="project_is_the_subject_of_the_problem",
        prompt="@PostHog production has been shedding mobile sessions since the 4.2 release, dig into it",
        expected=_routes_to(PRODUCTION),
    ),
    BaseEvalCase(
        name="environment_word_alone",
        prompt="@PostHog how many people hit the paywall on staging last week?",
        expected=_routes_to(STAGING),
    ),
    BaseEvalCase(
        name="project_at_the_end",
        prompt="@PostHog which feature flags haven't been evaluated in a month? staging please",
        expected=_routes_to(STAGING),
    ),
]

NO_ROUTE_CASES = [
    BaseEvalCase(
        name="project_as_the_object_of_a_change",
        prompt="@PostHog our onboarding doc still tells people to make a Website project, bring it up to date",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="project_in_a_proposal",
        prompt="@PostHog write up the case for folding Website into Production so we stop paying for both",
        expected=_routes_to(),
    ),
    # One task answers from one project, so picking either silently answers half.
    BaseEvalCase(
        name="two_projects_at_once",
        prompt="@PostHog which had more failed exports this week, staging or production?",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="project_name_as_an_ordinary_noun",
        prompt="@PostHog add a link to our website in the survey footer copy",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="project_named_in_a_config_value",
        prompt="@PostHog our deploy script has PROJECT=northwind-staging hardcoded, make it an env var",
        expected=_routes_to(),
    ),
    # Past tense is the tell, the same one the model classifier turns on.
    BaseEvalCase(
        name="project_already_ruled_out",
        prompt="@PostHog staging came back clean when I looked yesterday, so start from the ingestion pipeline",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="no_project_mentioned",
        prompt="@PostHog the checkout funnel drops 40% between steps 2 and 3, can you work out why",
        expected=_routes_to(),
    ),
]


async def eval_project_classifier(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        classifier_model = classifiers.PROJECT_ROUTE_CLASSIFIER_MODEL
        try:
            # Sync, and blocking on the gateway — keep it off the event loop so cases
            # still run concurrently under the harness's limiter.
            chosen = await asyncio.to_thread(
                classifiers.classify_slack_app_project_route,
                case.prompt,
                PROJECTS,
            )
        except Exception as error:
            return {
                "classifier_model": classifier_model,
                "route": None,
                "error": f"{type(error).__name__}: {error}",
            }
        return {
            "classifier_model": classifier_model,
            "route": {"integration_id": chosen.id} if chosen else None,
            "last_message": f"{classifier_model}: {chosen.team.name if chosen else None}",
        }

    await OneShotPublicEval(
        experiment_name="slack-app-project-classifier",
        cases=[*ROUTING_CASES, *NO_ROUTE_CASES],
        scorers=[ProjectRouteMatch(), NoUnaskedProjectSwitch()],
        task=task,
        ctx=ctx,
    )
