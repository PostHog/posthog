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

The prompt is the only thing standing between a mention and a wrong project, so this suite
is the whole of the quality signal. Nothing downstream second-guesses the answer: an id the
model returns is an id the run is moved to.

Most cases run with the project the run is already on offered as the default, which is how
a mention usually arrives. `NO_DEFAULT_CASES` repeats five of them with none, the shape a
mention takes when the resolved install is one `routable_projects` drops. Same message on
either side, so a difference in the answers is the default's doing and nothing else.

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
# The project whose team owns the agent itself. Present because without it the suite
# cannot pose the question the classifier actually got wrong: asked to change how the
# agent behaves, it answered with the owning project instead of with null. A workspace
# with nothing to attribute the work to never offers that temptation.
AGENT_PLATFORM = _project(team_id=44, integration_id=440, name="Agent Platform")
# Real project names carry emoji and more than one word, and nobody types them whole.
MOBILE = _project(team_id=45, integration_id=450, name="📱 Mobile app")
# The project the run is already on, which heads the list the model is shown. No case
# routes to it by accident: nothing below says "main", so every scored switch is a real
# one, and every null is a decision to stay here.
MAIN = _project(team_id=40, integration_id=400, name="Main")
PROJECTS = [STAGING, PRODUCTION, WEBSITE, AGENT_PLATFORM, MOBILE, MAIN]


# A second workspace, shaped like the one the misroute happened in: thirteen projects,
# several of them plausible homes for work on an AI agent. Six clean candidates turned out
# not to reproduce anything — the model answers those correctly with or without the rules
# this suite is here to measure. The pull towards an owner only appears when several
# owners are on offer and the message reads like their subject matter.
AUTOPILOT = _project(team_id=46, integration_id=460, name="Autopilot")
CROWD = [
    MAIN,
    STAGING,
    PRODUCTION,
    WEBSITE,
    AGENT_PLATFORM,
    MOBILE,
    AUTOPILOT,
    _project(team_id=47, integration_id=470, name="AI labeling suite"),
    _project(team_id=48, integration_id=480, name="Security Review Agent"),
    _project(team_id=49, integration_id=490, name="🧪 Test"),
    _project(team_id=50, integration_id=500, name="DevEx"),
    _project(team_id=51, integration_id=510, name="Demo"),
    _project(team_id=52, integration_id=520, name="Statuspage"),
]

WORKSPACES: dict[str, tuple[list[Integration], Integration]] = {"simple": (PROJECTS, MAIN), "crowded": (CROWD, MAIN)}


def _routes_to(project: Integration | None = None) -> dict:
    return {PROJECT_ROUTE_KEY: {"integration_id": project.id if project else None}}


def _in_the_crowd(**kwargs) -> BaseEvalCase:
    return BaseEvalCase(metadata={"workspace": "crowded"}, **kwargs)


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
    BaseEvalCase(
        name="project_id_in_a_pasted_url",
        prompt="@PostHog https://us.posthog.com/project/42/insights/a1b2c3 reads zero since Tuesday, what happened?",
        expected=_routes_to(PRODUCTION),
    ),
    BaseEvalCase(
        name="project_id_written_out",
        prompt="@PostHog answer this from project 43: which pages lost the most traffic last month?",
        expected=_routes_to(WEBSITE),
    ),
    # The counterpart to the ownership cases below, and the reason the fix cannot simply
    # be "never route to the project that owns the agent". A data question about that
    # project is an ordinary routing request and has to be answered from its data.
    BaseEvalCase(
        name="owning_project_asked_a_data_question",
        prompt="@PostHog how many agent runs failed overnight on Agent Platform?",
        expected=_routes_to(AGENT_PLATFORM),
    ),
    BaseEvalCase(
        name="decorated_name_written_short",
        prompt="@PostHog how many crashes did the mobile app see after Thursday's release?",
        expected=_routes_to(MOBILE),
    ),
    BaseEvalCase(
        name="possessive_form",
        prompt="@PostHog what is staging's event volume today compared with a week ago?",
        expected=_routes_to(STAGING),
    ),
    BaseEvalCase(
        name="named_with_from",
        prompt="@PostHog from production, list the ten slowest queries this morning",
        expected=_routes_to(PRODUCTION),
    ),
    BaseEvalCase(
        name="named_only_in_a_url",
        prompt="@PostHog https://us.posthog.com/project/45/replay/abc — is this session typical of the crash?",
        expected=_routes_to(MOBILE),
    ),
    # The default is nameable like any other project, and saying so is not a mistake.
    BaseEvalCase(
        name="default_named_explicitly",
        prompt="@PostHog in Main, how many weekly active users did we finish the month on?",
        expected=_routes_to(MAIN),
    ),
    # The run is on the default already, so a project named alongside it still wins.
    BaseEvalCase(
        name="named_project_beside_the_default",
        prompt="@PostHog I know we usually look at Main, but check the paywall conversion on website",
        expected=_routes_to(WEBSITE),
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
    BaseEvalCase(
        name="change_the_agents_own_wordiness",
        prompt="@PostHog you're far too wordy when nothing is wrong, edit this scout to keep quiet weeks short",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="change_where_the_agent_puts_a_link",
        prompt="@PostHog your last answer buried the link at the bottom, put it up top from now on",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="change_the_agents_house_style",
        prompt="@PostHog stop using em-dashes in the summaries you post, they read badly on mobile",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="subject_matter_overlap_without_a_name",
        prompt=(
            "@PostHog we said this was fine once already, stop raising it: 806,431 of 2,774,905 rows "
            "are missing a request id, which blocks trace lookup"
        ),
        expected=_routes_to(),
    ),
    # A count, a percentage, a version and an error code, each exactly equal to an offered
    # project id. Numbers are only a project where the message says they are.
    BaseEvalCase(
        name="bare_number_is_a_count",
        prompt="@PostHog 42 people hit the paywall twice yesterday, is that expected?",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="bare_number_is_a_version",
        prompt="@PostHog crashes jumped after 41 shipped, can you confirm before I roll it back?",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="bare_number_is_an_error_code",
        prompt="@PostHog we're seeing a lot of 43s in the exporter logs, worth worrying about?",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="asks_who_owns_something",
        prompt="@PostHog who looks after the ingestion pipeline these days, and who should I take this to?",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="change_where_the_agent_answers",
        prompt="@PostHog reply in the thread next time instead of DMing me, I lost the last one",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="complains_about_the_agents_routing",
        prompt="@PostHog why did you answer my last question from somewhere else entirely? sort that out",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="agent_capability_question",
        prompt="@PostHog can you open pull requests on your own, or do you only ever comment?",
        expected=_routes_to(),
    ),
    # A project that does not exist yet cannot be where an answer comes from.
    BaseEvalCase(
        name="hypothetical_project",
        prompt="@PostHog if we split the mobile app out into its own project later, what breaks?",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="url_to_another_service",
        prompt="@PostHog https://github.com/Northwind/northwind/pull/4821 — can you review this before standup?",
        expected=_routes_to(),
    ),
    # An id that belongs to nothing on the list, offered as bait.
    BaseEvalCase(
        name="unoffered_id_in_the_message",
        prompt="@PostHog pull last week's retention from project 987654",
        expected=_routes_to(),
    ),
    BaseEvalCase(
        name="staying_put_said_out_loud",
        prompt="@PostHog keep this where it is and tell me which dashboards nobody opened this quarter",
        expected=_routes_to(),
    ),
    # The shape of the mention that misrouted, in a workspace shaped like the one it
    # misrouted in. Dense, numeric, unmistakably about an AI agent, and naming no project.
    _in_the_crowd(
        name="crowded_change_the_agents_own_wordiness",
        prompt=(
            "@PostHog Seems like you're too wordy for telling us everything is business as usual. Could you "
            "please edit this scout to be less wordy when nothing is actionable?\n\nAlso, for the following "
            "point, if we said it's fine, let's not mention it again:\n> The known gateway identifier gap "
            "persists: 806,431 of 2,774,905 summarization rows (29.1%) and 18,662 of 64,118 clustering rows "
            "(29.1%) lacked a gateway request ID. This blocks reliable trace lookup and request-level "
            "attribution."
        ),
        expected=_routes_to(),
    ),
    _in_the_crowd(
        name="crowded_change_the_agents_reply",
        prompt=(
            "@PostHog the bot can hand out discount codes. The reply it sends is missing the clickable URL an "
            "end user needs. Can you update the bottom section to include one, and drop the em-dash?"
        ),
        expected=_routes_to(),
    ),
    _in_the_crowd(
        name="crowded_agent_evaluation_question",
        prompt="@PostHog which of your evaluations regressed this week, and can you make the scorer stricter?",
        expected=_routes_to(),
    ),
]

# Crowding must not cost the classifier a project the author did name.
CROWDED_ROUTING_CASES = [
    _in_the_crowd(
        name="crowded_explicit_on_project",
        prompt="@PostHog how many signups did we get on Northwind staging yesterday?",
        expected=_routes_to(STAGING),
    ),
    _in_the_crowd(
        name="crowded_owning_project_asked_a_data_question",
        prompt="@PostHog how many agent runs failed overnight on Autopilot?",
        expected=_routes_to(AUTOPILOT),
    ),
]

# A mention normally arrives with the resolved project on offer as the default, but not
# always: `routable_projects` drops an install the bot cannot post into, and the project
# the run is on can be that one. The model then sees the list in the auth filter's own
# order and no sentence naming where it already is.
_CASES_BY_NAME = {case.name: case for case in [*ROUTING_CASES, *NO_ROUTE_CASES, *CROWDED_ROUTING_CASES]}


def _without_a_default(name: str) -> BaseEvalCase:
    """The same message again, with nothing marked as the default.

    Same text on purpose. Holding the message fixed and removing the default is what
    isolates the sentence's effect on the answer; two different messages would only show
    that two different messages score differently.
    """
    case = _CASES_BY_NAME[name]
    return case.model_copy(
        update={"name": f"{name}_without_a_default", "metadata": {**case.metadata, "default": "none"}}
    )


NO_DEFAULT_CASES = [
    _without_a_default(name)
    for name in (
        "explicit_on_project",
        "project_id_in_a_pasted_url",
        "change_the_agents_own_wordiness",
        "subject_matter_overlap_without_a_name",
        "no_project_mentioned",
        "crowded_change_the_agents_own_wordiness",
        "crowded_change_the_agents_reply",
        "crowded_explicit_on_project",
    )
]


async def eval_project_classifier(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        classifier_model = classifiers.PROJECT_ROUTE_CLASSIFIER_MODEL
        try:
            # Sync, and blocking on the gateway — keep it off the event loop so cases
            # still run concurrently under the harness's limiter.
            projects, resolved = WORKSPACES[case.metadata.get("workspace", "simple")]
            chosen = await asyncio.to_thread(
                classifiers.classify_slack_app_project_route,
                case.prompt,
                projects,
                None if case.metadata.get("default") == "none" else resolved,
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
        cases=[*ROUTING_CASES, *CROWDED_ROUTING_CASES, *NO_ROUTE_CASES, *NO_DEFAULT_CASES],
        scorers=[ProjectRouteMatch(), NoUnaskedProjectSwitch()],
        task=task,
        ctx=ctx,
    )
