from __future__ import annotations

import json
import hashlib
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue

from products.signals.evals.agentic.saved_case import (
    EVENT_TABLE,
    STATE_MODELS,
    SavedCaseManifest,
    SavedEvent,
    SavedFile,
    SavedModel,
    SavedProjectProfile,
    SavedRow,
    SavedScoutCase,
    SavedSkill,
    SavedState,
    SavedStateManifest,
    StateTableName,
    state_table,
)

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext


class SavedDatasetSource(SavedModel):
    manifest_path: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: SavedCaseManifest


class SavedDatasetManifest(SavedModel):
    schema_version: Literal[1] = 1
    source_team_id: int | None
    source_cutoff: AwareDatetime
    checkpoint: AwareDatetime
    timezone: str
    sources: list[SavedDatasetSource] = Field(min_length=1)
    cases: list[SavedFile] = Field(min_length=1)
    input_event_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    state_counts: dict[str, int]


def _digest(row: SavedModel) -> bytes:
    encoded = json.dumps(row.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).digest()


def _reference(path: Path, workspace: Path) -> SavedFile:
    path.chmod(0o600)
    with path.open("rb") as content:
        digest = hashlib.file_digest(content, "sha256").hexdigest()
    return SavedFile(path=path.relative_to(workspace).as_posix(), sha256=digest)


def _write_model(path: Path, model: SavedModel, workspace: Path) -> SavedFile:
    with path.open("x", encoding="utf-8") as content:
        content.write(model.model_dump_json(indent=2) + "\n")
    return _reference(path, workspace)


class SavedScoutDataset:
    def __init__(
        self, path: Path, manifest: SavedDatasetManifest, cases: tuple[SavedScoutCase, ...], manifest_sha256: str
    ) -> None:
        self.path = path
        self.manifest = manifest
        self.cases = cases
        self.manifest_sha256 = manifest_sha256

    @property
    def metadata(self) -> dict[str, JsonValue]:
        return {
            **self.manifest.model_dump(mode="json"),
            "dataset_manifest_sha256": self.manifest_sha256,
            "deduplicated_event_count": self.manifest.input_event_count - self.manifest.event_count,
        }

    @staticmethod
    def _validate_cases(cases: Sequence[SavedScoutCase]) -> None:
        if not cases:
            raise ValueError("A saved dataset requires at least one case.")
        first = cases[0]
        if len(cases) > 1 and first.manifest.source_team_id is None:
            raise ValueError("Combining cases requires an explicit common source project.")
        skill_names: set[str] = set()
        repositories: dict[str, str] = {}
        for case in cases:
            case.preflight(validate_events=False)
            if case.manifest.source_team_id != first.manifest.source_team_id:
                raise ValueError("Saved dataset cases have different source projects.")
            if case.manifest.source_cutoff != first.manifest.source_cutoff:
                raise ValueError("Saved dataset cases have different source cutoffs.")
            if case.state.checkpoint != first.state.checkpoint or case.state.timezone != first.state.timezone:
                raise ValueError("Saved dataset cases have different state checkpoints or timezones.")
            if (
                set(case.manifest.time_strings) != set(first.manifest.time_strings)
                or case.manifest.string_replacements != first.manifest.string_replacements
            ):
                raise ValueError("Saved dataset cases require the same reviewed text replacement policy.")
            if case.skill_name in skill_names:
                raise ValueError(
                    "Saved dataset cases must select different scout skills; use trial variants for repeats."
                )
            skill_names.add(case.skill_name)
            repository = case.manifest.repository
            if repository:
                previous = repositories.setdefault(repository.name, repository.commit)
                if previous != repository.commit:
                    raise ValueError("Saved dataset cases pin different commits for the same repository.")

    @staticmethod
    def _merge_state(cases: Sequence[SavedScoutCase]) -> SavedState:
        values: dict[str, object] = cases[0].state.model_dump(include={"checkpoint", "complete", "gaps", "timezone"})
        identities: dict[UUID, str] = {}
        for name in STATE_MODELS:
            merged: dict[UUID, SavedRow] = {}
            profile: SavedProjectProfile | None = None
            for case in cases:
                if name == "project_profile":
                    candidate = case.state.project_profile
                    if candidate is not None:
                        if profile is not None and _digest(profile) != _digest(candidate):
                            raise ValueError("Saved dataset cases have conflicting project profiles.")
                        profile = candidate
                    continue
                for row in cast(list[SavedRow], getattr(case.state, name)):
                    previous_table = identities.setdefault(row.id, name)
                    previous = merged.get(row.id)
                    if previous_table != name or (previous is not None and _digest(previous) != _digest(row)):
                        raise ValueError(f"Saved dataset cases have conflicting {name} record IDs.")
                    merged[row.id] = row
            values[name] = profile if name == "project_profile" else list(merged.values())
        state = SavedState.model_validate(values)
        config_skills: dict[UUID, str] = {}
        for run in state.scout_runs:
            if run.scout_config_id is not None:
                previous_skill = config_skills.setdefault(run.scout_config_id, run.skill_name)
                if previous_skill != run.skill_name or run.scout_config_id in identities:
                    raise ValueError("Saved dataset cases have conflicting scout configuration IDs.")
        # Reuse reference, unique-key, and cutoff validation against the complete merged state.
        merged_case = SavedScoutCase(cases[0].path, cases[0].manifest, state)
        merged_case.preflight(validate_events=False)
        return state

    @classmethod
    def prepare(cls, cases: Sequence[SavedScoutCase], workspace: Path) -> SavedScoutDataset:
        cls._validate_cases(cases)
        state = cls._merge_state(cases)
        if workspace.is_symlink() or (workspace.exists() and (not workspace.is_dir() or any(workspace.iterdir()))):
            raise ValueError("Prepare requires a new or empty private dataset directory.")
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
        workspace = workspace.resolve()
        workspace.chmod(0o700)
        first = cases[0]
        seen_events: dict[UUID, bytes] = {}
        input_event_count = 0
        event_names: set[str] = set()

        def events() -> Iterator[SavedEvent]:
            nonlocal input_event_count
            for case in cases:
                for event in case.events():
                    if (
                        event.timestamp >= first.manifest.source_cutoff
                        or event.created_at >= first.manifest.source_cutoff
                    ):
                        raise ValueError("A saved dataset event is at or after the exclusive source cutoff.")
                    input_event_count += 1
                    digest = _digest(event)
                    previous = seen_events.get(event.uuid)
                    if previous is not None:
                        if previous != digest:
                            raise ValueError("Saved dataset cases have conflicting event UUIDs.")
                        continue
                    seen_events[event.uuid] = digest
                    event_names.add(event.event)
                    yield event

        event_path = workspace / "events.parquet"
        EVENT_TABLE.write(event_path, events())
        event_file = _reference(event_path, workspace)
        tables: dict[StateTableName, SavedFile] = {}
        state_counts: dict[str, int] = {}
        for name in STATE_MODELS:
            value = cast(list[SavedRow] | SavedProjectProfile | None, getattr(state, name))
            rows: list[SavedModel] = [value] if isinstance(value, SavedModel) else list(value or [])
            state_counts[name] = len(rows)
            if rows:
                table_path = workspace / f"{name}.parquet"
                state_table(name).write(table_path, rows)
                tables[name] = _reference(table_path, workspace)
        state_manifest = SavedStateManifest(
            checkpoint=state.checkpoint, complete=True, timezone=state.timezone, tables=tables
        )
        prepared_cases: list[SavedScoutCase] = []
        case_files: list[SavedFile] = []
        sources: list[SavedDatasetSource] = []
        for index, case in enumerate(cases):
            skill_values = case.manifest.skill.model_dump()
            body_path = workspace / f"skill-{index}.md"
            body_path.write_bytes(case.manifest.skill.body.resolve(case.path.parent).read_bytes())
            skill_values["body"] = _reference(body_path, workspace)
            skill_files = []
            for file_index, file in enumerate(case.manifest.skill.files):
                file_path = workspace / f"skill-{index}-file-{file_index}"
                file_path.write_bytes(file.content.resolve(case.path.parent).read_bytes())
                skill_files.append(file.model_copy(update={"content": _reference(file_path, workspace)}))
            skill_values["files"] = skill_files
            case_manifest = case.manifest.model_copy(
                update={
                    "skill": SavedSkill.model_validate(skill_values),
                    "state": state_manifest,
                    "events": [event_file],
                }
            )
            case_path = workspace / f"case-{index}.json"
            case_file = _write_model(case_path, case_manifest, workspace)
            prepared = SavedScoutCase(case_path, case_manifest, state, manifest_sha256=case_file.sha256)
            prepared.preflight(validate_events=False)
            prepared.event_count = len(seen_events)
            prepared.event_names = event_names.copy()
            prepared_cases.append(prepared)
            case_files.append(case_file)
            source_bytes = case.path.read_bytes()
            source_hash = hashlib.sha256(source_bytes).hexdigest()
            if case.manifest_sha256 is not None and source_hash != case.manifest_sha256:
                raise ValueError("A source manifest changed after loading; reload it before preparing a dataset.")
            if SavedCaseManifest.model_validate_json(source_bytes) != case.manifest:
                raise ValueError("The supplied case does not match its retained source manifest.")
            sources.append(
                SavedDatasetSource(manifest_path=str(case.path), manifest_sha256=source_hash, manifest=case.manifest)
            )
        manifest = SavedDatasetManifest(
            source_team_id=first.manifest.source_team_id,
            source_cutoff=first.manifest.source_cutoff,
            checkpoint=state.checkpoint,
            timezone=state.timezone,
            sources=sources,
            cases=case_files,
            input_event_count=input_event_count,
            event_count=len(seen_events),
            state_counts=state_counts,
        )
        path = workspace / "dataset.json"
        reference = _write_model(path, manifest, workspace)
        return cls(path, manifest, tuple(prepared_cases), reference.sha256)

    @classmethod
    def load(cls, path: Path) -> SavedScoutDataset:
        path = path.resolve(strict=True)
        content = path.read_bytes()
        manifest = SavedDatasetManifest.model_validate_json(content)
        cases: list[SavedScoutCase] = []
        for reference in manifest.cases:
            case_path = reference.resolve(path.parent)
            if not cases:
                case = SavedScoutCase.load(case_path)
            else:
                case_manifest = SavedCaseManifest.model_validate_json(case_path.read_bytes())
                if case_manifest.state != cases[0].manifest.state or case_manifest.events != cases[0].manifest.events:
                    raise ValueError("Prepared dataset cases must share the same state and events.")
                case = SavedScoutCase(case_path, case_manifest, cases[0].state, manifest_sha256=reference.sha256)
                case.event_count = cases[0].event_count
                case.event_names = cases[0].event_names.copy()
            cases.append(case)
        cls._validate_cases(cases)
        if (
            cases[0].event_count != manifest.event_count
            or cases[0].manifest.source_cutoff != manifest.source_cutoff
            or cases[0].manifest.source_team_id != manifest.source_team_id
            or cases[0].state.checkpoint != manifest.checkpoint
            or cases[0].state.timezone != manifest.timezone
            or manifest.input_event_count < manifest.event_count
            or len(manifest.sources) != len(cases)
        ):
            raise ValueError("The prepared dataset does not match its manifest.")
        state_counts = {
            name: int(cases[0].state.project_profile is not None)
            if name == "project_profile"
            else len(cast(list[SavedRow], getattr(cases[0].state, name)))
            for name in STATE_MODELS
        }
        if manifest.state_counts != state_counts:
            raise ValueError("The prepared dataset state counts do not match its manifest.")
        return cls(path, manifest, tuple(cases), hashlib.sha256(content).hexdigest())

    def restore(self, context: CustomPromptSandboxContext, *, target_cutoff: datetime) -> dict[str, JsonValue]:
        retained = type(self).load(self.path)
        if retained.manifest_sha256 != self.manifest_sha256:
            raise ValueError("The prepared dataset manifest changed before restoration.")
        restored = retained.cases[0]._restore(context, target_cutoff=target_cutoff, skill_sources=retained.cases)
        return {**restored, "dataset": self.metadata, "restored_skills": [case.skill_name for case in retained.cases]}
