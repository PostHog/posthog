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
from collections.abc import Mapping, Sequence
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from PIL import Image

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models import Team
from posthog.ph_client import ph_background_capture
from posthog.utils import absolute_uri

from products.dashboards.backend.facade.dashboard_creation import delete_unlisted_dashboard
from products.exports.backend.facade.api import read_export_asset_content, render_png_export
from products.metrics.backend.dashboard_import.catalog import CatalogEntry, MetricCatalog
from products.metrics.backend.dashboard_import.layout import RequestedBox, place_screenshot_boxes
from products.metrics.backend.dashboard_import.spec import BuilderFilter, PanelQuery
from products.metrics.backend.dashboard_import.tiles import insight_query
from products.metrics.backend.dashboard_import.validation import PanelValidator
from products.metrics.backend.metric_attributes_query_runner import (
    MetricAttributeKeysQueryRunner,
    MetricAttributeValuesQueryRunner,
)
from products.metrics.backend.models import MetricsDashboardTemplate
from products.metrics.backend.suggested_dashboards import prompts
from products.metrics.backend.suggested_dashboards.checks import ProjectChecks, attribute_profile, variable_candidates
from products.metrics.backend.suggested_dashboards.dashboards import (
    SERVICE_ATTRIBUTES,
    acting_user,
    attribute_variable,
    create_dashboard,
    drop_preview,
    fill_rows,
)
from products.metrics.backend.suggested_dashboards.llm import MODEL, ask_model, image_block, text_block
from products.metrics.backend.suggested_dashboards.matching import query_metric_names, template_metric_names
from products.metrics.backend.suggested_dashboards.spec import (
    DashboardDraft,
    DraftPanel,
    DraftVariable,
    GenerationRecord,
    GenerationRound,
    PreviewCritique,
    TemplatePanel,
    template_panels,
)
from products.metrics.backend.suggested_dashboards.timeouts import GENERATE_TIMEOUT
from products.metrics.backend.variables import (
    RANGE_VARIABLES,
    REFERENCE,
    VARIABLE_NAME,
    reference_name,
    referenced_names,
)

logger = structlog.get_logger(__name__)

MAX_ATTRIBUTE_METRICS = 24
MAX_ATTRIBUTES_PER_METRIC = 8
# The values of an attribute with this many values or fewer go into the prompt, so that a filter uses a real value.
MAX_LISTED_VALUES = 8
CHECK_DEADLINE_SECONDS = 30.0
MAX_VARIABLES = 2
PICTURE_TTL = dt.timedelta(days=90)
# A generation that has not saved for this long has stopped: it is longer than the whole workflow may run.
STALE_GENERATION = GENERATE_TIMEOUT + dt.timedelta(hours=1)
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
            "generation": GenerationRecord(
                model=MODEL, requested_name=request.name, requested_metric_names=sorted(request.metric_names)
            ).model_dump(mode="json"),
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
    # MetricsDashboardVariable JSON for the variables that the kept panels refer to.
    variables: tuple[dict[str, Any], ...] = ()
    accepted_variables: tuple[DraftVariable, ...] = ()


@frozen
class _ValidVariables:
    variables: list[DraftVariable]
    # Each variable that selects the same thing as a kept one, by name, with that kept variable.
    replaced: dict[str, tuple[DraftVariable, DraftVariable]]


def _valid_variables(
    drafts: Sequence[DraftVariable], attributes: Mapping[str, Sequence[str]], checks: ProjectChecks | None
) -> _ValidVariables:
    """The drafted variables that list a known attribute with several values, with unique names.

    A variable whose values go one to one with those of an earlier variable selects the same thing, so the earlier
    one replaces it.
    """
    known = {key for keys in attributes.values() for key in keys} | SERVICE_ATTRIBUTES
    valid: list[DraftVariable] = []
    replaced: dict[str, tuple[DraftVariable, DraftVariable]] = {}
    for draft in drafts:
        if len(valid) >= MAX_VARIABLES:
            break
        if (
            not VARIABLE_NAME.match(draft.name)
            or draft.name in RANGE_VARIABLES
            or (draft.attribute not in known and not (checks is not None and checks.knows(draft.attribute)))
            or any(variable.name == draft.name for variable in valid)
        ):
            continue
        if checks is not None and not checks.has_several_values(draft.attribute):
            continue
        equivalent = (
            next((variable for variable in valid if checks.one_to_one(variable.attribute, draft.attribute)), None)
            if checks is not None
            else None
        )
        if equivalent is not None:
            replaced[draft.name] = (draft, equivalent)
            continue
        valid.append(draft)
    return _ValidVariables(variables=valid, replaced=replaced)


def _same_attribute(first: str, second: str) -> bool:
    return first == second or {first, second} <= SERVICE_ATTRIBUTES


def _replace_reference(builder_filter: BuilderFilter, old: DraftVariable, new: DraftVariable) -> BuilderFilter:
    value = REFERENCE.sub(
        lambda match: (
            match.group(0).replace(old.name, new.name, 1) if reference_name(match) == old.name else match.group(0)
        ),
        builder_filter.value,
    )
    key = new.attribute if _same_attribute(builder_filter.key, old.attribute) else builder_filter.key
    return builder_filter.model_copy(update={"key": key, "value": value})


def _with_known_references(draft: DraftPanel, valid: _ValidVariables) -> DraftPanel:
    """The panel without the filters that refer to a variable that the dashboard does not have.

    A filter on a replaced variable filters on the variable that replaced it.
    """
    names = {variable.name for variable in valid.variables}

    def rewritten(builder_filter: BuilderFilter) -> BuilderFilter:
        for name in referenced_names(builder_filter.value):
            if name in valid.replaced:
                builder_filter = _replace_reference(builder_filter, *valid.replaced[name])
        return builder_filter

    clauses = []
    for clause in draft.query.clauses:
        filters: list[BuilderFilter] = []
        for item in map(rewritten, clause.filters):
            if set(referenced_names(item.value)) <= names and item not in filters:
                filters.append(item)
        clauses.append(clause.model_copy(update={"filters": filters}))
    return draft.model_copy(update={"query": draft.query.model_copy(update={"clauses": clauses})})


def _variable_definitions(
    variables: Sequence[DraftVariable], panels: Sequence[DraftPanel], queries: Mapping[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """MetricsDashboardVariable JSON for each variable that a panel refers to.

    Its options are only the values of the metrics of the panels that refer to it, not every value in the project.
    """
    metric_names: dict[str, set[str]] = {}
    for panel in panels:
        names = query_metric_names(queries[panel.key])
        for clause in panel.query.clauses:
            for item in clause.filters:
                for name in referenced_names(item.value):
                    metric_names.setdefault(name, set()).update(names)
    return {
        variable.name: attribute_variable(
            name=variable.name,
            label=" ".join(variable.label.split())[:100],
            attribute=variable.attribute,
            multi=variable.multi,
            metric_names=metric_names[variable.name],
        )
        for variable in variables
        if variable.name in metric_names
    }


def _convert(
    drafts: Sequence[DraftPanel],
    team: Team,
    catalog: MetricCatalog,
    *,
    variables: Sequence[DraftVariable] = (),
    attributes: Mapping[str, Sequence[str]] | None = None,
    checks: ProjectChecks | None = None,
) -> _Converted:
    """Check each drafted query as PostHog would run it, and keep the panels that pass, with no overlapping boxes.

    A drafted variable stays when it lists a known attribute and a kept panel refers to it. It selects All, because
    the template is for every project and a value of the source project must not reach the others. With `checks`,
    each panel also runs in the source project, and a panel whose run fails goes.
    """
    valid = _valid_variables(variables, attributes or {}, checks)
    valid_variables = valid.variables
    drafts = [_with_known_references(draft, valid) for draft in drafts]
    validator = PanelValidator(team=team, catalog=catalog, promql_available=False)
    queries = {draft.key: PanelQuery(language="builder", builder=draft.query) for draft in drafts}
    static_checks = validator.check_all(queries, deadline_seconds=CHECK_DEADLINE_SECONDS)
    accepted: list[DraftPanel] = []
    queries_by_key: dict[str, dict] = {}
    dropped: list[str] = []
    for draft in drafts:
        check = static_checks.get(draft.key)
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
    if checks is not None and accepted:
        errors = checks.run_errors(
            {draft.key: queries_by_key[draft.key] for draft in accepted},
            list(_variable_definitions(valid_variables, accepted, queries_by_key).values()),
        )
        dropped.extend(f"{draft.title}: {errors[draft.key]}" for draft in accepted if draft.key in errors)
        accepted = [draft for draft in accepted if draft.key not in errors]
    boxes = place_screenshot_boxes(
        [RequestedBox(key=draft.key, layout=draft.layout, min_w=2, min_h=2) for draft in accepted]
    )
    # A dropped panel leaves a hole in its row, so the rest of the row spreads across the full width again.
    layouts = fill_rows([(index, boxes[draft.key]) for index, draft in enumerate(accepted)])
    panels = tuple(
        TemplatePanel(key=draft.key, title=draft.title[:200], query=queries_by_key[draft.key], layout=layouts[index])
        for index, draft in enumerate(accepted)
    )
    definitions = _variable_definitions(valid_variables, accepted, queries_by_key)
    kept_variables = tuple(variable for variable in valid_variables if variable.name in definitions)
    return _Converted(
        panels=panels,
        accepted=tuple(accepted),
        dropped=tuple(dropped),
        variables=tuple(definitions[variable.name] for variable in kept_variables),
        accepted_variables=kept_variables,
    )


def _store_panels(template: MetricsDashboardTemplate, record: GenerationRecord, converted: _Converted) -> None:
    template.panels = [panel.model_dump(mode="json") for panel in converted.panels]
    template.variables = list(converted.variables)
    record.draft_panels = list(converted.accepted)
    record.draft_variables = list(converted.accepted_variables)
    record.dropped_panels = list(converted.dropped)


def _checks(context: _Context, value_counts: Mapping[str, int] | None) -> ProjectChecks:
    return ProjectChecks(
        context.team, [entry.name for entry in context.entries], value_counts, deadline=CHECK_DEADLINE_SECONDS
    )


def draft_template(template_id: str) -> int:
    """Ask the model for the first version of the panels. Returns how many panels passed the checks."""
    context = _context(template_id)
    template, record = context.template, _record(context.template)
    attributes = _attributes(context.team, context.entries)
    metric_names = [entry.name for entry in context.entries]
    try:
        profile = attribute_profile(context.team, metric_names)
    except Exception:
        # Without the profile, the dashboard gets no candidates, and a variable is not checked for its values.
        logger.warning("metrics_suggested_dashboards_attribute_profile_failed", team_id=context.team.id)
        profile = None
    candidates = variable_candidates(profile or {}, len(metric_names))
    value_counts = {key: stats.value_count for key, stats in profile.items()} if profile is not None else None
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
                    variable_candidates=candidates,
                )
            )
        ],
        answer_type=DashboardDraft,
    )
    converted = _convert(
        draft.panels,
        context.team,
        context.catalog,
        variables=draft.variables,
        attributes=attributes.keys,
        checks=_checks(context, value_counts),
    )
    template.name = " ".join(draft.name.split())[:200] or template.name
    template.description = " ".join(draft.description.split())[:300] or template.description
    _store_panels(template, record, converted)
    record.attributes = attributes.keys
    record.attribute_values = attributes.values
    record.attribute_value_counts = value_counts
    record.variable_candidates = candidates
    _save_record(template, record, "name", "description", "panels", "variables")
    return len(converted.panels)


def _refresh_preview(context: _Context, round_number: int) -> int | None:
    """Replace the preview dashboard with one that shows the current panels. Returns its id."""
    template = context.template
    user = acting_user(context.team)
    if user is None:
        return None
    if template.preview_dashboard_id and template.preview_team_id:
        delete_unlisted_dashboard(team_id=template.preview_team_id, dashboard_id=template.preview_dashboard_id)
    created, built = create_dashboard(
        team=context.team,
        user=user,
        name=template.name,
        description=template.description,
        panels=template_panels(template.panels),
        catalog=context.catalog,
        idempotency_key=f"metrics-template-preview:{template.id}:{round_number}:{uuid.uuid4()}",
        unlisted=True,
        variables=template.variables or [],
    )
    template.preview_team_id = context.team.id if created else None
    template.preview_dashboard_id = created.id if created else None
    template.preview_unbuilt_keys = list(built.dropped_keys) if created else []
    template.save(update_fields=["preview_team_id", "preview_dashboard_id", "preview_unbuilt_keys", "updated_at"])
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
                    variables=record.draft_variables,
                    entries=context.entries,
                    attributes=record.attributes,
                    attribute_values=record.attribute_values,
                    variable_candidates=record.variable_candidates,
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
        converted = _convert(
            critique.panels,
            context.team,
            context.catalog,
            variables=critique.variables,
            attributes=record.attributes,
            checks=_checks(context, record.attribute_value_counts),
        )
        if converted.panels:
            current.revised = True
            _store_panels(template, record, converted)
            # The preview shows the old panels. A review that approved it would bring them back.
            drop_preview(template)
            _save_record(
                template,
                record,
                "panels",
                "variables",
                "preview_team_id",
                "preview_dashboard_id",
                "preview_unbuilt_keys",
            )
            return False
    _save_record(template, record)
    return looks_good


def finish_generation(template_id: str, *, error: str | None = None) -> None:
    with transaction.atomic():
        template = MetricsDashboardTemplate.objects.select_for_update().get(id=template_id)
        # The workflow and the stale sweep can both try to finish a generation. The first one wins.
        if template.status != MetricsDashboardTemplate.Status.GENERATING:
            return
        record = _record(template)
        if error is None and not template.panels:
            error = "No drafted panel passed the query checks."
        record.error = error
        template.status = (
            MetricsDashboardTemplate.Status.FAILED if error else MetricsDashboardTemplate.Status.PENDING_REVIEW
        )
        if error:
            # Nobody reviews a failed template, so its preview would stay in the project for good.
            drop_preview(template)
        else:
            # The requested names stay during the rounds, so that a revision can use any of them.
            template.metric_names = template_metric_names(template_panels(template.panels)) or template.metric_names
        _save_record(
            template,
            record,
            "status",
            "metric_names",
            "preview_team_id",
            "preview_dashboard_id",
            "preview_unbuilt_keys",
        )
    _capture_generated(template, record)


def fail_stale_generations(now: dt.datetime) -> int:
    """Mark the generations that stopped without finishing as failed, so that their metric names can be proposed again.

    Every step of a generation saves the template, so a template that has not changed for STALE_GENERATION
    belongs to a workflow that timed out or was ended.
    """
    stale = MetricsDashboardTemplate.objects.filter(
        status=MetricsDashboardTemplate.Status.GENERATING, updated_at__lt=now - STALE_GENERATION
    ).values_list("id", flat=True)
    count = 0
    for template_id in list(stale):
        try:
            finish_generation(str(template_id), error="The generation stopped before it finished.")
        except Exception:
            # One broken template must not stop the sweep for every team, nor stay generating for good.
            logger.exception("metrics_suggested_dashboards_stale_generation_not_finished", template_id=str(template_id))
            MetricsDashboardTemplate.objects.filter(
                id=template_id, status=MetricsDashboardTemplate.Status.GENERATING
            ).update(status=MetricsDashboardTemplate.Status.FAILED)
            continue
        count += 1
    return count


def _capture_generated(template: MetricsDashboardTemplate, record: GenerationRecord) -> None:
    team = Team.objects.filter(id=template.source_team_id).first() if template.source_team_id else None
    ph_background_capture()(
        distinct_id=str(team.uuid) if team else str(template.id),
        event="metrics dashboard generated",
        properties={
            "template_id": str(template.id),
            "template_name": template.name,
            "status": template.status,
            "error": record.error,
            "panel_count": len(template.panels or []),
            "dropped_panel_count": len(record.dropped_panels),
            "variable_count": len(template.variables or []),
            "check_rounds": len(record.rounds),
            "looks_good": record.rounds[-1].looks_good if record.rounds else None,
            # No project in the path: the reviewer opens it in their own project, not the source team's.
            "review_url": absolute_uri(f"/metrics/dashboard-review/{template.id}"),
            "$process_person_profile": False,
        },
        groups=groups(team=team) if team else None,
    )
