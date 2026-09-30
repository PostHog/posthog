import re
from typing import TYPE_CHECKING, Annotated, Any, Literal, Union

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema, model_validator
from pydantic_core import PydanticCustomError

from posthog.schema import PropertyOperator

from products.workflows.backend.models.hog_flow.hog_flow import SUPPORTED_ACTION_TYPES, TRIGGER_TYPES, HogFlow
from products.workflows.backend.utils.durations import (
    DURATION_PATTERN,
    MAX_VALUE_FOR_DURATION_UNIT,
    SECONDS_PER_DURATION_UNIT,
    parse_duration,
)

KEY_PATTERN = r"^[A-Za-z0-9_-]{1,400}$"
MAX_KEY_LENGTH = 400
STEP_ID_PATTERN = r"^[A-Za-z0-9_-]{1,200}$"

_MAX_DELAY_SECONDS = MAX_VALUE_FOR_DURATION_UNIT["d"] * SECONDS_PER_DURATION_UNIT["d"]
_OVER_30_DAYS_FIX = "Use 30d or less. To wait longer, add a second delay step after this one."
_UNIT_NAMES = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
# The number alternation keeps each digit run owned by one quantifier, as in durations.py, so a long
# value that does not match fails in linear time.
_LOOSE_DURATION = re.compile(
    r"^ *((?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)) *(s|sec|second|m|min|minute|h|hr|hour|d|day)s? *$", re.IGNORECASE
)
_MAX_SHOWN_VALUE_LENGTH = 60

PASS_THROUGH_ACTION_TYPES = [t for t in SUPPORTED_ACTION_TYPES if t not in ("trigger", "exit")]
PASS_THROUGH_TRIGGER_TYPES = sorted(TRIGGER_TYPES - {"event", "schedule"})

if TYPE_CHECKING:
    PropertyOperatorValue = str
    PassThroughActionType = str
    PassThroughTriggerType = str
    ExitConditionValue = str
else:
    PropertyOperatorValue = Literal[tuple(operator.value for operator in PropertyOperator)]
    PassThroughActionType = Literal[tuple(PASS_THROUGH_ACTION_TYPES)]
    PassThroughTriggerType = Literal[tuple(PASS_THROUGH_TRIGGER_TYPES)]
    ExitConditionValue = Literal[tuple(HogFlow.ExitCondition.values)]


def document_error(message: str, why: str, fix: str) -> PydanticCustomError:
    return PydanticCustomError("document_error", "{message}", {"message": message, "why": why, "fix": fix})


def shown(value: str) -> str:
    """A value quoted back in an error, cut short so a long value does not fill the response."""
    if len(value) <= _MAX_SHOWN_VALUE_LENGTH:
        return f"'{value}'"
    return f"'{value[:_MAX_SHOWN_VALUE_LENGTH]}...'"


def _check_duration(value: str) -> str:
    parsed = parse_duration(value)
    if parsed is None or parsed.negative or parsed.amount == 0:
        raise document_error(
            f"{shown(value)} is not a duration.",
            "A delay needs a number above zero followed by one unit: s, m, h or d.",
            _duration_fix(value),
        )
    cap = MAX_VALUE_FOR_DURATION_UNIT[parsed.unit]
    if parsed.amount <= cap:
        return value
    seconds = parsed.amount * SECONDS_PER_DURATION_UNIT[parsed.unit]
    if seconds > _MAX_DELAY_SECONDS:
        raise document_error(
            f"{shown(value)} is longer than 30 days.",
            "The longest delay PostHog runs is 30 days. A longer delay ends after 30 days without an error.",
            _OVER_30_DAYS_FIX,
        )
    raise document_error(
        f"{shown(value)} is more than {cap:g} {_UNIT_NAMES[parsed.unit]}.",
        f"A delay in {_UNIT_NAMES[parsed.unit]} is at most {cap:g}{parsed.unit}. PostHog shortens a longer value to {cap:g}{parsed.unit} without an error.",
        _suggest_duration(seconds) or f"Use at most {cap:g}{parsed.unit}, or write the delay in a larger unit.",
    )


def _duration_fix(value: str) -> str:
    match = _LOOSE_DURATION.match(value) if len(value) <= _MAX_SHOWN_VALUE_LENGTH else None
    if match is None:
        return "Write the duration as a number and a unit, for example 30m or 3d."
    seconds = float(match.group(1)) * SECONDS_PER_DURATION_UNIT[match.group(2)[0].lower()]
    if seconds == 0:
        return "Use a number above zero, for example 30m or 3d."
    if seconds > _MAX_DELAY_SECONDS:
        return _OVER_30_DAYS_FIX
    return _suggest_duration(seconds) or "Write the duration as a number and a unit, for example 30m or 3d."


def _suggest_duration(seconds: float) -> str | None:
    """The duration in the largest unit that holds it as a short number within that unit's cap."""
    for unit in ("d", "h", "m", "s"):
        amount = seconds / SECONDS_PER_DURATION_UNIT[unit]
        if 1 <= amount <= MAX_VALUE_FOR_DURATION_UNIT[unit] and round(amount, 2) == amount:
            return f"Write the duration as {amount:g}{unit}."
    return None


def _only_the_number(value: Any) -> Any:
    # Strict Literal[1] still takes true and 1.0, since both equal 1.
    if type(value) is not int:
        raise PydanticCustomError("unsupported_version", "version is not the number 1")
    return value


def key_from_name(name: str) -> str:
    """A key made from a workflow name: lower case, other characters turned into -."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:MAX_KEY_LENGTH].strip("-") or "workflow"


def _check_key(value: str) -> str:
    if re.fullmatch(KEY_PATTERN, value):
        return value
    raise document_error(
        f"{shown(value)} is not a valid key.",
        "The key identifies the workflow in the project. It holds letters, digits, hyphens and underscores, up to 400 characters.",
        "Use only letters, digits, - and _ in the key, for example trial-upgrade-nudge.",
    )


def _check_step_id(value: str) -> str:
    if re.fullmatch(STEP_ID_PATTERN, value):
        return value
    raise document_error(
        f"{shown(value)} is not a valid step id.",
        "A step id holds letters, digits, hyphens and underscores, up to 200 characters. PostHog stores it on every edge to the step.",
        "Use only letters, digits, - and _ in the id, for example wait_three_days.",
    )


Duration = Annotated[
    str,
    AfterValidator(_check_duration),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": DURATION_PATTERN,
            "description": "A number and one unit: s, m, h or d, for example 30m or 3d. At most 60s, 60m, 24h or 30d.",
        }
    ),
]
WorkflowKey = Annotated[str, AfterValidator(_check_key), WithJsonSchema({"type": "string", "pattern": KEY_PATTERN})]
StepId = Annotated[str, AfterValidator(_check_step_id), WithJsonSchema({"type": "string", "pattern": STEP_ID_PATTERN})]


class _DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Condition(_DocumentModel):
    model_config = ConfigDict(
        json_schema_extra={"oneOf": [{"required": ["person"]}, {"required": ["event"]}]},
    )

    person: str | None = Field(default=None, description="A person property to check. Set this or event, not both.")
    event: str | None = Field(default=None, description="An event property to check. Set this or person, not both.")
    operator: PropertyOperatorValue = Field(default="exact", description="How the property is compared with value.")
    value: Any = Field(
        default=None, description="What the property is compared with. A list matches any of its entries."
    )

    @model_validator(mode="after")
    def _one_property(self) -> "Condition":
        if (self.person is None) == (self.event is None):
            raise document_error(
                "A condition needs exactly one of person or event.",
                "A condition checks one property, either of the person or of the event.",
                "Write the condition as { person: plan, operator: exact, value: [pro] }, or use event: in place of person:.",
            )
        return self


class EventTrigger(_DocumentModel):
    model_config = ConfigDict(
        json_schema_extra={"oneOf": [{"required": ["event"]}, {"required": ["filters"]}]},
    )

    type: Literal["event"] = Field(description="Starts a run each time the event is captured.")
    name: str = Field(default="Trigger", max_length=400, description="The trigger's name in the workflow editor.")
    description: str = Field(default="", description="An optional note about the trigger.")
    event: str | None = Field(
        default=None, description="The event name, for example $pageview or trial started. Set this or filters."
    )
    properties: list[Condition] = Field(default_factory=list, description="Conditions the event must meet.")
    filter_test_accounts: bool = Field(default=False, description="Leave out events from test accounts.")
    filters: dict[str, Any] | None = Field(
        default=None,
        description="The trigger's filters as the workflows API takes them, for more than one event, actions or cohorts. Set this or event.",
    )

    @model_validator(mode="after")
    def _event_or_filters(self) -> "EventTrigger":
        if (self.event is None) == (self.filters is None):
            raise document_error(
                "An event trigger needs exactly one of event or filters.",
                "event, properties and filter_test_accounts describe one event. filters holds any other trigger filter as the workflows API takes it.",
                "Set event: to the event name, or move the whole filter into filters:.",
            )
        if self.filters is not None and (self.properties or self.filter_test_accounts):
            raise document_error(
                "properties and filter_test_accounts go with event, not with filters.",
                "filters holds the whole trigger filter, so the conditions and the test account setting belong inside it.",
                "Move the conditions into filters, or use event: in place of filters:.",
            )
        return self


class ScheduleTrigger(_DocumentModel):
    type: Literal["schedule"] = Field(
        description="Starts runs on a schedule. Set the schedule on the workflow in PostHog; the file does not hold it."
    )
    name: str = Field(default="Trigger", max_length=400, description="The trigger's name in the workflow editor.")
    description: str = Field(default="", description="An optional note about the trigger.")


class PassThroughTrigger(_DocumentModel):
    type: PassThroughTriggerType = Field(description="Any other trigger kind. Its config goes to PostHog unchanged.")
    name: str = Field(default="Trigger", max_length=400, description="The trigger's name in the workflow editor.")
    description: str = Field(default="", description="An optional note about the trigger.")
    config: dict[str, Any] = Field(description="The trigger config as the workflows API takes it, without type.")


Trigger = Annotated[Union[EventTrigger, ScheduleTrigger, PassThroughTrigger], Field(discriminator="type")]


class _Step(_DocumentModel):
    name: str = Field(
        min_length=1, max_length=400, description="The step's name. Unless id is set, the step id is made from it."
    )
    id: StepId | None = Field(
        default=None,
        description="The step id. Defaults to the name in lower case with other characters turned into _. Set it to keep people in place when you rename a step.",
    )
    description: str = Field(default="", description="An optional note about the step.")
    output_variable: dict[str, Any] | list[dict[str, Any]] | None = Field(
        default=None,
        description="Saves the step's result in a workflow variable, as the workflows API takes it: { key, result_path } or a list of those. Later steps read it as {variables.<key>}.",
    )


class DelayStep(_Step):
    type: Literal["delay"] = Field(description="Waits a fixed time before the next step.")
    duration: Duration


class Arm(_DocumentModel):
    name: str = Field(max_length=400, description="The arm's name in the workflow editor.")
    when: list[Condition] = Field(min_length=1, description="Conditions that must all match to take this arm.")
    then: list["Step"] = Field(min_length=1, description="The steps this arm runs, in order.")


class BranchStep(_Step):
    type: Literal["branch"] = Field(
        description="Takes the first arm whose conditions match. When none match, the run goes on after the branch."
    )
    arms: list[Arm] = Field(min_length=1, description="The arms, checked in order.")


class EmailSender(_DocumentModel):
    integration_ids: list[int] = Field(
        min_length=1, max_length=10, description="Ids of the project's email integrations to send from."
    )
    name: str | None = Field(default=None, description="The sender name people see.")
    email: str | None = Field(
        default=None,
        description="A sender address on the integration's verified domain. Defaults to the integration's.",
    )


class EmailRecipient(_DocumentModel):
    email: str = Field(description="The address, or Liquid such as {{ person.properties.email }}.")
    name: str = Field(default="", description="The recipient's name.")


def _recipient_from_address(value: Any) -> Any:
    return {"email": value} if isinstance(value, str) else value


Recipient = Annotated[
    EmailRecipient,
    BeforeValidator(_recipient_from_address),
    WithJsonSchema(
        {
            "description": "The recipient: an address, or { email, name }. Liquid works, for example {{ person.properties.email }}.",
            "anyOf": [{"type": "string"}, EmailRecipient.model_json_schema()],
        }
    ),
]


class EmailStep(_Step):
    type: Literal["email"] = Field(
        description="Sends an email. Values use Liquid, for example {{ person.properties.name }}."
    )
    sender: EmailSender = Field(alias="from", description="Who the email comes from.")
    to: Recipient
    subject: str = Field(description="The subject line.")
    text: str | None = Field(default=None, description="The plain text body. Set text, html or both.")
    html: str | None = Field(default=None, description="The HTML body. Set text, html or both.")
    preheader: str | None = Field(default=None, description="The preview text inboxes show after the subject.")

    @model_validator(mode="after")
    def _has_body(self) -> "EmailStep":
        if self.text is None and self.html is None:
            raise document_error(
                f'The email "{self.name}" has no body.',
                "An email needs text, html or both, and PostHog refuses to send one without a body.",
                "Add text: or html: to the step.",
            )
        return self


class WebhookStep(_Step):
    type: Literal["webhook"] = Field(description="Sends an HTTP request.")
    url: str = Field(description="The URL to call. Hog templating works, for example {person.properties.id}.")
    method: Literal["POST", "PUT", "PATCH", "GET", "DELETE"] = Field(default="POST", description="The HTTP method.")
    headers: dict[str, str] | None = Field(default=None, description="HTTP headers to send.")
    body: Any = Field(default=None, description="The JSON body to send.")


class FunctionStep(_Step):
    type: Literal["function"] = Field(description="Runs a function template, such as a destination.")
    template: str = Field(description="The template id, for example template-slack.")
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="The template's inputs by key. Leave secret inputs out: a file cannot carry secrets.",
    )


class PassThroughStep(_Step):
    type: Literal["step"] = Field(description="Any other action, sent to PostHog as written.")
    action_type: PassThroughActionType = Field(description="The action type, for example wait_until_condition.")
    config: dict[str, Any] = Field(description="The action config as the workflows API takes it.")
    branches: list[list["Step"]] = Field(
        default_factory=list,
        description="Steps for each branch of the action, by branch index. A run that takes branch i runs branches[i].",
    )


Step = Annotated[
    Union[DelayStep, BranchStep, EmailStep, WebhookStep, FunctionStep, PassThroughStep], Field(discriminator="type")
]


class Variable(_DocumentModel):
    key: str = Field(description="The variable name. Steps read it as {variables.<key>}.")
    type: Literal["string", "number", "boolean"] = Field(default="string", description="The variable type.")
    default: str = Field(default="", description="The value a run starts with, written as text.")


class Exit(_DocumentModel):
    name: str = Field(
        default="Exit", min_length=1, max_length=400, description="The exit's name in the workflow editor."
    )
    reason: str = Field(default="", description="What PostHog records when a run reaches the end.")
    description: str = Field(default="", description="An optional note about the exit.")


class WorkflowDocument(_DocumentModel):
    model_config = ConfigDict(title="PostHog workflow")

    version: Annotated[Literal[1], BeforeValidator(_only_the_number)] = Field(
        description="The file format version. Always 1."
    )
    key: WorkflowKey = Field(description="The workflow's identity in the project. Changing it creates a new workflow.")
    name: str = Field(min_length=1, max_length=400, description="The workflow name.")
    description: str = Field(default="", description="An optional description.")
    status: Literal["draft", "active"] = Field(
        default="draft", description="draft does not run; active runs. The file wins over a change made in PostHog."
    )
    exit_condition: ExitConditionValue = Field(
        default=HogFlow.ExitCondition.ONLY_AT_END.value, description="When a run leaves the workflow early."
    )
    variables: list[Variable] = Field(default_factory=list, description="Workflow variables.")
    trigger: Trigger = Field(description="What starts a run.")
    steps: list[Step] = Field(description="The steps, in the order a run takes them.")
    exit: Exit = Field(default_factory=Exit, description="The end of the workflow.")


Arm.model_rebuild()
PassThroughStep.model_rebuild()
WorkflowDocument.model_rebuild()
