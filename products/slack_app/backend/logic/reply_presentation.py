"""Slack components picked from a fixed catalog for a finished agent answer.

The catalog is a set of pydantic models. Their JSON schemas are the prompt the presenter model
follows, and the same models validate what comes back, so the prompt and the check cannot drift.

The model writes one component per line, so each component is checked and shown as soon as its
line is complete. A line that fails the check is dropped and recorded, and the others still show.

The model only picks and labels. Every value, cell, and URL must already be in the answer, so a
presentation never shows a number or a page the agent did not give.
"""

import json
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Annotated, Any, Literal

from django.conf import settings

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_ai_gateway_openai_client
from posthog.slack.formatting import escape_slack_mrkdwn

PRESENTATION_MODEL = "gpt-6-luna"
# Online evaluations scope to this call with `slack_app_classifier = reply_presentation`.
PRESENTATION_CLASSIFIER = "reply_presentation"
PRESENTATION_AI_PRODUCT = "slack_app_routing"
# The wait between two streamed chunks. The whole call has its own budget below.
PRESENTATION_READ_TIMEOUT_SECONDS = 8.0
PRESENTATION_BUDGET_SECONDS = 15.0
PRESENTATION_MAX_COMPLETION_TOKENS = 2048
# Long answers keep their head, where the result usually is.
ANSWER_CHARS = 12_000
# Slack asks for at most one edit per second on a message, so two edits a second stay inside it with a margin.
MESSAGE_EDIT_INTERVAL_SECONDS = 0.5

METRIC_LABEL_CHARS = 40
METRIC_VALUE_CHARS = 24
LINK_LABEL_CHARS = 30
TABLE_HEADER_CHARS = 40
TABLE_CELL_CHARS = 80
TABLE_MAX_COLUMNS = 5
TABLE_MAX_ROWS = 20
CHART_TITLE_CHARS = 80
PRESENTATION_LINKS_BLOCK_ID = "slack_app_presentation_links"

ComponentKind = Literal["metric", "link", "table", "resource", "chart"]
ALL_COMPONENT_KINDS: frozenset[ComponentKind] = frozenset({"metric", "link", "table", "resource", "chart"})

COMPONENT_LIMITS: Mapping[ComponentKind, int] = {"metric": 6, "link": 3, "table": 1, "resource": 2, "chart": 1}


class _Component(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricComponent(_Component):
    """A headline number of the answer."""

    type: Literal["metric"]
    label: str = Field(min_length=1, max_length=METRIC_LABEL_CHARS, description="What the number measures.")
    value: str = Field(
        min_length=1, max_length=METRIC_VALUE_CHARS, description="The number exactly as the answer writes it."
    )


class LinkComponent(_Component):
    """A button to a page a reader opens next."""

    type: Literal["link"]
    label: str = Field(min_length=1, max_length=LINK_LABEL_CHARS, description="A short verb phrase in sentence case.")
    url: str = Field(description="An https URL copied exactly from the answer.")


class TableComponent(_Component):
    """A small table of values that the answer lists, such as a breakdown."""

    type: Literal["table"]
    columns: list[Annotated[str, Field(min_length=1, max_length=TABLE_HEADER_CHARS)]] = Field(
        min_length=1, max_length=TABLE_MAX_COLUMNS
    )
    rows: list[list[Annotated[str, Field(max_length=TABLE_CELL_CHARS)]]] = Field(
        min_length=1, max_length=TABLE_MAX_ROWS, description="Each cell copied exactly from the answer."
    )

    @model_validator(mode="after")
    def _rows_match_columns(self) -> "TableComponent":
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("every row needs one cell per column")
        return self


class ResourceComponent(_Component):
    """A card for a PostHog page the answer cites, such as an insight, dashboard, or flag."""

    type: Literal["resource"]
    url: str = Field(description="A PostHog URL copied exactly from the answer.")


class ChartComponent(_Component):
    """The chart of a saved insight the answer cites. It arrives a little after the reply."""

    type: Literal["chart"]
    url: str = Field(description="A PostHog insight URL copied exactly from the answer.")
    title: str = Field(min_length=1, max_length=CHART_TITLE_CHARS)


PresentedComponent = MetricComponent | LinkComponent | TableComponent | ResourceComponent | ChartComponent

_COMPONENT_ADAPTER: TypeAdapter[PresentedComponent] = TypeAdapter(
    Annotated[PresentedComponent, Field(discriminator="type")]  # type: ignore[arg-type]
)
_CATALOG: Mapping[ComponentKind, type[_Component]] = {
    "metric": MetricComponent,
    "link": LinkComponent,
    "table": TableComponent,
    "resource": ResourceComponent,
    "chart": ChartComponent,
}


def catalog_prompt(kinds: frozenset[ComponentKind]) -> str:
    entries = "\n".join(
        f"- {kind} (at most {COMPONENT_LIMITS[kind]}): {_CATALOG[kind].__doc__} Schema: "
        f"{json.dumps(_CATALOG[kind].model_json_schema())}"
        for kind in _CATALOG
        if kind in kinds
    )
    return f"""You choose what a Slack reply shows next to an AI agent's answer.
The answer is already posted as text. You add a few components under it, so a reader sees the result at a glance.

Components:
{entries}

Rules:
- Use only numbers, cells, and URLs that are in the answer. Copy them exactly. Never compute, round, or invent one.
- Pick the components that answer the question, not one for every fact in the text.
- When the answer is a plain explanation, a question back, or a code change with no numbers, write nothing.
- Fewer components are better than weak ones.

Write one component per line as a compact JSON object, in the order a reader should see them. Write nothing else."""


def _normalized(text: str) -> str:
    return " ".join(text.split())


def complete_lines(deltas: Iterable[str]) -> Iterator[str]:
    buffer = ""
    for delta in deltas:
        buffer += delta
        *lines, buffer = buffer.split("\n")
        yield from (line.strip() for line in lines if line.strip())
    if buffer.strip():
        yield buffer.strip()


class ComponentChecker:
    """Checks one line against the catalog, the answer, and the limits. Records why each dropped line failed."""

    def __init__(self, answer_markdown: str, kinds: frozenset[ComponentKind]) -> None:
        self._answer = answer_markdown
        self._normalized_answer = _normalized(answer_markdown)
        self._kinds = kinds
        self.accepted: Counter[str] = Counter()
        self.rejections: list[str] = []

    def check(self, line: str) -> PresentedComponent | None:
        result = self._check(line.strip().removeprefix("```json").strip("`").strip())
        if isinstance(result, str):
            self.rejections.append(result)
            return None
        self.accepted[result.type] += 1
        return result

    def _check(self, line: str) -> PresentedComponent | str:
        try:
            component = _COMPONENT_ADAPTER.validate_json(line)
        except ValidationError as error:
            return "; ".join(f"{'.'.join(str(p) for p in issue['loc'])}: {issue['msg']}" for issue in error.errors())
        if component.type not in self._kinds:
            return f"{component.type}: not offered for this reply"
        if self.accepted[component.type] >= COMPONENT_LIMITS[component.type]:
            return f"{component.type}: over the limit of {COMPONENT_LIMITS[component.type]}"
        error_text = self._grounding_error(component)
        return error_text or component

    def _grounding_error(self, component: PresentedComponent) -> str | None:
        match component:
            case MetricComponent(value=value):
                if _normalized(value) not in self._normalized_answer:
                    return f"metric: value '{value}' is not in the answer"
            case TableComponent(rows=rows):
                missing = [cell for row in rows for cell in row if _normalized(cell) not in self._normalized_answer]
                if missing:
                    return f"table: cells not in the answer: {missing[:3]}"
            case LinkComponent(url=url) | ResourceComponent(url=url) | ChartComponent(url=url):
                if not url.startswith("https://"):
                    return f"{component.type}: use an https URL"
                if url not in self._answer:
                    return f"{component.type}: URL '{url}' is not in the answer"
        return None


def metrics_block(metrics: list[MetricComponent]) -> dict[str, Any]:
    return {
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*{escape_slack_mrkdwn(metric.label)}*\n{escape_slack_mrkdwn(metric.value)}"}
            for metric in metrics
        ],
    }


def links_block(links: list[LinkComponent]) -> dict[str, Any]:
    return {
        "type": "actions",
        "block_id": PRESENTATION_LINKS_BLOCK_ID,
        "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": link.label, "emoji": True}, "url": link.url}
            for link in links
        ],
    }


def table_block(table: TableComponent) -> dict[str, Any]:
    def row(cells: list[str]) -> list[dict[str, str]]:
        # `raw_text` renders the cell as written, so a cell cannot carry a mention or a disguised link.
        return [{"type": "raw_text", "text": cell or " "} for cell in cells]

    return {"type": "table", "rows": [row(table.columns), *(row(cells) for cells in table.rows)]}


@frozen
class _MetricGroup:
    metrics: list[MetricComponent]


@frozen
class _Blocks:
    blocks: tuple[dict[str, Any], ...]


class BlockAssembler:
    """Turns components into blocks in reading order.

    Metrics in a row share one section, and the links close the message in one actions block.
    ``snapshot`` is everything so far, for a message that is edited in place. ``take_settled`` is
    what can no longer change, for a stream that only takes appends: the trailing metric group
    stays open until another component follows it, and the links wait for the end.
    """

    def __init__(self, render_resource: Callable[[str], list[dict[str, Any]] | None]) -> None:
        self._render_resource = render_resource
        self._parts: list[_MetricGroup | _Blocks] = []
        self._links: list[LinkComponent] = []
        self._taken = 0
        self._links_taken = False
        self.charts: list[ChartComponent] = []
        self.unrendered_resources = 0

    def add(self, component: PresentedComponent) -> None:
        match component:
            case MetricComponent():
                if self._parts and isinstance(self._parts[-1], _MetricGroup):
                    self._parts[-1].metrics.append(component)
                else:
                    self._parts.append(_MetricGroup(metrics=[component]))
            case LinkComponent():
                self._links.append(component)
            case ChartComponent():
                self.charts.append(component)
            case TableComponent():
                self._parts.append(_Blocks(blocks=(table_block(component),)))
            case ResourceComponent(url=url):
                blocks = self._render_resource(url)
                if blocks:
                    self._parts.append(_Blocks(blocks=tuple(blocks)))
                else:
                    self.unrendered_resources += 1

    def snapshot(self) -> list[dict[str, Any]]:
        blocks = [block for part in self._parts for block in self._part_blocks(part)]
        return [*blocks, links_block(self._links)] if self._links else blocks

    def take_settled(self, *, final: bool) -> list[dict[str, Any]]:
        end = len(self._parts)
        if not final and self._parts and isinstance(self._parts[-1], _MetricGroup):
            end -= 1
        blocks = [block for part in self._parts[self._taken : end] for block in self._part_blocks(part)]
        self._taken = max(self._taken, end)
        if final and self._links and not self._links_taken:
            self._links_taken = True
            blocks.append(links_block(self._links))
        return blocks

    @staticmethod
    def _part_blocks(part: _MetricGroup | _Blocks) -> list[dict[str, Any]]:
        if isinstance(part, _MetricGroup):
            return [metrics_block(part.metrics)]
        return list(part.blocks)


class ThrottledMessage:
    """One thread message that grows as components arrive. It is posted with the first blocks and
    then edited at most once per interval, and the last edit always carries everything."""

    def __init__(
        self,
        post: Callable[[list[dict[str, Any]]], str | None],
        update: Callable[[str, list[dict[str, Any]]], bool],
        *,
        clock: Callable[[], float] = time.monotonic,
        interval: float = MESSAGE_EDIT_INTERVAL_SECONDS,
    ) -> None:
        self._post = post
        self._update = update
        self._clock = clock
        self._interval = interval
        self._ts: str | None = None
        self._failed = False
        self._shown: list[dict[str, Any]] = []
        self._last_sent = 0.0

    @property
    def ts(self) -> str | None:
        return self._ts

    def show(self, blocks: list[dict[str, Any]], *, final: bool = False) -> None:
        if self._failed or not blocks or blocks == self._shown:
            return
        if self._ts is None:
            self._ts = self._post(blocks)
            self._failed = self._ts is None
        elif final or self._clock() - self._last_sent >= self._interval:
            self._failed = not self._update(self._ts, blocks)
        else:
            return
        self._shown = blocks
        self._last_sent = self._clock()


@frozen
class PresentationAttribution:
    trace_id: str | None = None
    distinct_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    privacy_mode: bool = False


@frozen
class PresentationOutcome:
    accepted: Mapping[str, int]
    rejections: tuple[str, ...]
    charts: tuple[ChartComponent, ...]
    unrendered_resources: int
    first_component_ms: int | None
    # Set when the model call stopped early. The components that arrived before still show.
    error: str | None = None


def presentation_deltas(
    answer_markdown: str,
    kinds: frozenset[ComponentKind],
    attribution: PresentationAttribution,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[str]:
    properties = {"slack_app_classifier": PRESENTATION_CLASSIFIER}
    if attribution.task_id:
        properties["task_id"] = attribution.task_id
    if attribution.run_id:
        properties["run_id"] = attribution.run_id
    client = build_ai_gateway_openai_client(
        settings.AI_GATEWAY_API_KEY,
        ai_product=PRESENTATION_AI_PRODUCT,
        trace_id=attribution.trace_id,
        distinct_id=attribution.distinct_id,
        properties=properties,
    ).with_options(timeout=PRESENTATION_READ_TIMEOUT_SECONDS, max_retries=0)
    extra: dict[str, Any] = {"user": attribution.distinct_id} if attribution.distinct_id else {}
    if attribution.privacy_mode:
        extra["extra_headers"] = {"X-PostHog-Privacy-Mode": "true"}
    deadline = clock() + PRESENTATION_BUDGET_SECONDS
    stream = client.chat.completions.create(
        model=PRESENTATION_MODEL,
        messages=[
            {"role": "system", "content": catalog_prompt(kinds)},
            {"role": "user", "content": f"<agent_answer>\n{answer_markdown[:ANSWER_CHARS]}\n</agent_answer>"},
        ],
        max_completion_tokens=PRESENTATION_MAX_COMPLETION_TOKENS,
        stream=True,
        **extra,
    )
    for chunk in stream:
        if clock() > deadline:
            raise TimeoutError("reply presentation ran past its budget")
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def present_components(
    deltas: Iterable[str],
    checker: ComponentChecker,
    assembler: BlockAssembler,
    deliver: Callable[[BlockAssembler, bool], None],
    *,
    clock: Callable[[], float] = time.monotonic,
) -> PresentationOutcome:
    """Feeds each checked component to ``deliver`` as soon as its line is complete, then once more with
    ``final`` set. A failed call still delivers what arrived before it, so one bad chunk costs only the rest."""
    started = clock()
    first_component_ms: int | None = None
    error: str | None = None
    try:
        for line in complete_lines(deltas):
            component = checker.check(line)
            if component is None:
                continue
            if first_component_ms is None:
                first_component_ms = int((clock() - started) * 1000)
            assembler.add(component)
            deliver(assembler, False)
    except Exception as exception:
        error = type(exception).__name__
    deliver(assembler, True)
    return PresentationOutcome(
        accepted=dict(checker.accepted),
        rejections=tuple(checker.rejections),
        charts=tuple(assembler.charts),
        unrendered_resources=assembler.unrendered_resources,
        first_component_ms=first_component_ms,
        error=error,
    )
