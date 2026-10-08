"""Generates a new template from metric names that no template in the bank covers.

The model drafts the panels. PostHog checks every query, builds an unlisted preview dashboard with live data,
and renders a picture of it. The model then looks at the picture and corrects the panels, for a few rounds,
until it is satisfied. The template then waits for a staff review, and no team sees it before that.
"""

from __future__ import annotations

import io
import uuid
import hashlib
import datetime as dt
from collections.abc import Sequence

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from PIL import Image

from posthog.dataclasses import frozen
from posthog.models import Team

from products.dashboards.backend.facade.dashboard_creation import delete_unlisted_dashboard
from products.exports.backend.facade.api import read_export_asset_content, render_png_export
from products.metrics.backend.dashboard_import.catalog import CatalogEntry, MetricCatalog
from products.metrics.backend.dashboard_import.layout import RequestedBox, place_screenshot_boxes
from products.metrics.backend.dashboard_import.spec import PanelQuery
from products.metrics.backend.dashboard_import.tiles import insight_query
from products.metrics.backend.dashboard_import.validation import PanelValidator
from products.metrics.backend.metric_attributes_query_runner import (
    MetricAttributeKeysQueryRunner,
    MetricAttributeValuesQueryRunner,
)
from products.metrics.backend.models import MetricsDashboardTemplate
from products.metrics.backend.suggested_dashboards import prompts
from products.metrics.backend.suggested_dashboards.dashboards import acting_user, create_dashboard
from products.metrics.backend.suggested_dashboards.llm import MODEL, ask_model, image_block, text_block
from products.metrics.backend.suggested_dashboards.matching import template_metric_names
from products.metrics.backend.suggested_dashboards.spec import (
    DashboardDraft,
    DraftPanel,
    GenerationRecord,
    GenerationRound,
    PreviewCritique,
    TemplatePanel,
)

logger = structlog.get_logger(__name__)

MAX_ROUNDS = 3
MAX_ATTRIBUTE_METRICS = 24
MAX_ATTRIBUTES_PER_METRIC = 8
# The values of an attribute with this many values or fewer go into the prompt, so that a filter uses a real value.
MAX_LISTED_VALUES = 8
CHECK_DEADLINE_SECONDS = 30.0
PICTURE_TTL = dt.timedelta(days=90)
# Vision models downscale a longer edge, so a tall dashboard goes in parts that keep its text readable.
MAX_PICTURE_EDGE = 1568
MAX_PICTURE_WIDTH = 1200
MAX_PICTURE_PARTS = 4
_HIDDEN_ATTRIBUTES = frozenset({"$originalTimestamp", "service_name", "service.name"})


class RenderFailed(Exception):
    """The image exporter returned no picture. A retry often works, for example after the web server restarted."""


@frozen
class GenerationRequest:
    key: str
    name: str
    description: str
    metric_names: tuple[str, ...]


def generation_key(metric_names: Sequence[str]) -> str:
    digest = hashlib.sha256("\n".join(sorted(set(metric_names))).encode()).hexdigest()
    return f"generated-{digest[:16]}"


def picture_available() -> bool:
    # The pictures come from the image exporter, which renders in a browserless service.
    return bool(settings.BROWSERLESS_CDP_URL)


def _record(template: MetricsDashboardTemplate) -> GenerationRecord:
    return GenerationRecord.model_validate(template.generation or {})


def _save_record(template: MetricsDashboardTemplate, record: GenerationRecord, *fields: str) -> None:
    template.generation = record.model_dump(mode="json")
    template.save(update_fields=["generation", "updated_at", *fields])


def start_generation(team_id: int, request: GenerationRequest) -> str | None:
    """Create the template row. Returns None when the bank already has a template for these metric names."""
    template, created = MetricsDashboardTemplate.objects.get_or_create(
        key=request.key,
        defaults={
            "name": request.name[:200],
            "description": request.description,
            "source": MetricsDashboardTemplate.Source.GENERATED,
            "status": MetricsDashboardTemplate.Status.GENERATING,
            "metric_names": sorted(request.metric_names),
            "source_team_id": team_id,
            "generation": GenerationRecord(model=MODEL, requested_name=request.name).model_dump(mode="json"),
        },
    )
    return str(template.id) if created else None


@frozen
class _Attributes:
    keys: dict[str, list[str]]
    values: dict[str, list[str]]


def _attributes(team: Team, entries: Sequence[CatalogEntry]) -> _Attributes:
    """The attribute keys of each metric, and the values of the keys that have few values."""
    keys: dict[str, list[str]] = {}
    few_values: set[str] = set()
    for entry in entries[:MAX_ATTRIBUTE_METRICS]:
        try:
            rows = MetricAttributeKeysQueryRunner(team, metric_name=entry.name, limit=MAX_ATTRIBUTES_PER_METRIC).run()
        except Exception:
            logger.warning("metrics_suggested_dashboards_attributes_failed", team_id=team.id, metric=entry.name)
            continue
        names = [str(row["name"]) for row in rows if row["name"] not in _HIDDEN_ATTRIBUTES]
        keys[entry.name] = names
        few_values.update(str(row["name"]) for row in rows if 0 < int(row["value_count"]) <= MAX_LISTED_VALUES)
    values: dict[str, list[str]] = {}
    for key in sorted(few_values - _HIDDEN_ATTRIBUTES):
        try:
            rows = MetricAttributeValuesQueryRunner(team, key=key, limit=MAX_LISTED_VALUES).run()
            values[key] = [str(row["name"]) for row in rows]
        except Exception:
            # The values only sharpen the filters, so a failed lookup leaves them out.
            logger.warning("metrics_suggested_dashboards_attribute_values_failed", team_id=team.id, key=key)
    return _Attributes(keys=keys, values=values)


@frozen
class _Context:
    template: MetricsDashboardTemplate
    team: Team
    catalog: MetricCatalog
    entries: tuple[CatalogEntry, ...]


def _context(template_id: str) -> _Context:
    template = MetricsDashboardTemplate.objects.get(id=template_id)
    if template.source_team_id is None:
        raise ValueError("A generated template needs its source team.")
    team = Team.objects.get(id=template.source_team_id)
    catalog = MetricCatalog.load(team)
    catalog.look_up(team, template.metric_names)
    entries = tuple(entry for name in template.metric_names if (entry := catalog.resolve(name)) is not None)
    return _Context(template=template, team=team, catalog=catalog, entries=entries)


@frozen
class _Converted:
    panels: tuple[TemplatePanel, ...]
    accepted: tuple[DraftPanel, ...]
    dropped: tuple[str, ...]


def _convert(drafts: Sequence[DraftPanel], team: Team, catalog: MetricCatalog) -> _Converted:
    """Check each drafted query as PostHog would run it, and keep the panels that pass, with no overlapping boxes."""
    validator = PanelValidator(team=team, catalog=catalog, promql_available=False)
    queries = {draft.key: PanelQuery(language="builder", builder=draft.query) for draft in drafts}
    checks = validator.check_all(queries, deadline_seconds=CHECK_DEADLINE_SECONDS)
    accepted: list[DraftPanel] = []
    queries_by_key: dict[str, dict] = {}
    dropped: list[str] = []
    for draft in drafts:
        check = checks.get(draft.key)
        if draft.key in queries_by_key or check is None or not check.ok:
            dropped.append(draft.title)
            continue
        try:
            queries_by_key[draft.key] = insight_query(
                queries[draft.key], draft.display, catalog=catalog, validator=validator, date_from=None
            )
        except ValueError:
            dropped.append(draft.title)
            continue
        accepted.append(draft)
    boxes = place_screenshot_boxes(
        [RequestedBox(key=draft.key, layout=draft.layout, min_w=2, min_h=2) for draft in accepted]
    )
    panels = tuple(
        TemplatePanel(key=draft.key, title=draft.title[:200], query=queries_by_key[draft.key], layout=boxes[draft.key])
        for draft in accepted
    )
    return _Converted(panels=panels, accepted=tuple(accepted), dropped=tuple(dropped))


def _store_panels(template: MetricsDashboardTemplate, record: GenerationRecord, converted: _Converted) -> None:
    template.panels = [panel.model_dump(mode="json") for panel in converted.panels]
    template.metric_names = template_metric_names(converted.panels) or template.metric_names
    record.draft_panels = list(converted.accepted)
    record.dropped_panels = list(converted.dropped)


def draft_template(template_id: str) -> int:
    """Ask the model for the first version of the panels. Returns how many panels passed the checks."""
    context = _context(template_id)
    template, record = context.template, _record(context.template)
    attributes = _attributes(context.team, context.entries)
    draft = ask_model(
        team_id=context.team.id,
        stage="draft",
        system=prompts.DRAFT_SYSTEM,
        content=[
            text_block(
                prompts.draft_input(
                    name=template.name,
                    description=template.description,
                    entries=context.entries,
                    attributes=attributes.keys,
                    attribute_values=attributes.values,
                )
            )
        ],
        answer_type=DashboardDraft,
    )
    converted = _convert(draft.panels, context.team, context.catalog)
    template.name = " ".join(draft.name.split())[:200] or template.name
    template.description = " ".join(draft.description.split())[:300] or template.description
    _store_panels(template, record, converted)
    record.attributes = attributes.keys
    record.attribute_values = attributes.values
    _save_record(template, record, "name", "description", "panels", "metric_names")
    return len(converted.panels)


def _refresh_preview(context: _Context, round_number: int) -> int | None:
    """Replace the preview dashboard with one that shows the current panels. Returns its id."""
    template = context.template
    user = acting_user(context.team)
    if user is None:
        return None
    if template.preview_dashboard_id and template.preview_team_id:
        delete_unlisted_dashboard(team_id=template.preview_team_id, dashboard_id=template.preview_dashboard_id)
    created, _ = create_dashboard(
        team=context.team,
        user=user,
        name=template.name,
        description=template.description,
        panels=[TemplatePanel.model_validate(panel) for panel in template.panels],
        catalog=context.catalog,
        idempotency_key=f"metrics-template-preview:{template.id}:{round_number}:{uuid.uuid4()}",
        unlisted=True,
    )
    template.preview_team_id = context.team.id if created else None
    template.preview_dashboard_id = created.id if created else None
    template.save(update_fields=["preview_team_id", "preview_dashboard_id", "updated_at"])
    return created.id if created else None


def render_preview(template_id: str, round_number: int) -> int | None:
    """Build the preview dashboard and render a picture of it. Returns the export asset id of the picture.

    Returns None when this deployment cannot render pictures. Raises `RenderFailed` when a render fails.
    """
    context = _context(template_id)
    dashboard_id = _refresh_preview(context, round_number)
    user = acting_user(context.team)
    if dashboard_id is None or user is None or not picture_available():
        return None
    asset, content = render_png_export(
        team=context.team,
        created_by=user,
        dashboard_id=dashboard_id,
        is_system=True,
        expires_after=timezone.now() + PICTURE_TTL,
    )
    if content is None:
        logger.warning("metrics_suggested_dashboards_render_failed", template_id=template_id, error=asset.exception)
        raise RenderFailed(asset.exception or "The image exporter returned no picture.")
    template = MetricsDashboardTemplate.objects.get(id=template_id)
    record = _record(template)
    record.rounds = [item for item in record.rounds if item.round != round_number]
    record.rounds.append(GenerationRound(round=round_number, asset_id=asset.id))
    _save_record(template, record)
    return asset.id


def _model_pictures(png: bytes) -> list[bytes]:
    """The picture at a width the model reads, cut into parts from top to bottom when the dashboard is tall."""
    image: Image.Image = Image.open(io.BytesIO(png))
    if image.width > MAX_PICTURE_WIDTH:
        image = image.resize((MAX_PICTURE_WIDTH, round(image.height * MAX_PICTURE_WIDTH / image.width)))
    parts: list[bytes] = []
    for top in range(0, image.height, MAX_PICTURE_EDGE):
        out = io.BytesIO()
        image.crop((0, top, image.width, min(top + MAX_PICTURE_EDGE, image.height))).save(
            out, format="PNG", optimize=True
        )
        parts.append(out.getvalue())
    return parts[:MAX_PICTURE_PARTS]


def check_preview(template_id: str, round_number: int, *, revise: bool) -> bool:
    """Show the model the picture of a round. Returns True when the model is satisfied.

    With `revise`, a correction from the model replaces the panels, so that the next round renders it.
    """
    context = _context(template_id)
    template, record = context.template, _record(context.template)
    current = next((item for item in record.rounds if item.round == round_number), None)
    png = (
        read_export_asset_content(team_id=context.team.id, asset_id=current.asset_id)
        if current and current.asset_id
        else None
    )
    if current is None or png is None:
        return True
    pictures = _model_pictures(png)
    critique = ask_model(
        team_id=context.team.id,
        stage="critique",
        system=prompts.CRITIQUE_SYSTEM,
        content=[
            *(image_block(picture) for picture in pictures),
            text_block(prompts.picture_note(len(pictures))),
            text_block(
                prompts.critique_input(
                    panels=record.draft_panels,
                    entries=context.entries,
                    attributes=record.attributes,
                    attribute_values=record.attribute_values,
                    dropped=record.dropped_panels,
                )
            ),
        ],
        answer_type=PreviewCritique,
    )
    looks_good = critique.looks_good or not critique.panels
    current.looks_good = critique.looks_good
    current.problems = [" ".join(problem.split())[:300] for problem in critique.problems][:10]
    if not looks_good and revise:
        converted = _convert(critique.panels, context.team, context.catalog)
        if converted.panels:
            current.revised = True
            _store_panels(template, record, converted)
            _save_record(template, record, "panels", "metric_names")
            return False
    _save_record(template, record)
    return looks_good


def finish_generation(template_id: str, *, error: str | None = None) -> None:
    with transaction.atomic():
        template = MetricsDashboardTemplate.objects.select_for_update().get(id=template_id)
        record = _record(template)
        if error is None and not template.panels:
            error = "No drafted panel passed the query checks."
        record.error = error
        template.status = (
            MetricsDashboardTemplate.Status.FAILED if error else MetricsDashboardTemplate.Status.PENDING_REVIEW
        )
        _save_record(template, record, "status")
