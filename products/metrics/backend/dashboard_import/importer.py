"""Runs a dashboard import from a Grafana dashboard JSON model or from a screenshot.

The import first converts every panel it can convert without AI: text panels, unsupported panels, and
PromQL panels whose metrics exist and whose query runs. When nothing is left, it creates the dashboard
at once. Otherwise it starts an internal agent task for the rest. When the task ends, a task run receiver
and the status endpoint both call `finalize`. It checks every query that the agent returned again, as
the user, and creates the dashboard in the same transaction that records the result. So the dashboard
exists once, whichever caller gets there first.

The agent only reads data and answers. It has read-only scopes and no network, so instructions planted
in a shared dashboard JSON can change nothing in the project.
"""

from __future__ import annotations

import io
import json
import uuid
import datetime as dt
from collections.abc import Iterable, Sequence
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

import structlog
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG
from posthog.event_usage import groups, report_user_action
from posthog.models import Team, User
from posthog.permissions import posthog_feature_flag_enabled
from posthog.ph_client import ph_scoped_capture
from posthog.storage import object_storage

from products.dashboards.backend.facade.dashboard_creation import (
    DashboardCreationDenied,
    NewDashboard,
    NewInsightTile,
    NewTextTile,
    TileLayout,
    create_dashboard_with_tiles,
)
from products.metrics.backend.dashboard_import.catalog import HISTOGRAM_TYPES, MetricCatalog
from products.metrics.backend.dashboard_import.grafana import GrafanaDashboardParser, GrafanaImportError
from products.metrics.backend.dashboard_import.layout import GridPacker
from products.metrics.backend.dashboard_import.prompt import (
    BRIEF_FILE_NAME,
    GRAFANA_FILE_NAME,
    SCREENSHOT_FILE_NAME,
    build_brief,
    build_prompt,
)
from products.metrics.backend.dashboard_import.promql_text import combine_targets, metric_names
from products.metrics.backend.dashboard_import.spec import (
    AgentImportOutput,
    AgentPanel,
    DashboardSpec,
    DisplaySpec,
    GridLayout,
    ImportResult,
    ImportSource,
    ImportState,
    ImportSummary,
    PanelOutcome,
    PanelQuery,
    PanelSpec,
    PanelVerdict,
    TileDraft,
)
from products.metrics.backend.dashboard_import.tiles import insight_query, insight_tile, text_tile
from products.metrics.backend.dashboard_import.validation import PanelValidator, QueryCheck
from products.metrics.backend.facade.contracts import (
    DashboardImportError,
    DashboardImportInProgress,
    DashboardImportNotAllowed,
    DashboardImportPanel,
    DashboardImportRequest,
    DashboardImportStatus,
    DashboardImportSummary,
    PanelQueryCheckRequest,
    PanelQueryCheckResult,
)
from products.metrics.backend.facade.enums import DashboardImportSource, DashboardImportState, PanelImportOutcome
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO, TaskRunInputFile

logger = structlog.get_logger(__name__)

IMPORT_STATE_KEY = "metrics_dashboard_import"
SANDBOX_ENVIRONMENT_NAME = "METRICS_DASHBOARD_IMPORT"
AGENT_MODEL = "claude-sonnet-5"
AGENT_RUNTIME_ADAPTER = "claude"
# The PostHog MCP server reads the user and the project to start a session, so it needs user:read and
# project:read. The rest lets the agent read metrics, logs and traces. Nothing lets it write.
AGENT_MCP_SCOPES = ["metrics:read", "logs:read", "tracing:read", "user:read", "project:read"]
# Read tools that the internal scopes unlock but the conversion never needs. The input can carry planted
# instructions, so hide every tool that reads other data of the user.
AGENT_HIDDEN_TOOLS = [
    "docs-search",
    "user-get",
    "user-home-settings-get",
    "llma-personal-spend",
    "reminder-get",
    "reminders-list",
    "mcp-connections-list",
    "mcp-connection-tools-list",
    "tasks-list",
    "tasks-retrieve",
    "tasks-runs-list",
    "tasks-runs-retrieve",
    "tasks-runs-session-logs-retrieve",
    "tasks-artifacts-list",
    "tasks-config-list",
    "tasks-me-config-list",
    "tasks-models-retrieve",
    "channel-list",
    "channel-retrieve",
    "channel-instructions-retrieve",
    "inbox-reports-list",
    "inbox-reports-retrieve",
    "task-context-wiki-channel-resolve",
    "task-context-wiki-page-retrieve",
]
START_CHECK_SECONDS = 20.0
FINAL_CHECK_SECONDS = 60.0
# A finalizer that holds the claim longer than this died before it saved a result, so another may take over.
CLAIM_TIMEOUT = dt.timedelta(minutes=5)
MAX_GRAFANA_JSON_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
# Vision models downscale larger images, so a larger upload only adds bytes.
MAX_IMAGE_EDGE = 1568
STORAGE_PREFIX = "metrics_dashboard_imports"
STORAGE_TTL_DAYS = "30"
DEFAULT_SCREENSHOT_LAYOUT = GridLayout(x=0, y=0, w=6, h=4)
_QUERY_KINDS = frozenset({"timeseries", "stat", "gauge", "bargauge", "table", "heatmap"})
_AGENT_FAILED_MESSAGE = "The import agent stopped before it finished. Try again."
_RUNNING_PROGRESS = "Starting the import agent."
_FINALIZING_PROGRESS = "Building the dashboard."


def promql_available(team: Team, user: User) -> bool:
    return bool(settings.SNUFFLE_APM_URL) and posthog_feature_flag_enabled(
        SNUFFLE_API_FEATURE_FLAG,
        str(user.distinct_id),
        organization_id=team.organization_id,
        team_id=team.pk,
    )


def _parse_state(raw: object) -> ImportState | None:
    if not isinstance(raw, dict):
        return None
    try:
        return ImportState.model_validate(raw)
    except ValidationError:
        logger.warning("metrics_dashboard_import_state_invalid")
        return None


def _status_from_result(*, import_id: str | None, state: ImportState, result: ImportResult) -> DashboardImportStatus:
    return DashboardImportStatus(
        id=import_id,
        source=DashboardImportSource(state.source),
        status=DashboardImportState(result.status),
        dashboard_name=state.dashboard_name,
        dashboard_id=result.dashboard_id,
        error=result.error,
        summary=DashboardImportSummary(**result.summary.model_dump()),
        panels=tuple(
            DashboardImportPanel(
                key=verdict.key,
                title=verdict.title,
                outcome=PanelImportOutcome(verdict.outcome),
                reason=verdict.reason,
            )
            for verdict in result.panels
        ),
    )


class PanelResolver:
    """Converts the panels that need no AI, and checks the PromQL panels that already match this project."""

    def __init__(self, *, catalog: MetricCatalog, validator: PanelValidator, promql_available: bool) -> None:
        self._catalog = catalog
        self._validator = validator
        self._promql_available = promql_available

    def resolve(self, spec: DashboardSpec) -> tuple[list[PanelVerdict], dict[str, QueryCheck]]:
        verdicts: dict[str, PanelVerdict] = {}
        queries: dict[str, PanelQuery] = {}
        for panel in spec.panels:
            if panel.skip_reason:
                verdicts[panel.key] = PanelVerdict(
                    key=panel.key, title=panel.title, outcome="skipped", reason=panel.skip_reason
                )
            elif panel.kind in ("row", "text") and panel.text:
                verdicts[panel.key] = PanelVerdict(
                    key=panel.key,
                    title=panel.title,
                    outcome="approximated" if panel.notes else "imported",
                    reason=" ".join(panel.notes),
                    tile=text_tile(name=panel.title, text=panel.text, layout=panel.layout),
                )
            elif query := self._direct_query(panel):
                queries[panel.key] = query
        checks = self._validator.check_all(queries, deadline_seconds=START_CHECK_SECONDS)
        panels = {panel.key: panel for panel in spec.panels}
        for key, check in checks.items():
            if check.ok:
                panel = panels[key]
                verdicts[key] = PanelVerdict(
                    key=key,
                    title=panel.title,
                    outcome="approximated" if panel.notes else "imported",
                    reason=" ".join([*panel.notes, *check.notes]),
                    tile=insight_tile(
                        name=panel.title,
                        description=_insight_description(panel.description, panel.notes),
                        query=insight_query(
                            queries[key],
                            panel.display,
                            catalog=self._catalog,
                            validator=self._validator,
                            date_from=spec.date_from,
                        ),
                        layout=panel.layout,
                    ),
                )
        return [verdicts[panel.key] for panel in spec.panels if panel.key in verdicts], checks

    def _direct_query(self, panel: PanelSpec) -> PanelQuery | None:
        if not self._promql_available or panel.kind not in _QUERY_KINDS or not panel.targets:
            return None
        if any(target.language != "promql" or target.unresolved_variables for target in panel.targets):
            return None
        if panel.kind == "heatmap":
            names = metric_names(panel.targets[0].expr) if len(panel.targets) == 1 else []
            entry = self._catalog.resolve(names[0]) if len(names) == 1 and names[0].endswith("_bucket") else None
            if entry is None or entry.metric_type not in HISTOGRAM_TYPES:
                return None
            return PanelQuery(language="histogram", histogram_metric=entry.name)
        return PanelQuery(
            language="promql", promql=combine_targets([(target.ref_id, target.expr) for target in panel.targets])
        )


def _query_metric_names(queries: Iterable[PanelQuery]) -> list[str]:
    names: list[str] = []
    for query in queries:
        names.extend(metric_names(query.promql or ""))
        names.extend(clause.metric_name for clause in (query.builder.clauses if query.builder else []))
        if query.histogram_metric:
            names.append(query.histogram_metric)
    return names


def _insight_description(description: str, notes: list[str]) -> str:
    parts = [description] if description else []
    if notes:
        parts.append("Import notes: " + " ".join(notes))
    return "\n\n".join(parts)


class DashboardImporter:
    def __init__(self, *, team: Team, user: User) -> None:
        self._team = team
        self._user = user

    def start(self, request: DashboardImportRequest) -> DashboardImportStatus:
        self._check_allowed()
        source: ImportSource = "grafana" if request.source == DashboardImportSource.GRAFANA else "screenshot"
        spec = self._parse_grafana(request.grafana_json) if source == "grafana" else None
        image = self._prepare_image(request.image) if source == "screenshot" else None
        promql = promql_available(self._team, self._user)
        catalog = MetricCatalog.load(self._team)
        validator = PanelValidator(team=self._team, catalog=catalog, promql_available=promql)
        name = " ".join((request.name or "").split())[:400] or (spec.title if spec else "Imported dashboard")

        resolved: list[PanelVerdict] = []
        checks: dict[str, QueryCheck] = {}
        if spec is not None:
            catalog.look_up(
                self._team,
                (
                    metric
                    for panel in spec.panels
                    for target in panel.targets
                    if target.language == "promql"
                    for metric in metric_names(target.expr)
                ),
            )
            resolved, checks = PanelResolver(catalog=catalog, validator=validator, promql_available=promql).resolve(
                spec
            )

        state = ImportState(
            source=source,
            user_id=self._user.id,
            dashboard_name=name,
            date_from=spec.date_from if spec else None,
            promql_available=promql,
            spec=spec,
            resolved=resolved,
            started_at=timezone.now().isoformat(),
        )
        if spec is not None and len(resolved) == len(spec.panels):
            result = self._build(state, resolved, idempotency_key=uuid.uuid4().hex)
            self._capture_started(state, path="direct", panel_count=len(spec.panels))
            self.capture_finished(state, result, path="direct", background=False)
            return _status_from_result(import_id=None, state=state, result=result)

        files = self._upload_inputs(
            source=source,
            brief=build_brief(
                source=source, spec=spec, resolved=resolved, checks=checks, catalog=catalog, promql_available=promql
            ),
            grafana_json=request.grafana_json,
            image=image,
        )
        try:
            task_id = self._start_task(
                state.model_copy(update={"input_paths": [file.storage_path for file in files]}), files
            )
        except Exception:
            _delete_inputs([file.storage_path for file in files])
            raise
        self._capture_started(state, path="agent", panel_count=len(spec.panels) if spec else None)
        return DashboardImportStatus(
            id=task_id,
            source=request.source,
            status=DashboardImportState.RUNNING,
            dashboard_name=name,
            progress=_RUNNING_PROGRESS,
        )

    def status(self, import_id: str) -> DashboardImportStatus | None:
        run = tasks_facade.get_owner_origin_latest_run(
            task_id=import_id,
            team_id=self._team.id,
            created_by_id=self._user.id,
            origin_product=tasks_facade.TaskOriginProduct.METRICS_IMPORT,
        )
        if run is None:
            return None
        state = _parse_state(tasks_facade.read_task_state_entry(import_id, self._team.id, IMPORT_STATE_KEY))
        if state is None:
            return None
        if state.result is None and run.is_terminal:
            finalize_import(team_id=self._team.id, task_id=import_id, background=False)
            state = (
                _parse_state(tasks_facade.read_task_state_entry(import_id, self._team.id, IMPORT_STATE_KEY)) or state
            )
        if state.result is not None:
            return _status_from_result(import_id=import_id, state=state, result=state.result)
        progress = run.state.get(tasks_facade.TASK_RUN_SUMMARY_STATE_KEY)
        return DashboardImportStatus(
            id=import_id,
            source=DashboardImportSource(state.source),
            status=DashboardImportState.RUNNING,
            dashboard_name=state.dashboard_name,
            progress=_FINALIZING_PROGRESS
            if run.is_terminal
            else (progress if isinstance(progress, str) and progress else _RUNNING_PROGRESS),
        )

    def _check_allowed(self) -> None:
        if self._team.organization.is_ai_data_processing_approved is not True:
            raise DashboardImportNotAllowed(
                "Turn on AI data processing in the organization settings to import dashboards."
            )
        # Deferred because ee is optional, and a self-hosted build without it has no AI credits to check.
        try:
            from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited  # noqa: PLC0415
        except ImportError:
            return
        if is_team_limited(self._team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
            raise DashboardImportNotAllowed(
                "Your organization used all of its AI credits. Check your billing settings, then try again."
            )

    @staticmethod
    def _parse_grafana(grafana_json: str | None) -> DashboardSpec:
        if not grafana_json or not grafana_json.strip():
            raise DashboardImportError("Paste the Grafana dashboard JSON.")
        if len(grafana_json.encode()) > MAX_GRAFANA_JSON_BYTES:
            raise DashboardImportError("The dashboard JSON is larger than 5 MB.")
        try:
            raw = json.loads(grafana_json)
        except json.JSONDecodeError as error:
            raise DashboardImportError(f"The text is not valid JSON: {error.msg} on line {error.lineno}.") from None
        try:
            return GrafanaDashboardParser(raw).parse()
        except GrafanaImportError as error:
            raise DashboardImportError(str(error)) from None

    @staticmethod
    def _prepare_image(image: bytes | None) -> bytes:
        if not image:
            raise DashboardImportError("Add a screenshot of the dashboard.")
        if len(image) > MAX_IMAGE_BYTES:
            raise DashboardImportError("The screenshot is larger than 5 MB.")
        try:
            with Image.open(io.BytesIO(image)) as opened:
                if opened.format not in ("PNG", "JPEG", "WEBP", "GIF"):
                    raise DashboardImportError("Use a PNG, JPEG, WebP or GIF screenshot.")
                if opened.width * opened.height > MAX_IMAGE_PIXELS:
                    raise DashboardImportError("The screenshot has too many pixels. Use a smaller image.")
                picture = opened.convert("RGB")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise DashboardImportError(
                "PostHog cannot read this file as an image. Use a PNG or JPEG screenshot."
            ) from None
        longest = max(picture.size)
        if longest > MAX_IMAGE_EDGE:
            scale = MAX_IMAGE_EDGE / longest
            picture = picture.resize(
                (max(1, int(picture.width * scale)), max(1, int(picture.height * scale))), Image.Resampling.LANCZOS
            )
        buffer = io.BytesIO()
        picture.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    def _upload_inputs(
        self, *, source: ImportSource, brief: bytes, grafana_json: str | None, image: bytes | None
    ) -> list[TaskRunInputFile]:
        folder = f"{STORAGE_PREFIX}/{self._team.id}/{uuid.uuid4().hex}"
        contents: list[tuple[str, bytes, str]] = [(BRIEF_FILE_NAME, brief, "application/json")]
        if source == "grafana" and grafana_json:
            contents.append((GRAFANA_FILE_NAME, grafana_json.encode(), "application/json"))
        if source == "screenshot" and image:
            contents.append((SCREENSHOT_FILE_NAME, image, "image/png"))
        files: list[TaskRunInputFile] = []
        for file_name, content, content_type in contents:
            path = f"{folder}/{file_name}"
            object_storage.write(path, content)
            try:
                object_storage.tag(path, {"ttl_days": STORAGE_TTL_DAYS, "team_id": str(self._team.id)})
            except Exception:
                logger.warning("metrics_dashboard_import_tag_failed", team_id=self._team.id)
            files.append(
                TaskRunInputFile(
                    id=file_name, name=file_name, storage_path=path, size_bytes=len(content), content_type=content_type
                )
            )
        return files

    def _start_task(self, state: ImportState, files: list[TaskRunInputFile]) -> str:
        prompt = build_prompt(source=state.source, promql_available=state.promql_available)

        def bind_inputs(run_id: uuid.UUID) -> dict[str, Any]:
            bound = [
                TaskRunInputFile(
                    id=str(uuid.uuid5(run_id, file.id)),
                    name=file.name,
                    storage_path=file.storage_path,
                    size_bytes=file.size_bytes,
                    content_type=file.content_type,
                )
                for file in files
            ]
            tasks_facade.attach_task_run_input_files(team_id=self._team.id, run_id=run_id, files=bound)
            return {
                "pending_user_message": prompt,
                # The agent server and the dispatch workflow must see the same id for the first message.
                "pending_user_message_id": str(run_id),
                "pending_user_artifact_ids": [file.id for file in bound],
                "mcp_gateway_server_ids": [],
            }

        with transaction.atomic():
            self._admit()
            environment_id = tasks_facade.upsert_internal_sandbox_env(
                self._team.id,
                SANDBOX_ENVIRONMENT_NAME,
                tasks_facade.SandboxNetworkAccessLevel.CUSTOM,
                private=False,
                internal=True,
                allowed_domains=[],
                include_default_domains=False,
            )
            created = tasks_facade.create_and_run_task(
                team=self._team,
                title=f"Import dashboard: {state.dashboard_name}"[:255],
                description=prompt,
                origin_product=tasks_facade.TaskOriginProduct.METRICS_IMPORT,
                user_id=self._user.id,
                repository=None,
                create_pr=False,
                internal=True,
                sandbox_environment_id=str(environment_id),
                posthog_mcp_scopes=AGENT_MCP_SCOPES,
                model=AGENT_MODEL,
                runtime_adapter=AGENT_RUNTIME_ADAPTER,
                output_schema=AgentImportOutput,
                extra_run_state={
                    "mcp_exclude_tools": AGENT_HIDDEN_TOOLS,
                    "config_snapshot": {"connectors": {"mcp_installation_ids": []}},
                },
                before_task_dispatch=bind_inputs,
            )
            task_id = str(created.task_id)
            initial = state.model_dump(mode="json")
            tasks_facade.update_task_state_entry(
                task_id, self._team.id, IMPORT_STATE_KEY, lambda _current: (initial, None)
            )
        return task_id

    def _admit(self) -> None:
        # Transaction-scoped, so two requests from one user cannot both pass the check below.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"metrics_dashboard_import:{self._team.id}:{self._user.id}"],
            )
        if tasks_facade.owner_origin_has_non_terminal_run(
            team_id=self._team.id,
            created_by_id=self._user.id,
            origin_product=tasks_facade.TaskOriginProduct.METRICS_IMPORT,
        ):
            raise DashboardImportInProgress("You already have an import that is running. Wait for it to finish.")

    def _build(self, state: ImportState, verdicts: list[PanelVerdict], *, idempotency_key: str) -> ImportResult:
        """Create the dashboard from the verdicts. A dashboard without an insight tile is not created."""
        summary = ImportSummary.from_verdicts(verdicts)
        tiles = [verdict.tile for verdict in verdicts if verdict.tile is not None]
        if not any(tile.kind == "insight" for tile in tiles):
            return ImportResult(
                status="failed",
                error="No panel could be imported, so no dashboard was created.",
                summary=summary,
                panels=verdicts,
            )
        try:
            created = create_dashboard_with_tiles(
                team_id=self._team.id,
                user_id=self._user.id,
                dashboard=NewDashboard(
                    name=state.dashboard_name,
                    description=_dashboard_description(state),
                    tiles=tuple(_new_tile(tile) for tile in tiles),
                    idempotency_key=idempotency_key,
                    date_from=state.date_from,
                ),
            )
        except DashboardCreationDenied as error:
            return ImportResult(status="failed", error=str(error), summary=summary, panels=verdicts)
        return ImportResult(status="completed", dashboard_id=created.id, summary=summary, panels=verdicts)

    def agent_verdicts(self, state: ImportState, output: AgentImportOutput) -> list[PanelVerdict]:
        """Check the agent's answer as the user, and merge it with the panels that the import resolved itself."""
        catalog = MetricCatalog.load(self._team)
        validator = PanelValidator(team=self._team, catalog=catalog, promql_available=state.promql_available)
        spec_panels = {panel.key: panel for panel in state.spec.panels} if state.spec else {}
        resolved_keys = {verdict.key for verdict in state.resolved}
        answers: dict[str, AgentPanel] = {}
        for answer in output.panels:
            known = answer.key in spec_panels if state.spec else True
            if known and answer.key not in resolved_keys and answer.key not in answers:
                answers[answer.key] = answer
        queries = {
            key: answer.query
            for key, answer in answers.items()
            if answer.outcome in ("imported", "approximated") and answer.query is not None
        }
        catalog.look_up(self._team, _query_metric_names(queries.values()))
        checks = validator.check_all(queries, deadline_seconds=FINAL_CHECK_SECONDS)

        packer = GridPacker()
        agent_verdicts: dict[str, PanelVerdict] = {}
        ordered = sorted(
            answers.values(), key=lambda answer: (answer.layout.y, answer.layout.x) if answer.layout else (0, 0)
        )
        for answer in ordered if state.spec is None else answers.values():
            spec_panel = spec_panels.get(answer.key)
            title = spec_panel.title if spec_panel else (" ".join(answer.title.split())[:200] or "Untitled panel")
            if spec_panel is not None:
                layout = spec_panel.layout
            else:
                requested = answer.layout or DEFAULT_SCREENSHOT_LAYOUT
                layout = packer.place(x=requested.x, w=requested.w, h=requested.h)
            agent_verdicts[answer.key] = self._agent_verdict(
                answer, spec_panel, title, layout, checks.get(answer.key), catalog, validator, state.date_from
            )

        merged: list[PanelVerdict] = []
        if state.spec is not None:
            resolved = {verdict.key: verdict for verdict in state.resolved}
            for panel in state.spec.panels:
                if panel.key in resolved:
                    merged.append(resolved[panel.key])
                elif panel.key in agent_verdicts:
                    merged.append(agent_verdicts[panel.key])
                else:
                    merged.append(
                        PanelVerdict(
                            key=panel.key,
                            title=panel.title,
                            outcome="failed",
                            reason="The import agent did not convert this panel.",
                        )
                    )
        else:
            merged = list(agent_verdicts.values())
        return merged

    def _agent_verdict(
        self,
        answer: AgentPanel,
        spec_panel: PanelSpec | None,
        title: str,
        layout: GridLayout,
        check: QueryCheck | None,
        catalog: MetricCatalog,
        validator: PanelValidator,
        date_from: str | None,
    ) -> PanelVerdict:
        reason = " ".join(answer.reason.split())[:500]
        if answer.outcome in ("skipped", "failed"):
            return PanelVerdict(
                key=answer.key, title=title, outcome=answer.outcome, reason=reason or "The panel was not converted."
            )
        if answer.query is None:
            if answer.text and spec_panel is None:
                return PanelVerdict(
                    key=answer.key,
                    title=title,
                    outcome="imported",
                    tile=text_tile(name=title, text=answer.text[:4000], layout=layout),
                )
            return PanelVerdict(
                key=answer.key, title=title, outcome="failed", reason="The import agent returned no query."
            )
        if check is None or not check.ok:
            error = check.error if check is not None else None
            return PanelVerdict(
                key=answer.key, title=title, outcome="failed", reason=error or "The query did not pass the check."
            )
        # The parser maps a Grafana panel's display exactly, so only a screenshot panel takes the agent's display.
        display = spec_panel.display if spec_panel is not None else (answer.display or DisplaySpec())
        notes = [*(spec_panel.notes if spec_panel else []), *([reason] if reason else [])]
        outcome: PanelOutcome = (
            "approximated" if answer.outcome == "approximated" or (spec_panel and spec_panel.notes) else "imported"
        )
        return PanelVerdict(
            key=answer.key,
            title=title,
            outcome=outcome,
            reason=" ".join([*notes, *check.notes]),
            tile=insight_tile(
                name=title,
                description=_insight_description(spec_panel.description if spec_panel else "", notes),
                query=insight_query(answer.query, display, catalog=catalog, validator=validator, date_from=date_from),
                layout=layout,
            ),
        )

    def record(
        self, task_id: str, state: ImportState, verdicts: list[PanelVerdict] | None, error: str | None
    ) -> ImportResult | None:
        """Create the dashboard and save the result while the task row is locked, unless a result exists."""

        def update(current: Any) -> tuple[Any, ImportResult | None]:
            latest = _parse_state(current)
            if latest is None or latest.result is not None:
                return current, None
            if verdicts is None:
                result = ImportResult(
                    status="failed",
                    error=error or _AGENT_FAILED_MESSAGE,
                    summary=ImportSummary.from_verdicts([]),
                    panels=[],
                )
            else:
                result = self._build(latest, verdicts, idempotency_key=task_id)
            return latest.model_copy(update={"result": result, "finalizing_since": None}).model_dump(
                mode="json"
            ), result

        return tasks_facade.update_task_state_entry(task_id, self._team.id, IMPORT_STATE_KEY, update)

    def _capture_started(self, state: ImportState, *, path: str, panel_count: int | None) -> None:
        report_user_action(
            self._user,
            "metrics dashboard import started",
            {
                "source": state.source,
                "path": path,
                "panel_count": panel_count,
                "resolved_without_agent": len(state.resolved),
                "promql_available": state.promql_available,
            },
            team=self._team,
        )

    def capture_finished(self, state: ImportState, result: ImportResult, *, path: str, background: bool) -> None:
        started = dt.datetime.fromisoformat(state.started_at)
        properties = {
            "source": state.source,
            "path": path,
            "status": result.status,
            "dashboard_id": result.dashboard_id,
            "duration_seconds": round((timezone.now() - started).total_seconds(), 1),
            **result.summary.model_dump(),
        }
        if not background:
            report_user_action(self._user, "metrics dashboard import finished", properties, team=self._team)
            return
        # A Celery worker can exit before the shared client flushes, so a background caller sends through its own.
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=str(self._user.distinct_id),
                event="metrics dashboard import finished",
                properties=properties,
                groups=groups(self._team.organization, self._team),
            )


def _dashboard_description(state: ImportState) -> str:
    if state.source == "screenshot":
        return "Imported from a screenshot."
    description = state.spec.description if state.spec else ""
    variables = ", ".join(
        f"{name} = {value or 'none'}" for name, value in (state.spec.variables if state.spec else {}).items()
    )
    parts = [description] if description else []
    parts.append("Imported from Grafana." + (f" Variables: {variables}." if variables else ""))
    return " ".join(parts)


def _new_tile(tile: TileDraft) -> NewInsightTile | NewTextTile:
    layout = TileLayout(x=tile.layout.x, y=tile.layout.y, w=tile.layout.w, h=tile.layout.h)
    if tile.kind == "text":
        return NewTextTile(body=tile.text or "", layout=layout)
    return NewInsightTile(name=tile.name, description=tile.description, query=tile.query or {}, layout=layout)


def _delete_inputs(paths: list[str]) -> None:
    for path in paths:
        try:
            object_storage.delete(path)
        except Exception:
            logger.warning("metrics_dashboard_import_input_delete_failed")


def _claim(team_id: int, task_id: str) -> ImportState | None:
    now = timezone.now()

    def update(current: Any) -> tuple[Any, ImportState | None]:
        state = _parse_state(current)
        if state is None or state.result is not None:
            return current, None
        if state.finalizing_since and now - dt.datetime.fromisoformat(state.finalizing_since) < CLAIM_TIMEOUT:
            return current, None
        claimed = state.model_copy(update={"finalizing_since": now.isoformat()})
        return claimed.model_dump(mode="json"), claimed

    return tasks_facade.update_task_state_entry(task_id, team_id, IMPORT_STATE_KEY, update)


def _run_failure(run: TaskRunDTO | None) -> str | None:
    if run is None:
        return "The import task no longer exists."
    if run.status != tasks_facade.TaskRunStatus.COMPLETED:
        logger.info("metrics_dashboard_import_run_ended", status=run.status, error=run.error_message)
        return _AGENT_FAILED_MESSAGE
    return None


def finalize_import(*, team_id: int, task_id: str, background: bool) -> None:
    """Build the dashboard of a finished import task. Safe to call more than once and from several workers."""
    state = _claim(team_id, task_id)
    if state is None:
        return
    run = tasks_facade.get_latest_run_by_task([task_id]).get(task_id)
    if run is not None and run.team_id != team_id:
        run = None
    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=state.user_id)
    importer = DashboardImporter(team=team, user=user)
    verdicts: list[PanelVerdict] | None = None
    error = _run_failure(run)
    if error is None and run is not None:
        try:
            output = AgentImportOutput.model_validate(run.output or {})
            verdicts = importer.agent_verdicts(state, output)
        except ValidationError:
            logger.warning("metrics_dashboard_import_output_invalid", team_id=team_id)
            error = "The import agent returned an answer that PostHog cannot read. Try again."
        except Exception:
            logger.exception("metrics_dashboard_import_finalize_failed", team_id=team_id)
            error = "The import failed while it built the dashboard. Try again."
    try:
        result = importer.record(task_id, state, verdicts, error)
    except Exception:
        logger.exception("metrics_dashboard_import_record_failed", team_id=team_id)
        result = importer.record(task_id, state, None, "The import failed while it built the dashboard. Try again.")
    _delete_inputs(state.input_paths)
    if result is not None:
        importer.capture_finished(state, result, path="agent", background=background)


def check_panel_queries(
    *, team: Team, user: User, panels: Sequence[PanelQueryCheckRequest]
) -> list[PanelQueryCheckResult]:
    catalog = MetricCatalog.load(team)
    validator = PanelValidator(team=team, catalog=catalog, promql_available=promql_available(team, user))
    queries: dict[str, PanelQuery] = {}
    results: dict[str, PanelQueryCheckResult] = {}
    for panel in panels:
        try:
            queries[panel.key] = PanelQuery.model_validate(
                {
                    "language": panel.language.value,
                    "promql": panel.promql,
                    "builder": panel.builder,
                    "histogram_metric": panel.histogram_metric,
                    "hogql": panel.hogql,
                }
            )
        except ValidationError as error:
            results[panel.key] = PanelQueryCheckResult(key=panel.key, valid=False, error=str(error)[:400])
    catalog.look_up(team, _query_metric_names(queries.values()))
    for key, check in validator.check_all(queries, deadline_seconds=FINAL_CHECK_SECONDS).items():
        results[key] = PanelQueryCheckResult(key=key, valid=check.ok, error=check.error, notes=check.notes)
    return [results[panel.key] for panel in panels if panel.key in results]
