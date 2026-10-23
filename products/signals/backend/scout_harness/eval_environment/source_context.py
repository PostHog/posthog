from __future__ import annotations

import re
import json
import hashlib
from datetime import datetime
from typing import Literal, cast
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue, TypeAdapter

from products.posthog_ai.eval_harness.environment.schema import EnvironmentMetric, EnvironmentModel
from products.posthog_ai.eval_harness.environment.storage import require_private_path
from products.signals.backend.scout_harness.eval_environment.schema import (
    ScoutEnvironmentCase,
    ScoutEnvironmentOrganization,
    ScoutEnvironmentRecord,
    ScoutEnvironmentSkill,
    ScoutEnvironmentStartingState,
    ScoutEnvironmentUser,
)
from products.signals.backend.scout_harness.eval_environment.source_client import (
    SourceAPI,
    SourceExportError,
    array_value,
    object_value,
    timestamp,
)
from products.signals.backend.scout_harness.eval_environment.source_plan import SourceSlicePlan
from products.signals.backend.scout_harness.eval_environment.support import ScoutEnvironmentSupport
from products.signals.backend.scout_harness.profile_version import INVENTORY_SOURCE_VERSION
from products.skills.backend.marketplace.packaging import SkillImportError, parse_skill_md


def string_value(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise SourceExportError("A required source text field is missing.")
    return value


def canonical_digest(value: JsonValue) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SourceSnapshot(EnvironmentModel):
    case: ScoutEnvironmentCase
    metrics: list[EnvironmentMetric]
    identity_mappings: dict[str, str]


class SourceContext:
    CONFIG_FIELDS = ScoutEnvironmentSupport.CONFIG_FIELDS
    REPORT_FIELDS = frozenset(
        {
            "title",
            "summary",
            "status",
            "monitoring_started_at",
            "total_weight",
            "signal_count",
            "signals_at_run",
            "charts",
            "metrics",
            "suggested_prompts",
            "billing_exempt_reason",
        }
    )
    RUN_FIELDS = frozenset(
        {
            "skill_name",
            "skill_version",
            "summary",
            "emitted_count",
            "emitted_finding_ids",
            "emitted_report_ids",
            "edited_report_ids",
            "metadata",
            "total_spend",
            "task_id",
            "task_run_id",
            "status",
            "started_at",
            "completed_at",
            "error",
        }
    )

    def __init__(self, api: SourceAPI, plan: SourceSlicePlan) -> None:
        self.api, self.plan = api, plan
        self.users: dict[str, ScoutEnvironmentUser] = {user.id: user for user in plan.users}
        self.identity_mappings: dict[str, str] = {}
        self.namespace = uuid5(NAMESPACE_URL, api.origin + api.project_path)

    def _user(self, data: JsonValue, *, operator: bool = False) -> str | None:
        if data is None:
            return None
        row = object_value(data)
        identifier = row.get("id")
        if not isinstance(identifier, (str, int)) or isinstance(identifier, bool):
            raise SourceExportError("A source user has no stable identity.")
        identifier = str(identifier)
        user = ScoutEnvironmentUser(
            id=identifier,
            uuid=UUID(string_value(row.get("uuid"))),
            first_name=string_value(row.get("first_name")),
            last_name=string_value(row.get("last_name", "")),
            email=string_value(row.get("email")),
            is_operator=operator or (identifier in self.users and self.users[identifier].is_operator),
            github_login=self.users[identifier].github_login if identifier in self.users else None,
        )
        previous = self.users.get(identifier)
        if previous and previous.model_copy(update={"is_operator": user.is_operator}) != user:
            raise SourceExportError("Source user identities changed or conflict with supplied identities.")
        self.users[identifier] = user
        return identifier

    def _named_author(self, name: JsonValue) -> str | None:
        if name is None:
            return None
        selected = [user.id for user in self.users.values() if (user.first_name + " " + user.last_name).strip() == name]
        if len(selected) != 1:
            raise SourceExportError(
                "A note author cannot be resolved uniquely. Supply verified source user identities; no author was invented."
            )
        return selected[0]

    def _record(
        self, row: dict[str, JsonValue], fields: dict[str, JsonValue], *, identity: str = "id"
    ) -> ScoutEnvironmentRecord:
        return ScoutEnvironmentRecord(
            id=UUID(string_value(row.get(identity))),
            created_at=timestamp(row.get("created_at")),
            updated_at=timestamp(row["updated_at"]) if row.get("updated_at") else None,
            fields=fields,
        )

    def _config(self) -> dict[str, JsonValue]:
        if self.plan.draft_skill is not None:
            config = dict(self.plan.draft_config)
        else:
            matches = [
                object_value(row)
                for row in array_value(self.api.read(self.api.project_path + "signals/scout/configs/"))
                if object_value(row).get("skill_name") == self.plan.skill_name
            ]
            if len(matches) != 1:
                raise SourceExportError("The source project does not have exactly one matching Scout.")
            config = matches[0]
        try:
            ScoutEnvironmentSupport.validate_connections(config)
        except ValueError:
            raise SourceExportError(
                "The Scout requires an unsupported isolated adapter for external connections."
            ) from None
        if config.get("structured_output_schema"):
            raise SourceExportError("The Scout requires an unsupported isolated adapter: structured_output_schema")
        if self.plan.draft_skill is None:
            rubric = object_value(
                self.api.read(
                    self.api.project_path + "signals/scout/rubrics/" + str(UUID(string_value(config.get("id")))) + "/"
                )
            )
            if rubric.get("config_id") != config.get("id") or rubric.get("skill_name") != self.plan.skill_name:
                raise SourceExportError("The source rubric belongs to another Scout.")
            config["rubrics"] = {key: value for key, value in rubric.items() if key not in {"config_id", "skill_name"}}
        return config

    def _skill(self, config: dict[str, JsonValue], *, skill_name: str | None = None) -> ScoutEnvironmentSkill:
        selected_name = skill_name or self.plan.skill_name
        if self.plan.draft_skill is not None and skill_name is None:
            draft_path = require_private_path(self.plan.draft_skill)
            try:
                parsed = parse_skill_md(draft_path.read_text())
            except SkillImportError:
                raise SourceExportError(
                    "The draft skill could not be parsed; its private contents were withheld."
                ) from None
            draft_files: dict[str, str] = {}
            for directory in ("references", "scripts", "assets"):
                root = draft_path.parent / directory
                if root.is_symlink():
                    raise SourceExportError("Draft skill directories cannot be symbolic links.")
                if root.exists():
                    for file in sorted(root.rglob("*")):
                        if file.is_symlink():
                            raise SourceExportError("Draft skill files cannot be symbolic links.")
                        if file.is_file():
                            draft_files[file.relative_to(draft_path.parent).as_posix()] = file.read_text()
            identifier = uuid5(self.namespace, "draft-skill:" + self.plan.skill_name)
            self.identity_mappings["draft-skill:" + self.plan.skill_name] = str(identifier)
            if parsed["name"] != self.plan.skill_name:
                raise SourceExportError("The draft skill name differs from the selected Scout.")
            return ScoutEnvironmentSkill.model_validate(
                {
                    **parsed,
                    "id": identifier,
                    "version": 1,
                    "origin": "custom",
                    "files": draft_files,
                    "owners": [user.id for user in self.users.values() if user.is_operator],
                }
            )
        path = self.api.project_path + "llm_skills/name/" + quote(selected_name, safe="") + "/"
        row = object_value(self.api.read(path))
        version = row.get("version")
        if not isinstance(version, int):
            raise SourceExportError("The source skill has no version.")
        body = string_value(row.get("body"))
        while row.get("body_next_offset") is not None:
            offset = row["body_next_offset"]
            if offset != len(body):
                raise SourceExportError("Source skill body paging is incomplete.")
            page = object_value(self.api.read(path, params={"version": version, "body_offset": len(body)}))
            if page.get("id") != row.get("id") or not page.get("body"):
                raise SourceExportError("The source skill changed while paging its body.")
            body += string_value(page.get("body"))
            row["body_next_offset"] = page.get("body_next_offset")
        if len(body) != row.get("body_total_length"):
            raise SourceExportError("The source skill body was truncated.")
        files: dict[str, str] = {}
        types: dict[str, str] = {}
        for entry in array_value(row.get("files", [])):
            manifest = object_value(entry)
            name = string_value(manifest.get("path"))
            content = object_value(
                self.api.read(path + "files/" + quote(name, safe="/") + "/", params={"version": version})
            )
            body_text = string_value(content.get("content"))
            if len(body_text) != manifest.get("char_count"):
                raise SourceExportError("A source skill file was truncated.")
            digest = manifest.get("sha256")
            if digest and digest != hashlib.sha256(body_text.encode()).hexdigest():
                raise SourceExportError("A source skill file does not match its manifest.")
            files[name], types[name] = body_text, string_value(content.get("content_type"))
        owners = [self._user(owner) for owner in array_value(row.get("owners", []))]
        creator = self._user(row.get("created_by"))
        metadata = object_value(row.get("metadata", {}))
        origin = config.get("scout_origin", "canonical" if metadata.get("canonical_hash") else "custom")
        allowed_tools = [string_value(tool) for tool in array_value(row.get("allowed_tools", []))]
        if origin == "canonical" and metadata.get("canonical_hash") is not None:
            # The runtime's row-origin check compares this same complete content shape.
            payload = {
                "description": row.get("description"),
                "body": body,
                "allowed_tools": sorted(allowed_tools),
                "files": sorted((name, content, types[name]) for name, content in files.items()),
            }
            if hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() != metadata["canonical_hash"]:
                origin = "custom"
        return ScoutEnvironmentSkill(
            id=UUID(string_value(row.get("id"))),
            name=selected_name,
            description=string_value(row.get("description")),
            body=body,
            version=version,
            origin=cast("Literal['canonical', 'custom']", origin),
            allowed_tools=allowed_tools,
            files=files,
            file_content_types=types,
            owners=[owner for owner in owners if owner is not None],
            created_by=creator,
            created_at=timestamp(row.get("created_at")),
            updated_at=timestamp(row.get("updated_at")),
            metadata=metadata,
            license=string_value(row.get("license", "")),
            compatibility=string_value(row.get("compatibility", "")),
            category=string_value(row.get("category") or ""),
        )

    def _metrics(self) -> list[EnvironmentMetric]:
        metrics = []
        for name in self.plan.metric_names:
            row = object_value(
                self.api.read(self.api.project_path + "data_catalog/metrics/" + quote(name, safe="") + "/")
            )
            if row.get("source_insight_short_id") or any(
                table != "events" for table in array_value(row.get("referenced_table_names", []))
            ):
                raise SourceExportError("A selected metric depends on unsupported data or a saved insight.")
            owner = row.pop("owner", None)
            for field in ("created_by", "approved_by"):
                identifier = self._user(row.pop(field, None))
                row[field + "_id"] = int(identifier) if identifier else None
            owner_ids = [user.id for user in self.users.values() if user.email == owner] if owner else []
            if owner and len(owner_ids) != 1:
                raise SourceExportError("A metric owner cannot be resolved uniquely from verified source identities.")
            row["owner_id"] = int(owner_ids[0]) if owner_ids else None
            metric = EnvironmentMetric.model_validate(
                {key: value for key, value in row.items() if key in EnvironmentMetric.model_fields}
            )
            if metric.name != name:
                raise SourceExportError("The source returned a different metric than requested.")
            if any(
                isinstance(value, datetime) and value > self.plan.source_cutoff
                for value in metric.model_dump().values()
            ):
                raise SourceExportError("A selected metric changed after the source cutoff.")
            metrics.append(metric)
        return metrics

    @classmethod
    def _structured_dates(cls, value: JsonValue) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, str) and (
                    key.endswith("_at")
                    or key in {"timestamp", "dateFrom", "dateTo", "date_from", "date_to", "start", "end"}
                ):
                    if re.fullmatch(
                        r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?", item
                    ):
                        datetime.fromisoformat(item.replace("Z", "+00:00"))
                        found.add(item)
                found.update(cls._structured_dates(item))
        elif isinstance(value, list):
            for item in value:
                found.update(cls._structured_dates(item))
        return found

    def read(self) -> SourceSnapshot:
        if self.plan.source_project_url is not None and self.plan.source_project_url != (
            self.api.origin + "/project/" + str(self.plan.project_id)
        ):
            raise SourceExportError("The source project URL must match the selected source project.")
        if not self.plan.text_time_policy_reviewed:
            raise SourceExportError(
                "Review source text dates and provide the explicit time_strings policy before exporting Scout context."
            )
        if self.plan.profile_snapshot is None:
            raise SourceExportError(
                "A Scout export needs an existing private profile snapshot. The current profile API can trigger a source rebuild; this exporter will not call it."
            )
        profile_input = object_value(
            TypeAdapter(JsonValue).validate_json(require_private_path(self.plan.profile_snapshot).read_bytes())
        )
        if (
            profile_input.get("source_origin") != self.api.origin
            or profile_input.get("project_id") != self.plan.project_id
        ):
            raise SourceExportError("The profile snapshot belongs to a different source project.")
        profile = object_value(profile_input.get("profile"))
        if profile.get("source_version") != INVENTORY_SOURCE_VERSION:
            raise SourceExportError("The source profile version is incompatible with this Scout harness.")
        object_value(profile.get("payload"))
        captured = timestamp(profile_input.get("captured_at"))
        if captured > self.plan.source_cutoff or timestamp(profile.get("computed_at")) > captured:
            raise SourceExportError("The profile snapshot is newer than the source export cutoff.")
        if timestamp(profile.get("expires_at")) <= self.plan.source_cutoff:
            raise SourceExportError(
                "The supplied profile snapshot is stale; obtain a current source snapshot explicitly."
            )
        project = object_value(self.api.read(self.api.project_path))
        if project.get("id") != self.plan.project_id or project.get("parent_team_id"):
            raise SourceExportError("Source export requires the canonical selected project.")
        me = object_value(self.api.read("/api/users/@me/"))
        user_document = object_value(me.get("user", me))
        self._user(user_document, operator=True)
        config = self._config()
        skill = self._skill(config)
        companion_skills = [self._skill({}, skill_name=name) for name in self.plan.companion_skill_names]
        metrics = self._metrics()
        base = self.api.project_path + "signals/scout/"
        notes = self.api.dated_rows(
            base + "notes/",
            date_field="created_at",
            identity_field="id",
            start=None,
            end=self.plan.source_cutoff,
            cap=500,
            max_rows=self.plan.max_context_rows,
            params={"skill_name": self.plan.skill_name, "include_general": "true", "include_expired": "false"},
        )
        memories = []
        for key in self.plan.memory_keys if self.plan.memory_keys is not None else [None]:
            memories.extend(
                self.api.dated_rows(
                    base + "scratchpad/",
                    date_field="updated_at",
                    identity_field="key",
                    start=None,
                    end=self.plan.source_cutoff,
                    cap=1000,
                    max_rows=self.plan.max_context_rows,
                    params={"include_expired": "false", **({"key": key} if key is not None else {})},
                )
            )
            if len(memories) > self.plan.max_context_rows:
                raise SourceExportError("Selected memory exceeds the explicit export limit.")
        if self.plan.memory_keys is not None:
            memories = [row for row in memories if row.get("key") in self.plan.memory_keys]
            if {row["key"] for row in memories} != set(self.plan.memory_keys):
                raise SourceExportError("A selected memory key is missing from current source state.")
        runs = self.api.dated_rows(
            base + "runs/",
            date_field="created_at",
            identity_field="run_id",
            start=self.plan.history_from,
            end=self.plan.source_cutoff,
            cap=100,
            max_rows=self.plan.max_context_rows,
            params={"skill_name": self.plan.skill_name},
        )
        run_ids = {row["run_id"] for row in runs}
        for memory in memories:
            run_id = memory.get("created_by_run_id")
            if isinstance(run_id, str) and run_id not in run_ids:
                if len(runs) >= self.plan.max_context_rows:
                    raise SourceExportError("Related run history exceeds the explicit export limit.")
                runs.append(object_value(self.api.read(base + "runs/" + str(UUID(run_id)) + "/")))
                run_ids.add(run_id)
        if any(row.get("status") not in {"completed", "failed", "cancelled"} for row in runs):
            raise SourceExportError("Selected source history contains an unfinished run.")
        if any(row.get("emitted_finding_ids") or row.get("emitted_count") for row in runs):
            raise SourceExportError("Selected run history depends on unsupported emitted Signal records.")
        reports: list[ScoutEnvironmentRecord] = []
        artefacts: list[ScoutEnvironmentRecord] = []
        report_ids = {str(identifier) for identifier in self.plan.report_ids}
        for run in runs:
            for field in ("emitted_report_ids", "edited_report_ids"):
                report_ids.update(string_value(value) for value in array_value(run.get(field) or []))
        if len(report_ids) > self.plan.max_context_rows:
            raise SourceExportError("The selected reports exceed the explicit export limit.")
        for identifier in sorted(report_ids):
            path = self.api.project_path + "signals/reports/" + str(UUID(identifier)) + "/"
            row = object_value(self.api.read(path))
            expected_work_state = "done" if row.get("status") in {"resolved", "monitoring"} else "unclaimed"
            if (
                row.get("channel_id")
                or row.get("pull_requests")
                or row.get("assignee")
                or row.get("work_state") not in {None, expected_work_state}
            ):
                raise SourceExportError(
                    "A selected report depends on unsupported task channels, work assignments or pull requests."
                )
            reports.append(self._record(row, {key: value for key, value in row.items() if key in self.REPORT_FIELDS}))
            for artefact in self.api.pages(path + "artefacts/", max_rows=self.plan.max_context_rows):
                if (
                    len(artefacts) >= self.plan.max_context_rows
                    or artefact.get("pull_request_id")
                    or artefact.get("type") == "check_result"
                ):
                    raise SourceExportError(
                        "Report artefacts exceed the limit or need an unsupported pull-request adapter."
                    )
                if artefact.get("task_id") and not any(run.get("task_id") == artefact["task_id"] for run in runs):
                    raise SourceExportError("A report artefact depends on a task outside the supported Scout history.")
                fields = {
                    key: artefact[key]
                    for key in ("type", "content", "actor_kind", "actor_agent", "task_id", "claim_id")
                    if key in artefact
                }
                fields.update(report_id=identifier, created_by_id=self._user(artefact.get("created_by")))
                fields["content"] = json.dumps(artefact.get("content"), sort_keys=True, separators=(",", ":"))
                artefacts.append(self._record(artefact, fields))
        memory_records = []
        for row in memories:
            key = string_value(row.get("key"))
            memory_identifier = uuid5(self.namespace, "memory:" + key)
            self.identity_mappings["memory:" + key] = str(memory_identifier)
            memory_records.append(
                self._record(
                    {**row, "id": str(memory_identifier)},
                    {
                        "key": key,
                        "content": row["content"],
                        "created_by_run_id": row.get("created_by_run_id"),
                        "created_by_identity": row.get("created_by_skill"),
                        "expires_at": row.get("expires_at"),
                    },
                )
            )
        profile_record = ScoutEnvironmentRecord(
            id=UUID(string_value(profile.get("profile_id"))),
            created_at=timestamp(profile.get("computed_at")),
            fields={key: profile[key] for key in ("expires_at", "source_version", "payload")},
        )
        organization = project.get("organization")
        org = object_value(organization) if isinstance(organization, dict) else {}
        current_org = user_document.get("organization")
        if not org and isinstance(current_org, dict) and current_org.get("id") == organization:
            org = current_org
        if not org or "is_ai_data_processing_approved" not in org or "is_ai_training_opted_in" not in org:
            raise SourceExportError(
                "The project API did not expose its organization approval state; an explicit source adapter is required."
            )
        case = ScoutEnvironmentCase(
            environment_id=self.plan.environment_id,
            source_cutoff=self.plan.source_cutoff,
            checkpoint=self.plan.source_cutoff,
            timezone=string_value(project.get("timezone")),
            project_name=string_value(project.get("name")),
            organization=ScoutEnvironmentOrganization(
                name=string_value(org["name"]) if org.get("name") else None,
                is_ai_data_processing_approved=bool(org.get("is_ai_data_processing_approved", False)),
                is_ai_training_opted_in=bool(org.get("is_ai_training_opted_in", False)),
            ),
            skill=skill,
            companion_skills=companion_skills,
            config={key: value for key, value in config.items() if key in self.CONFIG_FIELDS},
            steering=self.plan.steering,
            prompt_mode="native",
            time_strings=self.plan.time_strings,
            string_replacements=self.plan.string_replacements,
            source_project_url=self.plan.source_project_url,
            users=sorted(self.users.values(), key=lambda user: user.id),
            state=ScoutEnvironmentStartingState(
                profile=profile_record,
                memory=memory_records,
                reports=reports,
                report_artefacts=artefacts,
                notes=[
                    self._record(
                        row,
                        {
                            "skill_name": row["skill_name"],
                            "content": row["content"],
                            "created_by_id": self._named_author(row.get("created_by_name")),
                            "expires_at": row.get("expires_at"),
                            "origin": row["origin"],
                        },
                    )
                    for row in notes
                ],
                runs=[
                    self._record(
                        row, {key: value for key, value in row.items() if key in self.RUN_FIELDS}, identity="run_id"
                    )
                    for row in runs
                ],
            ),
        )
        if len(case.state.records()) > self.plan.max_context_rows:
            raise SourceExportError("Related context exceeds the explicit export limit.")
        dates = self._structured_dates(case.model_dump(mode="json"))
        for metric in metrics:
            dates.update(self._structured_dates(metric.model_dump(mode="json")))
        case = ScoutEnvironmentCase.model_validate(
            {**case.model_dump(), "time_strings": sorted(dates | set(case.time_strings))}
        )
        source_context = case.model_dump_json().lower()
        if any(str(metric.id) in source_context or metric.id.hex in source_context for metric in metrics):
            raise SourceExportError(
                "Scout context references a source metric UUID. Metric identity links need a separate adapter; name-based metric reads are supported."
            )
        ScoutEnvironmentSupport.validate(case)
        return SourceSnapshot(case=case, metrics=metrics, identity_mappings=self.identity_mappings)
