from typing import Any, Literal, TypeVar

import structlog
from pydantic import BaseModel, Field, ValidationError

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.workflows.backend.services.data_suggestions.ranking import LifecycleStage

from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.utils.untrusted import as_untrusted_data

logger = structlog.get_logger(__name__)

MAX_PLANNED_STEPS = 20

# Ideas are short copy over an event list. The step plan is a graph of up to 20 steps with branches and email copy,
# which needs the stronger model. It runs once per click, so its cost stays small.
IDEAS_MODEL = "claude-sonnet-5-5"
PLANNER_MODEL = "claude-opus-5-5"
_TIMEOUT_SECONDS = 120
_MAX_OUTPUT_TOKENS = 16000

# The step chips a suggestion card shows.
OutlineKind = Literal["email", "sms", "push", "slack", "webhook", "delay", "wait_until", "branch", "split", "action"]
# The planner's step types. "function" covers every other step from the template catalog.
StepType = Literal[
    "email",
    "sms",
    "push",
    "slack",
    "function",
    "delay",
    "wait_until_time_window",
    "wait_until_event",
    "conditional_branch",
    "random_split",
    "exit",
]
DelayDuration = Literal["1h", "1d", "2d", "3d", "7d"]
# Message channels that need a provider the team connects. Email is always offered.
Channel = Literal["sms", "push"]


class WorkflowIdea(BaseModel):
    name: str = Field(description="Short workflow name in sentence case, at most 50 characters.")
    description: str = Field(description="One sentence on what the workflow does, at most 90 characters.")
    reason: str = Field(description="One sentence on why it fits this project, naming the trigger event.")
    trigger_event: str = Field(description="Exactly one event name from the project's event list.")
    stage: LifecycleStage = Field(
        description="The customer lifecycle stage the trigger event marks: signup (an account or user is created), "
        "onboarding (first steps, setup, activation, invites), trial, purchase (paid, upgraded, ordered), "
        "churn_risk (cancelled, downgraded, inactive), failure (an error the user hit), support (tickets, "
        "surveys), or other."
    )
    step_outline: list[OutlineKind] = Field(
        description="The main steps after the trigger, in order, at most 20. webhook is a call to an external "
        "endpoint, action is any other step such as updating a person or sending to a CRM."
    )


class WorkflowIdeas(BaseModel):
    ideas: list[WorkflowIdea]


class PlannedBranch(BaseModel):
    label: str = Field(description="Short name of this path, like 'Finished onboarding' or 'Group A'.")
    percentage: int | None = Field(description="For a random_split: this path's share in percent, else null.")
    next: str | None = Field(description="The id of the first step on this path, or null to end the workflow.")


class PlannedStep(BaseModel):
    id: str = Field(description="A short id that is unique in this workflow, like 'welcome_email'.")
    type: StepType
    name: str = Field(description="Short display name of the step in sentence case, at most 40 characters.")
    setup_note: str = Field(
        description="What the team still has to fill in on this step, like 'Pick the Slack channel'. "
        "Empty when nothing is left."
    )
    next: str | None = Field(
        description="The id of the step that follows. For wait_until_event it is the path when the wait times out, "
        "for conditional_branch the path when no condition matches. Null ends the workflow."
    )
    branches: list[PlannedBranch] | None = Field(
        description="conditional_branch: one path per condition, the label says what the condition checks. "
        "random_split: two or more paths whose percentages add up to 100. Null for every other type."
    )
    template_id: str | None = Field(
        description="For a function step: one template_id from the step catalog, else null."
    )
    wait_event: str | None = Field(
        description="For wait_until_event: one event name copied exactly from the project's events, else null."
    )
    wait_event_next: str | None = Field(
        description="For wait_until_event: the id of the step to run when the event happens, or null to end the workflow."
    )
    duration: DelayDuration | None = Field(
        description="For delay: how long to wait. For wait_until_event: the longest time to wait. Else null."
    )
    email_template_id: str | None = Field(
        description="For an email step: the id of one of the team's saved email templates that fits, else null."
    )
    email_subject: str | None = Field(description="For an email step without a saved template: the subject line.")
    email_heading: str | None = Field(description="For an email step without a saved template: the headline.")
    email_paragraphs: list[str] | None = Field(
        description="For an email step without a saved template: 1 to 3 short paragraphs of body copy."
    )
    email_button_label: str | None = Field(description="For an email step without a saved template: the button text.")
    slack_message: str | None = Field(description="For a slack step: the message to post, else null.")


class PlannedWorkflow(BaseModel):
    first_step: str = Field(description="The id of the step that runs right after the trigger.")
    steps: list[PlannedStep]


@frozen
class IdeaContext:
    events: tuple[tuple[str, int], ...]
    stages: dict[str, LifecycleStage]
    channels: frozenset[Channel]
    has_slack: bool


@frozen
class StepsContext:
    idea: WorkflowIdea
    email_templates: tuple[tuple[str, str, str], ...]
    step_templates: tuple[tuple[str, str, str], ...]
    events: tuple[str, ...]
    channels: frozenset[Channel]
    has_slack: bool


_SIMPLE_RULE = (
    "Keep the workflow as simple as its goal allows. Every step must do something for the person or the team. "
    "Do not add steps that only record state, like setting a person property, unless a later step depends on it."
)

_ONBOARDING_RULE = (
    "This team has no workflows yet, and welcome and onboarding workflows convert best. When the list has an "
    "event for a new sign-up or for onboarding, make one of the ideas a welcome or onboarding workflow on it, "
    "even when other events fire more often. Then prefer other meaningful moments."
)

_COPY_RULES = "Write plain, friendly copy in sentence case. No emojis, no em dashes, no placeholders like [Name], no template tags."

_IDEAS_PROMPT = f"""You suggest marketing and automation workflows for a product team using PostHog Workflows.
Suggest up to 6 workflows the project does not have yet. Each one starts when one of the project's events happens.

Rules:
- trigger_event must be copied exactly from the event list.
- {_ONBOARDING_RULE}
- Each idea must use a different trigger_event.
- Email is the main way to reach people. {{channel_rule}} {{slack_rule}}
- Use the steps the workflow needs, including waits for an event and branches. {_SIMPLE_RULE}
- Put a delay between two emails.
- {_COPY_RULES}
"""

_STEPS_PROMPT = f"""You plan the steps of one PostHog workflow. The workflow and its outline are given below.
Follow the outline unless a step cannot work. Use at most {{max_steps}} steps, as many as the workflow needs.

Step types:
- email: a message to the person, and the main channel. Write the copy.
- sms, push: a message to the person, only when the team has that provider connected.
- slack: a message to the team's Slack channel. Write the message.
- function: any step from the step catalog, such as a webhook, a CRM update or a PostHog action. Set template_id.
- delay: wait a fixed time.
- wait_until_time_window: wait for a time of day or day of the week the team picks.
- wait_until_event: wait until the person does one of the project's events, at most duration.
- conditional_branch: split on conditions the team defines, such as a person property.
- random_split: split people at random into paths, such as for an A/B test.
- exit: end the workflow early with a reason.

Rules:
- Steps form a graph: next, branches and wait_event_next point at step ids. Never point back at an earlier step.
- Leave settings you cannot know blank: API keys, URLs, channels, phone numbers, property filters and \
recipients. The team fills them in. Say what is left in setup_note.
- {{email_rule}}
- {{channel_rule}}
- {{slack_rule}}
- {_SIMPLE_RULE}
- Put a delay between two emails.
- {_COPY_RULES}
"""


def suggest_ideas(*, team: Team, user: User, context: IdeaContext) -> list[WorkflowIdea]:
    slack_rule = "" if context.has_slack else "The team has not connected Slack yet, so prefer other steps."
    lines = [
        f"{name} ({count} in the last 7 days, stage: {context.stages[name]})"
        if name in context.stages
        else f"{name} ({count} in the last 7 days)"
        for name, count in context.events
    ]
    result = _invoke(
        team=team,
        user=user,
        model=IDEAS_MODEL,
        effort="low",
        feature="data_suggestion_ideas",
        schema=WorkflowIdeas,
        system=_IDEAS_PROMPT.format(channel_rule=_channel_rule(context.channels), slack_rule=slack_rule),
        excluded_values=_missing_channels(context.channels),
        human=as_untrusted_data("project_events", lines, source="event names sent by this project's app"),
    )
    return result.ideas if result else []


def _missing_channels(channels: frozenset[Channel]) -> frozenset[str]:
    return frozenset({"sms", "push"} - channels)


def _channel_rule(channels: frozenset[Channel]) -> str:
    if not channels:
        return "The team has no SMS or push provider, so use email to reach people."
    return f"The team can also send {' and '.join(sorted(channels))}. Use them only when they suit the message better than email."


def plan_steps(*, team: Team, user: User, context: StepsContext) -> PlannedWorkflow | None:
    email_rule = (
        "For each email step, set email_template_id only when a saved template's name and subject clearly match "
        "the purpose of that step. Generic or placeholder templates never match. Otherwise leave it null and "
        "write the subject, heading, paragraphs and button label."
        if context.email_templates
        else "For each email step, write the subject, heading, paragraphs and button label, and leave email_template_id null."
    )
    slack_rule = (
        "Slack steps post to a channel the team picks later."
        if context.has_slack
        else "The team has not connected Slack yet. A slack step is fine, the team connects it on the step."
    )
    idea = context.idea
    human = as_untrusted_data(
        "workflow",
        [
            f"name: {idea.name}",
            f"description: {idea.description}",
            f"trigger event: {idea.trigger_event}",
            f"outline: {', '.join(idea.step_outline)}",
        ],
        source="a workflow idea written from this project's event names",
    )
    human += "\n\n" + as_untrusted_data(
        "project_events", list(context.events), source="event names sent by this project's app"
    )
    human += "\n\n" + as_untrusted_data(
        "step_catalog",
        [
            f"template_id={template_id} name={name} description={description[:120]}"
            for template_id, name, description in context.step_templates
        ],
        source="the function templates a workflow step can use",
    )
    if context.email_templates:
        human += "\n\n" + as_untrusted_data(
            "saved_email_templates",
            [
                f"id={template_id} name={name} subject={subject}"
                for template_id, name, subject in context.email_templates
            ],
            source="email templates this team saved in PostHog",
        )
    result = _invoke(
        team=team,
        user=user,
        model=PLANNER_MODEL,
        effort="medium",
        feature="data_suggestion_steps",
        schema=PlannedWorkflow,
        system=_STEPS_PROMPT.format(
            email_rule=email_rule,
            channel_rule=_channel_rule(context.channels),
            slack_rule=slack_rule,
            max_steps=MAX_PLANNED_STEPS,
        ),
        excluded_values=_missing_channels(context.channels),
        human=human,
    )
    return result


_Schema = TypeVar("_Schema", bound=BaseModel)


def _invoke(
    *,
    team: Team,
    user: User,
    model: str,
    effort: Literal["low", "medium", "high"],
    feature: str,
    schema: type[_Schema],
    system: str,
    human: str,
    excluded_values: frozenset[str],
) -> _Schema | None:
    try:
        llm = MaxChatAnthropic(
            model=model,
            user=user,
            team=team,
            # PostHog covers these calls, so suggestions never draw on the customer's AI credits.
            billable=False,
            inject_context=False,
            streaming=False,
            disable_streaming=True,
            stream_usage=False,
            max_tokens=_MAX_OUTPUT_TOKENS,
            # Current Claude models only think adaptively, and a forced tool call (langchain's structured output)
            # does not work with thinking. The API's own JSON schema output does.
            thinking={"type": "adaptive"},
            model_kwargs={
                "output_config": {
                    "effort": effort,
                    "format": {"type": "json_schema", "schema": _strict_schema(schema, excluded_values)},
                }
            },
            default_request_timeout=_TIMEOUT_SECONDS,
            posthog_properties={"ai_product": "workflows", "ai_feature": feature},
        )
        response = llm.invoke([("system", system), ("human", human)])
        return schema.model_validate_json(_response_text(response.content))
    except ValidationError:
        logger.warning("workflows.data_suggestions.llm_malformed", team_id=team.id, feature=feature, exc_info=True)
        return None
    except Exception:
        logger.warning("workflows.data_suggestions.llm_failed", team_id=team.id, feature=feature, exc_info=True)
        return None


def _strict_schema(schema: type[BaseModel], excluded_values: frozenset[str]) -> dict[str, Any]:
    # The API's JSON schema output requires every object to forbid properties the schema does not list.
    # Removing a value from every enum means the model cannot pick a channel the team has not connected.
    def close_objects(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
            if isinstance(node.get("enum"), list):
                node["enum"] = [value for value in node["enum"] if value not in excluded_values]
            for value in node.values():
                close_objects(value)
        elif isinstance(node, list):
            for value in node:
                close_objects(value)

    json_schema = schema.model_json_schema()
    close_objects(json_schema)
    return json_schema


def _response_text(content: str | list[Any]) -> str:
    # With thinking on, the answer is the text blocks after the thinking blocks.
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
    )
