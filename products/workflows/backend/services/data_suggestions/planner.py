from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.messaging.backend.facade.api import EmailTemplateSummary
from products.workflows.backend.facade.contracts import LifecycleStage, OutlineKind
from products.workflows.backend.services.data_suggestions.llm import invoke_structured
from products.workflows.backend.services.hog_flow_templates import StepTemplate

from ee.hogai.utils.untrusted import as_untrusted_data

MAX_PLANNED_STEPS = 20

# Ideas are short copy over an event list. The step plan is a graph of up to 20 steps with branches and email copy,
# which needs the stronger model. It runs once per click, so its cost stays small.
IDEAS_MODEL = "claude-sonnet-5-5"
PLANNER_MODEL = "claude-opus-5-5"

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
    email_templates: tuple[EmailTemplateSummary, ...]
    step_templates: tuple[StepTemplate, ...]
    events: tuple[str, ...]
    channels: frozenset[Channel]
    has_slack: bool
    # The trigger event's own properties, like a product name or an amount, that an email can show.
    event_properties: tuple[str, ...] = ()


_SIMPLE_RULE = (
    "Keep the workflow as simple as its goal allows. Every step must do something for the person or the team. "
    "Do not add steps that only record state, like setting a person property, unless a later step depends on it."
)

_ONBOARDING_RULE = (
    "This team has no workflows yet, and welcome and onboarding workflows convert best. When the list has an "
    "event for a new sign-up or for onboarding, make one of the ideas a welcome or onboarding workflow on it, "
    "even when other events fire more often. Then prefer other meaningful moments."
)

_REVENUE_RULE = (
    "Prefer moments where a message earns or saves money: a trial that ends soon, a cart or checkout left "
    "unfinished, a failed payment, a cancellation or pause to win back, and a sign-up that has not reached its "
    "first key action. Prefer them over thank-you, feedback and review requests. Prefer events that happen every "
    "week over rare ones, so the workflow keeps sending."
)

_COPY_RULES = "Write plain, friendly copy in sentence case. No emojis, no em dashes, no placeholders like [Name], no template tags."

_IDEAS_PROMPT = f"""You suggest marketing and automation workflows for a product team using PostHog Workflows.
Suggest up to 6 workflows the project does not have yet. Each one starts when one of the project's events happens.

Rules:
- trigger_event must be copied exactly from the event list.
- {_ONBOARDING_RULE}
- {_REVENUE_RULE}
- Each idea must use a different trigger_event.
- List the ideas best first. Within one lifecycle stage only the first idea is shown.
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
- conditional_branch: split on person properties the team defines. It cannot check what the person did.
- random_split: split people at random into paths, such as for an A/B test.
- exit: end the workflow early with a reason.

Rules:
- Steps form a graph: next, branches and wait_event_next point at step ids. Never point back at an earlier step.
- Leave settings you cannot know blank: API keys, URLs, channels, phone numbers, property filters and \
recipients. The team fills them in. Say what is left in setup_note.
- A wait_until_event step waits for the event that shows the workflow reached its goal for this person, like a \
successful payment after a failed one, or an order after an abandoned cart. Use it only when an event in the list \
clearly means that. Another event of the same kind is not enough: a paid invoice from the person's own customer is not \
their subscription payment. When no event means it, use a delay instead.
- To check whether the person did something, like started a chat or placed an order, wait for that event with a \
wait_until_event step. Never use a delay followed by a conditional_branch for it, which the team would have to set up.
- {{personalization_rule}}
- Never promise a discount, offer or gift. The team adds one if it has one.
- {{email_rule}}
- {{channel_rule}}
- {{slack_rule}}
- {_SIMPLE_RULE}
- Put a delay between two emails.
- {_COPY_RULES}
"""


def suggest_ideas(*, team: Team, user: User, context: IdeaContext, analytics_client: Any = None) -> list[WorkflowIdea]:
    slack_rule = "" if context.has_slack else "The team has not connected Slack yet, so prefer other steps."
    lines = [
        f"{name} ({count} in the last 7 days, stage: {context.stages[name]})"
        if name in context.stages
        else f"{name} ({count} in the last 7 days)"
        for name, count in context.events
    ]
    result = invoke_structured(
        team=team,
        user=user,
        model=IDEAS_MODEL,
        effort="low",
        feature="data_suggestion_ideas",
        schema=WorkflowIdeas,
        system=_IDEAS_PROMPT.format(channel_rule=_channel_rule(context.channels), slack_rule=slack_rule),
        excluded_values=_missing_channels(context.channels),
        # The prompt escapes `<` and `>` in event names, so the schema carries the exact names the model must return.
        allowed_values={"trigger_event": [name for name, _ in context.events]},
        human=as_untrusted_data("project_events", lines, source="event names sent by this project's app"),
        analytics_client=analytics_client,
    )
    return result.ideas if result else []


def _missing_channels(channels: frozenset[Channel]) -> frozenset[str]:
    return frozenset({"sms", "push"} - channels)


def _channel_rule(channels: frozenset[Channel]) -> str:
    if not channels:
        return "The team has no SMS or push provider, so use email to reach people."
    return f"The team can also send {' and '.join(sorted(channels))}. Use them only when they suit the message better than email."


def plan_steps(
    *, team: Team, user: User, context: StepsContext, analytics_client: Any = None
) -> PlannedWorkflow | None:
    email_rule = (
        "For each email step, set email_template_id only when a saved template's name and subject clearly match "
        "the purpose of that step. Generic or placeholder templates never match. Otherwise leave it null and "
        "write the subject, heading and paragraphs."
        if context.email_templates
        else "For each email step, write the subject, heading and paragraphs, and leave email_template_id null."
    )
    slack_rule = (
        "Slack steps post to a channel the team picks later."
        if context.has_slack
        else "The team has not connected Slack yet. A slack step is fine, the team connects it on the step."
    )
    personalization_rule = (
        "The trigger event carries the properties listed in trigger_event_properties. To show one in an email, write "
        "[[property|fallback words]], for example [[product_name|your items]]. The fallback shows when the event has "
        "no value. Use a property where it makes the email specific, like naming the product, plan or amount. Never show a "
        "code, id or error value, which reads as noise to a customer. Never write a value yourself. This is the only "
        "placeholder allowed."
        if context.event_properties
        else "Do not mention a product name, price or amount you cannot know."
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
    if context.event_properties:
        human += "\n\n" + as_untrusted_data(
            "trigger_event_properties",
            list(context.event_properties),
            source="property names this project sends on the trigger event",
        )
    human += "\n\n" + as_untrusted_data(
        "step_catalog",
        [
            f"template_id={template.template_id} name={template.name} description={template.description[:120]}"
            for template in context.step_templates
        ],
        source="the function templates a workflow step can use",
    )
    if context.email_templates:
        human += "\n\n" + as_untrusted_data(
            "saved_email_templates",
            [
                f"id={template.id} name={template.name} subject={template.subject}"
                for template in context.email_templates
            ],
            source="email templates this team saved in PostHog",
        )
    return invoke_structured(
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
            personalization_rule=personalization_rule,
            max_steps=MAX_PLANNED_STEPS,
        ),
        excluded_values=_missing_channels(context.channels),
        # An empty enum would make every wait_until_event step impossible, so the list is only set when there is one.
        allowed_values={"wait_event": context.events} if context.events else None,
        human=human,
        analytics_client=analytics_client,
    )
