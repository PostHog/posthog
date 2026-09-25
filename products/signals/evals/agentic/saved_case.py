from __future__ import annotations

import re
import json
import hashlib
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from itertools import groupby
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, Self, cast
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator

from products.signals.evals.agentic.saved_table import SavedTable

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet

    from products.signals.evals.agentic.datasets import ScoutCase
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext


class SavedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SavedFile(SavedModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def resolve(self, directory: Path) -> Path:
        relative = PurePosixPath(self.path)
        if relative.is_absolute() or ".." in relative.parts or "\\" in self.path:
            raise ValueError(f"Fixture file must stay inside its case directory: {self.path}")
        path = (directory / self.path).resolve(strict=True)
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError(f"Fixture file must stay inside its case directory: {self.path}")
        with path.open("rb") as content:
            digest = hashlib.file_digest(content, "sha256").hexdigest()
        if digest != self.sha256:
            raise ValueError(f"Fixture checksum does not match: {self.path}")
        return path


class SavedSkillFile(SavedModel):
    path: str
    content: SavedFile
    content_type: str = "text/plain"

    @field_validator("path")
    @classmethod
    def safe_skill_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value or not value:
            raise ValueError("Skill file paths must be relative and cannot traverse directories.")
        return value


class SavedSkill(SavedModel):
    name: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    description: str = Field(max_length=4096)
    body: SavedFile
    files: list[SavedSkillFile] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    license: str = ""
    compatibility: str = ""


class SavedRepository(SavedModel):
    name: str = "posthog/posthog"
    source_path: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    history_depth: Literal[1] | None = None


type StateTableName = Literal[
    "scratchpad",
    "reports",
    "report_artefacts",
    "scout_notes",
    "tasks",
    "task_runs",
    "scout_runs",
    "metrics",
    "project_profile",
]


class SavedStateManifest(SavedModel):
    checkpoint: AwareDatetime
    complete: bool
    gaps: list[str] = Field(default_factory=list)
    timezone: str = "UTC"
    tables: dict[StateTableName, SavedFile] = Field(default_factory=dict)


class SavedCaseManifest(SavedModel):
    schema_version: Literal[2]
    case_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    source_cutoff: AwareDatetime
    investigation_start: AwareDatetime | None = None
    source_team_id: int | None = None
    run_note: str = ""
    skill: SavedSkill
    repository: SavedRepository | None = None
    events: list[SavedFile] = Field(default_factory=list)
    state: SavedStateManifest
    time_strings: list[str] = Field(default_factory=list)
    string_replacements: dict[str, str] = Field(default_factory=dict)


class SavedEvent(SavedModel):
    uuid: UUID
    timestamp: AwareDatetime
    event: str = Field(min_length=1)
    distinct_id: str
    person_id: UUID | None = None
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: AwareDatetime

    @field_validator("properties", mode="before")
    @classmethod
    def decode_properties(cls, value: object) -> object:
        return json.loads(value) if isinstance(value, str) else value


class SavedRow(SavedModel):
    id: UUID
    team_id: int | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime | None = None


class SavedScratchpad(SavedRow):
    key: str = Field(max_length=300)
    content: str
    created_by_run_id: UUID | None = None
    created_by_identity: str | None = None
    expires_at: AwareDatetime | None = None


class SavedReport(SavedRow):
    status: Literal[
        "potential", "candidate", "in_progress", "pending_input", "ready", "resolved", "failed", "deleted", "suppressed"
    ]
    billing_exempt_reason: str | None = None
    status_before_suppression: str | None = None
    total_weight: float = 0
    signal_count: int = Field(default=0, ge=0)
    signals_at_run: int = 0
    run_count: int = 0
    signals_researched: int | None = None
    implemented_at_run_count: int | None = None
    content_revision_count: int | None = None
    implemented_at_revision_count: int | None = None
    corroboration_count: int | None = None
    title: str | None = None
    summary: str | None = None
    error: str | None = None
    charts: list[JsonValue] = Field(default_factory=list)
    metrics: list[JsonValue] = Field(default_factory=list)
    suggested_prompts: list[str] = Field(default_factory=list)
    promoted_at: AwareDatetime | None = None
    last_run_at: AwareDatetime | None = None
    first_visible_at: AwareDatetime | None = None
    inbox_notified_at: AwareDatetime | None = None
    scout_idempotency_key: str | None = None


class SavedReportArtefact(SavedRow):
    report_id: UUID
    type: str
    content: str
    actor_kind: Literal["user", "task", "agent", "system"] | None = None
    actor_agent: str | None = None
    created_by_id: int | None = None
    task_id: UUID | None = None
    claim_id: UUID | None = None
    pull_request_id: None = None
    channel_id: None = None


class SavedTask(SavedRow):
    title: str = ""
    description: str = ""
    origin_product: str = "signals_scout"
    created_by_id: int | None = None
    repository: str | None = None
    signal_report_id: UUID | None = None
    internal: bool = True
    state: dict[str, JsonValue] = Field(default_factory=dict)
    last_activity_at: AwareDatetime | None = None


class SavedTaskRun(SavedRow):
    task_id: UUID
    status: Literal["completed", "failed", "cancelled"]
    origin_product: str = "signals_scout"
    branch: str | None = None
    stage: str | None = None
    completed_at: AwareDatetime | None = None
    queued_at: AwareDatetime | None = None
    scheduled_at: AwareDatetime | None = None
    error_message: str | None = None
    output: JsonValue = None
    state: dict[str, JsonValue] = Field(default_factory=dict)
    artifacts: list[JsonValue] = Field(default_factory=list)


class SavedScoutRun(SavedRow):
    task_run_id: UUID
    scout_config_id: UUID | None = None
    skill_name: str
    skill_version: int
    summary: str = ""
    emitted_count: int | None = 0
    emitted_finding_ids: list[str] = Field(default_factory=list)
    emitted_report_ids: list[UUID] = Field(default_factory=list)
    edited_report_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class SavedScoutNote(SavedRow):
    skill_name: str = ""
    content: str
    created_by_id: int | None = None
    expires_at: AwareDatetime | None = None
    origin: Literal[
        "human", "report_dismissal", "report_discussion", "report_feedback", "report_reviewer_correction"
    ] = "human"


class SavedProjectProfile(SavedModel):
    source_version: str
    payload: dict[str, JsonValue]
    computed_at: AwareDatetime
    expires_at: AwareDatetime


class SavedMetric(SavedRow):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=128)
    display_name: str = Field(default="", max_length=255)
    description: str
    unit: str = Field(default="", max_length=64)
    owner_id: int | None = None
    definition: dict[str, JsonValue] | None = None
    referenced_table_names: list[str] = Field(default_factory=list)
    status: Literal["proposed", "approved"]
    approved_by_id: int | None = None
    approved_at: AwareDatetime | None = None
    source_insight_short_id: None = None
    source_insight_query_hash: None = None
    last_run_at: AwareDatetime | None = None
    created_source: Literal["user", "ai_generated"] = "user"
    ai_model: str = Field(default="", max_length=128)
    confidence: float | None = Field(default=None, ge=0, le=1)
    reasoning: str = ""
    created_by_id: int | None = None
    deleted: bool | None = False
    deleted_at: AwareDatetime | None = None


class SavedState(SavedModel):
    checkpoint: AwareDatetime
    complete: bool
    gaps: list[str] = Field(default_factory=list)
    scratchpad: list[SavedScratchpad] = Field(default_factory=list)
    reports: list[SavedReport] = Field(default_factory=list)
    report_artefacts: list[SavedReportArtefact] = Field(default_factory=list)
    scout_notes: list[SavedScoutNote] = Field(default_factory=list)
    tasks: list[SavedTask] = Field(default_factory=list)
    task_runs: list[SavedTaskRun] = Field(default_factory=list)
    scout_runs: list[SavedScoutRun] = Field(default_factory=list)
    metrics: list[SavedMetric] = Field(default_factory=list)
    project_profile: SavedProjectProfile | None = None
    evidence: list[dict[str, JsonValue]] = Field(default_factory=list)
    timezone: str = "UTC"


_UUID_TEXT = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


STATE_MODELS: dict[StateTableName, type[SavedModel]] = {
    "scratchpad": SavedScratchpad,
    "reports": SavedReport,
    "report_artefacts": SavedReportArtefact,
    "scout_notes": SavedScoutNote,
    "tasks": SavedTask,
    "task_runs": SavedTaskRun,
    "scout_runs": SavedScoutRun,
    "metrics": SavedMetric,
    "project_profile": SavedProjectProfile,
}
_JSON_FIELDS = frozenset(
    {
        "charts",
        "metrics",
        "suggested_prompts",
        "state",
        "output",
        "artifacts",
        "emitted_finding_ids",
        "emitted_report_ids",
        "edited_report_ids",
        "metadata",
        "payload",
        "definition",
        "referenced_table_names",
    }
)
EVENT_TABLE = SavedTable(SavedEvent, json_fields={"properties"})


def state_table(name: StateTableName) -> SavedTable[SavedModel]:
    model = STATE_MODELS[name]
    return SavedTable(model, json_fields=_JSON_FIELDS.intersection(model.model_fields))


class RestoredEventSummary:
    def __init__(self, timestamp: datetime) -> None:
        self.count = 1
        self.minimum = timestamp
        self.maximum = timestamp

    def observe(self, timestamp: datetime) -> None:
        self.count += 1
        self.minimum = min(self.minimum, timestamp)
        self.maximum = max(self.maximum, timestamp)

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "count": self.count,
            "min_timestamp": self.minimum.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "max_timestamp": self.maximum.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }


class SavedScoutCase:
    def __init__(
        self, path: Path, manifest: SavedCaseManifest, state: SavedState, *, manifest_sha256: str | None = None
    ) -> None:
        self.path = path
        self.manifest = manifest
        self.state = state
        self.manifest_sha256 = manifest_sha256
        self.event_count = 0
        self.event_names: set[str] = set()

    @property
    def skill_name(self) -> str:
        return self.manifest.skill.name

    @property
    def skill_version(self) -> int:
        return self.manifest.skill.version

    @property
    def repo(self) -> str | None:
        return self.manifest.repository.name if self.manifest.repository else None

    @property
    def metadata(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.manifest.schema_version,
            "case_id": self.manifest.case_id,
            "manifest_sha256": self.manifest_sha256,
            "source_cutoff": self.manifest.source_cutoff.isoformat(),
            "state_table_sha256": {name: file.sha256 for name, file in self.manifest.state.tables.items()},
            "event_sha256": [file.sha256 for file in self.manifest.events],
            "event_count": self.event_count,
            "skill_name": self.skill_name,
            "skill_version": self.skill_version,
            "skill_body_sha256": self.manifest.skill.body.sha256,
            "skill_file_sha256": {file.path: file.content.sha256 for file in self.manifest.skill.files},
        }

    @classmethod
    def load(cls, path: Path) -> Self:
        path = path.resolve(strict=True)
        manifest_bytes = path.read_bytes()
        manifest = SavedCaseManifest.model_validate_json(manifest_bytes)
        values: dict[str, object] = manifest.state.model_dump(exclude={"tables"})
        for name, reference in manifest.state.tables.items():
            rows = list(state_table(name).read(reference.resolve(path.parent)))
            if name == "project_profile":
                if len(rows) != 1:
                    raise ValueError("The saved project profile must contain exactly one row.")
                values[name] = rows[0]
            else:
                values[name] = rows
        state = SavedState.model_validate(values)
        case = cls(path, manifest, state, manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest())
        case.preflight()
        return case

    def _files(self) -> list[SavedFile]:
        return [
            *self.manifest.state.tables.values(),
            self.manifest.skill.body,
            *self.manifest.events,
            *[file.content for file in self.manifest.skill.files],
        ]

    def _rows(self) -> list[SavedRow]:
        return [
            *self.state.scratchpad,
            *self.state.reports,
            *self.state.report_artefacts,
            *self.state.scout_notes,
            *self.state.tasks,
            *self.state.task_runs,
            *self.state.scout_runs,
            *self.state.metrics,
        ]

    def events(self) -> Iterator[SavedEvent]:
        for reference in self.manifest.events:
            path = (self.path.parent / reference.path).resolve(strict=True)
            yield from EVENT_TABLE.read(path)

    def preflight(self, *, validate_events: bool = True) -> None:
        for reference in self._files():
            reference.resolve(self.path.parent)
        if not self.state.complete or self.state.gaps:
            raise ValueError("The starting state is incomplete: " + "; ".join(self.state.gaps))
        if self.state.evidence or any(run.emitted_finding_ids for run in self.state.scout_runs):
            raise ValueError("Restoring backing signal evidence is not supported; retain it before running this case.")
        if self.state.checkpoint > self.manifest.source_cutoff:
            raise ValueError("The starting checkpoint cannot be after the source cutoff.")
        if self.manifest.investigation_start and self.manifest.investigation_start > self.manifest.source_cutoff:
            raise ValueError("The investigation start cannot be after its cutoff.")
        if "" in self.manifest.string_replacements:
            raise ValueError("String replacement keys cannot be empty.")
        self.text_replacements(self.manifest.source_cutoff)
        if self.state.project_profile and self.state.project_profile.computed_at > self.manifest.source_cutoff:
            raise ValueError("The project profile was computed after the source cutoff.")
        paths = [file.path for file in self.manifest.skill.files]
        if len(paths) != len(set(paths)):
            raise ValueError("The skill contains duplicate support file paths.")
        ids = [row.id for row in self._rows()]
        if len(ids) != len(set(ids)):
            raise ValueError("The starting state contains duplicate record IDs.")
        memory_keys = [row.key for row in self.state.scratchpad]
        if len(memory_keys) != len(set(memory_keys)):
            raise ValueError("The starting state contains duplicate scratchpad keys.")
        metric_names = [metric.name for metric in self.state.metrics if metric.deleted is False]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("The starting state contains duplicate live metric names.")
        for row in self._rows():
            if (
                row.team_id is not None
                and self.manifest.source_team_id is not None
                and row.team_id != self.manifest.source_team_id
            ):
                raise ValueError("A starting-state row belongs to another source project.")
            for name, value in row.model_dump().items():
                if isinstance(value, datetime) and name != "expires_at" and value > self.state.checkpoint:
                    raise ValueError(f"Starting-state {name} is after its checkpoint: {row.id}")
        self._check_references()
        if not validate_events:
            return
        self.event_count = 0
        self.event_names = set()
        for event in self.events():
            if event.timestamp >= self.manifest.source_cutoff or event.created_at >= self.manifest.source_cutoff:
                raise ValueError(f"Event is at or after the exclusive source cutoff: {event.uuid}")
            self.event_count += 1
            self.event_names.add(event.event)

    def _check_references(self) -> None:
        reports = {row.id for row in self.state.reports}
        tasks = {row.id for row in self.state.tasks}
        task_runs = {row.id for row in self.state.task_runs}
        runs = {row.id for row in self.state.scout_runs}
        artefacts = {row.id for row in self.state.report_artefacts}
        references: list[tuple[UUID | None, set[UUID]]] = []
        references.extend((row.created_by_run_id, runs) for row in self.state.scratchpad)
        references.extend((row.signal_report_id, reports) for row in self.state.tasks)
        references.extend((row.task_id, tasks) for row in self.state.task_runs)
        for row in self.state.report_artefacts:
            references.extend([(row.report_id, reports), (row.task_id, tasks), (row.claim_id, artefacts)])
        for run in self.state.scout_runs:
            references.append((run.task_run_id, task_runs))
            references.extend((report_id, reports) for report_id in [*run.emitted_report_ids, *run.edited_report_ids])
        if any(reference is not None and reference not in available for reference, available in references):
            raise ValueError("The starting state contains a reference to a record absent from this case.")

    def run_note(self, target_cutoff: datetime) -> str:
        delta = self._delta(target_cutoff)
        note = self._replace_text(self.manifest.run_note, self.text_replacements(target_cutoff))
        if self.manifest.investigation_start is not None:
            start = self.manifest.investigation_start + delta
            note += f"\nInvestigate the interval starting at {start.isoformat()} and ending before {target_cutoff.isoformat()}. Include the start and exclude the end."
        return note.strip()

    def to_scout_case(self, target_cutoff: datetime) -> ScoutCase:
        from products.signals.evals.agentic.datasets import (
            ScoutCase,  # noqa: PLC0415 - Loading a manifest does not initialize Django.
        )

        return ScoutCase(
            case_id=self.manifest.case_id,
            step="scout",
            skill_name=self.skill_name,
            skill_version=self.skill_version,
            repository=self.repo,
            run_note=self.run_note(target_cutoff),
        )

    def _delta(self, target_cutoff: datetime) -> timedelta:
        if target_cutoff.tzinfo is None or target_cutoff.utcoffset() is None:
            raise ValueError("The target cutoff must include a timezone.")
        return target_cutoff.astimezone(UTC) - self.manifest.source_cutoff

    def _replacement_pattern(self, replacements: Mapping[str, str]) -> re.Pattern[str] | None:
        if not replacements:
            return None
        time_strings = set(self.manifest.time_strings)
        alternatives = []
        ordered_keys = sorted(replacements, key=len, reverse=True)
        for is_time, keys in groupby(ordered_keys, key=lambda key: key in time_strings):
            if is_time:
                dates = [re.escape(key) + (r"(?![T ]\d{2}:\d{2})" if len(key) == 10 else "") for key in keys]
                alternatives.append(r"(?<![\w/-])(?:" + "|".join(dates) + r")(?![\w/+-]|\.\d)")
            else:
                alternatives.extend(re.escape(key) for key in keys)
        return re.compile("|".join(alternatives))

    def _replace_text(self, value: str, replacements: Mapping[str, str]) -> str:
        pattern = self._replacement_pattern(replacements)
        return pattern.sub(lambda match: replacements[match.group(0)], value) if pattern else value

    def text_replacements(self, target_cutoff: datetime) -> dict[str, str]:
        delta = self._delta(target_cutoff)
        replacements: dict[str, str] = {}
        for value in self.manifest.time_strings:
            if not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?", value
            ):
                raise ValueError(f"A declared time string is not a supported ISO date or timestamp: {value}")
            parsed = datetime.fromisoformat(value)
            shifted = parsed.replace(tzinfo=parsed.tzinfo or UTC) + delta
            if len(value) == 10:
                replacements[value] = shifted.date().isoformat()
                continue
            time_part = value[11:].removesuffix("Z")
            fraction = re.search(r"\.(\d+)", time_part)
            timespec = "microseconds" if fraction else "seconds" if len(value) >= 19 and value[16] == ":" else "minutes"
            rendered = shifted.isoformat(sep=value[10], timespec=timespec)
            if fraction:
                precision = len(fraction.group(1))

                def truncate_fraction(match: re.Match[str], digits: int = precision) -> str:
                    return "." + match.group(1)[:digits]

                rendered = re.sub(r"\.(\d{6})", truncate_fraction, rendered)
            if value.endswith("Z"):
                rendered = rendered.removesuffix("+00:00") + "Z"
            elif parsed.tzinfo is None:
                rendered = rendered.removesuffix("+00:00")
            replacements[value] = rendered
        replacements.update(self.manifest.string_replacements)
        return replacements

    def restore(
        self,
        context: CustomPromptSandboxContext,
        *,
        target_cutoff: datetime,
        string_replacements: Mapping[str, str] | None = None,
    ) -> dict[str, JsonValue]:
        from django.conf import settings  # noqa: PLC0415 - Manifest validation stays independent of Django.
        from django.db import transaction  # noqa: PLC0415

        from posthog.models import Team, User  # noqa: PLC0415

        from products.data_catalog.backend.models import Metric  # noqa: PLC0415
        from products.signals.backend.models import (  # noqa: PLC0415
            SignalProjectProfile,
            SignalReport,
            SignalReportArtefact,
            SignalScoutConfig,
            SignalScoutNote,
            SignalScoutRun,
            SignalScratchpad,
            SignalTeamConfig,
        )
        from products.skills.backend.models.skills import LLMSkill, LLMSkillFile  # noqa: PLC0415
        from products.tasks.backend.models import Task, TaskRun  # noqa: PLC0415

        if not settings.TEST:
            raise RuntimeError("Saved scout cases can only restore into the local test environment.")
        self.preflight(validate_events=False)
        body = self.manifest.skill.body.resolve(self.path.parent).read_text()
        support_files = [
            (file, file.content.resolve(self.path.parent).read_text()) for file in self.manifest.skill.files
        ]
        team = Team.objects.select_related("organization").get(id=context.team_id)
        if team.parent_team_id or team.is_demo or not team.organization.name.startswith("Eval ("):
            raise ValueError("Restore requires a fresh empty project from the eval harness.")
        user = User.objects.get(id=context.user_id, organization_membership__organization_id=team.organization_id)
        for model in (SignalReport, Task, LLMSkill):
            if model.objects.filter(team_id=team.id).exists():
                raise ValueError("The target project already contains data; restore into a fresh project.")
        for scoped_model in (
            SignalScratchpad,
            SignalScoutConfig,
            SignalScoutRun,
            SignalScoutNote,
            SignalProjectProfile,
            Metric,
        ):
            if scoped_model.objects.for_team(team.id).exists():
                raise ValueError("The target project already contains scout state; restore into a fresh project.")
        allowed_artefacts = {choice[0] for choice in SignalReportArtefact._meta.get_field("type").choices or []}
        if any(row.type not in allowed_artefacts for row in self.state.report_artefacts):
            raise ValueError("The case contains an unsupported report artefact type.")
        transformer = SavedCaseTransform(self, target_cutoff, string_replacements)
        with transaction.atomic():
            team.organization.name = "Workspace"
            team.organization.is_ai_data_processing_approved = True
            team.organization.save(update_fields=["name", "is_ai_data_processing_approved"])
            User.objects.filter(id=user.id).update(
                email=f"member-{user.id}@example.com", first_name="Project member", last_name=""
            )
            team.timezone = self.state.timezone
            team.save(update_fields=["timezone"])
            team_config, _ = SignalTeamConfig.objects.get_or_create(team_id=team.id)
            SignalTeamConfig.objects.filter(id=team_config.id).update(
                autostart_enabled=False, github_issue_writeback_enabled=False
            )
            configurations: dict[str, SignalScoutConfig] = {}
            skill_names = {self.skill_name, *(run.skill_name for run in self.state.scout_runs)}
            for skill_name in skill_names:
                config = SignalScoutConfig(
                    team_id=team.id,
                    skill_name=skill_name,
                    enabled=False,
                    status=SignalScoutConfig.Status.PAUSED_BY_USER,
                    emit=True,
                    created_by_id=context.user_id,
                    enabled_by_id=context.user_id,
                    repositories=[self.repo] if self.repo and skill_name == self.skill_name else [],
                    write_scopes=[],
                    output_destinations={},
                    mcp_gateway_server_ids=[],
                )
                SignalScoutConfig.objects.for_team(team.id).bulk_create([config])
                configurations[skill_name] = config
            for saved_run in self.state.scout_runs:
                if saved_run.scout_config_id is not None:
                    transformer.ids[saved_run.scout_config_id] = configurations[saved_run.skill_name].id
            skill_spec = self.manifest.skill
            skill = LLMSkill(
                team_id=team.id,
                name=skill_spec.name,
                version=skill_spec.version,
                is_latest=True,
                category="scout",
                description=skill_spec.description,
                body=body,
                metadata=skill_spec.metadata,
                allowed_tools=skill_spec.allowed_tools,
                license=skill_spec.license,
                compatibility=skill_spec.compatibility,
                created_by_id=context.user_id,
            )
            LLMSkill.objects.bulk_create([skill])
            LLMSkillFile.objects.bulk_create(
                [
                    LLMSkillFile(skill=skill, path=file.path, content=content, content_type=file.content_type)
                    for file, content in support_files
                ]
            )
            for saved_metric in self.state.metrics:
                transformer.insert(
                    Metric.objects.for_team(team.id),
                    Metric,
                    saved_metric,
                    team.id,
                    overrides={
                        "owner_id": context.user_id if saved_metric.owner_id is not None else None,
                        "approved_by_id": context.user_id if saved_metric.approved_by_id is not None else None,
                        "created_by_id": context.user_id if saved_metric.created_by_id is not None else None,
                    },
                )
            for saved_report in self.state.reports:
                transformer.insert(SignalReport.objects.filter(team_id=team.id), SignalReport, saved_report, team.id)
            for saved_task in self.state.tasks:
                transformer.insert(
                    Task.objects.filter(team_id=team.id),
                    Task,
                    saved_task,
                    team.id,
                    overrides={"created_by_id": context.user_id if saved_task.created_by_id is not None else None},
                )
            for saved_task_run in self.state.task_runs:
                transformer.insert(TaskRun.objects.filter(team_id=team.id), TaskRun, saved_task_run, team.id)
            for saved_run in self.state.scout_runs:
                transformer.insert(
                    SignalScoutRun.objects.for_team(team.id),
                    SignalScoutRun,
                    saved_run,
                    team.id,
                    overrides={"scout_config_id": configurations[saved_run.skill_name].id},
                )
            for saved_artefact in self.state.report_artefacts:
                transformer.insert(
                    SignalReportArtefact.objects.filter(team_id=team.id),
                    SignalReportArtefact,
                    saved_artefact,
                    team.id,
                    overrides={"created_by_id": context.user_id if saved_artefact.created_by_id is not None else None},
                )
            for saved_memory in self.state.scratchpad:
                transformer.insert(SignalScratchpad.objects.for_team(team.id), SignalScratchpad, saved_memory, team.id)
            for saved_note in self.state.scout_notes:
                transformer.insert(
                    SignalScoutNote.objects.for_team(team.id),
                    SignalScoutNote,
                    saved_note,
                    team.id,
                    overrides={"created_by_id": context.user_id if saved_note.created_by_id is not None else None},
                )
            profile = self.state.project_profile
            if profile is not None:
                profile_row = SignalProjectProfile(
                    team_id=team.id,
                    source_version=profile.source_version,
                    payload=transformer.value(profile.payload),
                    expires_at=profile.expires_at + transformer.delta,
                )
                SignalProjectProfile.objects.for_team(team.id).bulk_create([profile_row])
                SignalProjectProfile.objects.for_team(team.id).filter(id=profile_row.id).update(
                    computed_at=profile.computed_at + transformer.delta
                )
        event_summaries = self._restore_events(context.team_id, transformer)
        event_validation = self._validate_restored_events(context.team_id, event_summaries)
        return {
            **self.metadata,
            "target_cutoff": target_cutoff.isoformat(),
            "time_delta_seconds": transformer.delta.total_seconds(),
            "text_replacements": cast(dict[str, JsonValue], transformer.replacements),
            "identity_namespace": str(transformer.namespace),
            "state_id_map": {str(source): str(target) for source, target in transformer.ids.items()},
            "restored_events": sum(summary.count for summary in event_summaries.values()),
            "event_validation": event_validation,
            "restored_reports": len(self.state.reports),
            "restored_scratchpad": len(self.state.scratchpad),
            "restored_metrics": len(self.state.metrics),
        }

    def _restore_events(self, team_id: int, transformer: SavedCaseTransform) -> dict[str, RestoredEventSummary]:
        from posthog.models.event.util import (
            bulk_create_events,  # noqa: PLC0415 - Event restoration runs only after Django initializes.
        )

        from products.demo.backend.facade.api import infer_taxonomy_for_team  # noqa: PLC0415

        batch: list[dict[str, object]] = []
        summaries: dict[str, RestoredEventSummary] = {}
        for event in self.events():
            timestamp = event.timestamp + transformer.delta
            person_id = event.person_id or uuid5(transformer.namespace, event.distinct_id)
            batch.append(
                {
                    "event_uuid": event.uuid,
                    "event": event.event,
                    "distinct_id": event.distinct_id,
                    "timestamp": timestamp,
                    "created_at": event.created_at + transformer.delta,
                    "properties": transformer.value(event.properties),
                    "person_id": person_id,
                    "team_id": team_id,
                    "person_mode": "full",
                }
            )
            if summary := summaries.get(event.event):
                summary.observe(timestamp)
            else:
                summaries[event.event] = RestoredEventSummary(timestamp)
            if len(batch) >= 5_000:
                bulk_create_events(batch, skip_entity_lookups=True)
                batch = []
        if batch:
            bulk_create_events(batch, skip_entity_lookups=True)
        if summaries:
            infer_taxonomy_for_team(team_id)
        return summaries

    @staticmethod
    def _validate_restored_events(team_id: int, summaries: dict[str, RestoredEventSummary]) -> dict[str, JsonValue]:
        from posthog.hogql import ast  # noqa: PLC0415 - Query validation runs only after event restoration.
        from posthog.hogql.query import execute_hogql_query  # noqa: PLC0415

        from posthog.models import Team  # noqa: PLC0415

        expected: dict[str, JsonValue] = {event: summary.as_json() for event, summary in summaries.items()}
        if not expected:
            return {"matched": True, "query_performed": False, "by_event": {}}
        result = execute_hogql_query(
            "SELECT event, count(), "
            "formatDateTime(min(timestamp), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC'), "
            "formatDateTime(max(timestamp), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') "
            "FROM events GROUP BY event ORDER BY event LIMIT {event_limit}",
            team=Team.objects.get(id=team_id),
            placeholders={"event_limit": ast.Constant(value=len(expected) + 1)},
        )
        actual = {
            row[0]: {"count": row[1], "min_timestamp": row[2], "max_timestamp": row[3]} for row in result.results or []
        }
        if actual != expected:
            raise ValueError(f"Restored event counts or timestamp bounds differ: expected={expected}, actual={actual}")
        return {"matched": True, "query_performed": True, "by_event": expected}


class SavedCaseTransform:
    def __init__(
        self,
        case: SavedScoutCase,
        target_cutoff: datetime,
        replacements: Mapping[str, str] | None = None,
    ) -> None:
        self.namespace = uuid4()
        self.delta = case._delta(target_cutoff)
        self.replacements = {**case.text_replacements(target_cutoff), **(replacements or {})}
        if "" in self.replacements:
            raise ValueError("String replacement keys cannot be empty.")
        self.ids = {row.id: uuid5(self.namespace, str(row.id)) for row in case._rows()}
        self._text_pattern = case._replacement_pattern(self.replacements)

    def identity(self, value: UUID) -> UUID:
        return self.ids.get(value) or uuid5(self.namespace, str(value))

    def text(self, value: str) -> str:
        value = _UUID_TEXT.sub(lambda match: str(self.ids.get(UUID(match.group(0)), match.group(0))), value)
        if self._text_pattern:
            value = self._text_pattern.sub(lambda match: self.replacements[match.group(0)], value)
        return value

    def value(self, value: object) -> object:
        if isinstance(value, UUID):
            return self.identity(value)
        if isinstance(value, datetime):
            return value + self.delta
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(key): self.value(nested) for key, nested in value.items()}
        if isinstance(value, list):
            return [self.value(nested) for nested in value]
        if value is None or isinstance(value, bool | int | float):
            return value
        raise TypeError(f"Unsupported saved-case value: {type(value).__name__}")

    def insert(
        self,
        queryset: QuerySet[Model],
        model: type[Model],
        source: SavedRow,
        team_id: int,
        *,
        overrides: Mapping[str, object] | None = None,
    ) -> None:
        from django.core.serializers.json import (
            DjangoJSONEncoder,  # noqa: PLC0415 - Only database restoration needs Django.
        )
        from django.db.models import JSONField  # noqa: PLC0415

        data = cast(dict[str, object], self.value(source.model_dump(exclude={"team_id", "created_at", "updated_at"})))
        data.update(overrides or {})
        for field in model._meta.fields:
            if isinstance(field, JSONField) and field.name in data:
                data[field.name] = json.loads(json.dumps(data[field.name], cls=DjangoJSONEncoder))
        row = model(team_id=team_id, **data)
        queryset.bulk_create([row])
        dates = {"created_at": source.created_at + self.delta}
        if any(field.name == "updated_at" for field in model._meta.fields):
            dates["updated_at"] = (source.updated_at or source.created_at) + self.delta
        queryset.filter(id=row.pk).update(**dates)
