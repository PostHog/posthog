from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import cast
from uuid import UUID, uuid5

from django.db import models, transaction

from pydantic import JsonValue
from social_django.models import UserSocialAuth

from posthog.models import Organization, OrganizationMembership, Project, Team, User

from products.posthog_ai.eval_harness.environment.restore import EnvironmentReceipt, PreparedEnvironment
from products.posthog_ai.eval_harness.environment.transform import EnvironmentTransform
from products.signals.backend.models import (
    SignalProjectProfile,
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutNote,
    SignalScoutRun,
    SignalScratchpad,
    SignalTeamConfig,
)
from products.signals.backend.scout_harness.eval_environment.schema import (
    ScoutEnvironmentCase,
    ScoutEnvironmentRecord,
    ScoutEnvironmentSeed,
    ScoutEnvironmentUser,
)
from products.signals.backend.scout_harness.lazy_seed import scout_skill_row_origin
from products.signals.backend.scout_harness.profile import INVENTORY_SOURCE_VERSION
from products.signals.backend.suggested_reviewer_index import sync_suggested_reviewer_index
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile, LLMSkillOwner
from products.tasks.backend.models import Task, TaskRun


class ScoutEnvironmentState:
    _CONFIG_FIELDS = frozenset(
        {
            "display_name",
            "emit",
            "model",
            "allowed_mcp_tools",
            "tool_preset",
            "write_scopes",
            "structured_output_schema",
            "tags",
            "run_interval_minutes",
            "run_cron_schedule",
            "precheck_query",
            "precheck_disabled",
            "rubrics",
            "lifecycle_locked",
            "network_access",
            "created_at",
            "updated_at",
            "last_run_at",
            "enabled",
            "mcp_gateway_server_ids",
            "output_destinations",
            "repositories",
        }
    )
    _REPORT_FIELDS = frozenset(
        {
            "status",
            "status_before_suppression",
            "total_weight",
            "signal_count",
            "signals_at_run",
            "run_count",
            "signals_researched",
            "implemented_at_run_count",
            "content_revision_count",
            "implemented_at_revision_count",
            "corroboration_count",
            "title",
            "summary",
            "error",
            "charts",
            "metrics",
            "suggested_prompts",
            "promoted_at",
            "last_run_at",
            "monitoring_started_at",
            "first_visible_at",
            "inbox_notified_at",
            "latest_actionability",
            "latest_already_addressed",
            "billing_exempt_reason",
        }
    )
    _RUN_FIELDS = frozenset(
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
        }
    )

    def __init__(self, case: ScoutEnvironmentCase, receipt: EnvironmentReceipt) -> None:
        self.case = case
        self.receipt = receipt
        self.user_ids: dict[str, int] = {}
        self.references: dict[type[models.Model], set[UUID]] = {
            SignalScoutRun: {record.id for record in case.state.runs},
            SignalReport: {record.id for record in case.state.reports},
            SignalReportArtefact: {record.id for record in case.state.report_artefacts},
            Task: set(),
        }
        identifiers = [case.skill.id, *(row.id for row in case.state.records())]
        for user in case.users:
            if user.uuid:
                identifiers.append(user.uuid)
        for run in case.state.runs:
            task_id = UUID(str(run.fields.get("task_id") or uuid5(run.id, "task")))
            task_run_id = UUID(str(run.fields.get("task_run_id") or uuid5(run.id, "task-run")))
            identifiers.extend([task_id, task_run_id])
            self.references[Task].add(task_id)
        self.transform = EnvironmentTransform(
            source_cutoff=case.source_cutoff,
            target_cutoff=receipt.target_cutoff,
            namespace=receipt.identity_namespace,
            record_ids=list(dict.fromkeys(identifiers)),
            time_strings=case.time_strings,
            string_replacements=case.string_replacements,
        )

    @property
    def team_id(self) -> int:
        if self.receipt.team_id is None:
            raise ValueError("Scout state requires a prepared project.")
        return self.receipt.team_id

    def _user(self, source: object) -> int | None:
        if source is None:
            return None
        try:
            return self.user_ids[str(source)]
        except KeyError as error:
            raise ValueError("A starting-state user reference has no supplied identity.") from error

    def _fields(
        self, model: type[models.Model], values: dict[str, JsonValue], allowed: frozenset[str]
    ) -> dict[str, object]:
        unknown = values.keys() - allowed
        if unknown:
            raise ValueError(f"Unsupported {model.__name__} reconstruction fields: {', '.join(sorted(unknown))}")
        result: dict[str, object] = {}
        by_name = {field.attname: field for field in model._meta.concrete_fields}
        for name, value in values.items():
            field = by_name[name]
            if isinstance(field, models.DateTimeField) and value is not None:
                parsed = cast(datetime, field.to_python(value))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("Reconstructed timestamps must include a timezone.")
                if name != "expires_at" and parsed > self.case.checkpoint:
                    raise ValueError("Starting-state timestamps cannot include observations after the checkpoint.")
                result[name] = parsed + self.transform.delta
            elif isinstance(field, models.ForeignKey) and field.related_model is User:
                result[name] = self._user(value)
            elif isinstance(field, models.ForeignKey) and value is not None:
                source_id = UUID(str(value))
                related_model = field.related_model
                if not isinstance(related_model, type) or source_id not in self.references.get(related_model, set()):
                    raise ValueError("Starting-state relationships must refer to supplied local records.")
                result[name] = self.transform.identity(source_id)
            else:
                result[name] = self.transform.value(value)
            if not isinstance(field, models.JSONField):
                result[name] = field.to_python(result[name])
            if isinstance(field, models.DecimalField) and result[name] is not None:
                result[name] = cast(Decimal, result[name]).quantize(
                    Decimal(1).scaleb(-field.decimal_places), rounding=ROUND_HALF_UP
                )
        return result

    def _config_values(self) -> dict[str, object]:
        source_config = dict(self.case.config)
        source_config.pop("reasoning_effort", None)
        for name in ("mcp_gateway_server_ids", "output_destinations", "repositories"):
            if source_config.get(name):
                raise ValueError("External scout connections require an isolated local reconstruction adapter.")
        values = self._fields(SignalScoutConfig, source_config, self._CONFIG_FIELDS)
        values.update(enabled=False, status=SignalScoutConfig.Status.PAUSED_BY_USER)
        return values

    def _insert(
        self,
        model: type[models.Model],
        record: ScoutEnvironmentRecord,
        allowed: frozenset[str],
        *,
        extra: dict[str, object] | None = None,
    ) -> models.Model:
        fields = self._fields(model, record.fields, allowed)
        fields.update(extra or {})
        row = model(id=self.transform.identity(record.id), team_id=self.team_id, **fields)
        manager = model._default_manager
        queryset = (
            manager.for_team(self.team_id) if hasattr(manager, "for_team") else manager.filter(team_id=self.team_id)
        )
        queryset.bulk_create([row])
        dates = {
            ("computed_at" if model is SignalProjectProfile else "created_at"): record.created_at + self.transform.delta
        }
        if any(field.name == "updated_at" for field in model._meta.fields):
            dates["updated_at"] = (record.updated_at or record.created_at) + self.transform.delta
        queryset.filter(pk=row.pk).update(**dates)
        return row

    def _organization_values(self) -> dict[str, object]:
        values = self.case.organization.model_dump(exclude_none=True)
        values["name"] = self.transform.text(self.case.organization.name or "Organization")
        return values

    def _project_name(self) -> str:
        return self.transform.text(self.case.project_name or "Project")

    def _member_email(self, source: ScoutEnvironmentUser) -> str:
        identifier = self.transform.identity(source.uuid or uuid5(self.case.skill.id, source.id))
        return source.email or f"member-{identifier.hex}@example.com"

    def _seed_users(self, team: Team, operator: User) -> None:
        for source in self.case.users:
            if source.is_operator:
                user = operator
                user.first_name, user.last_name = source.first_name, source.last_name
                if source.email:
                    if User.objects.exclude(id=user.id).filter(email=source.email).exists():
                        raise ValueError("The reconstructed operator email belongs to another local user.")
                    user.email = source.email
                user.save(update_fields=["first_name", "last_name", "email"])
            else:
                identifier = self.transform.identity(source.uuid or uuid5(self.case.skill.id, source.id))
                email = self._member_email(source)
                if User.objects.filter(email=email).exists():
                    raise ValueError("A reconstructed user email already exists outside this fresh environment.")
                user = User(
                    uuid=identifier,
                    email=email,
                    first_name=source.first_name,
                    last_name=source.last_name,
                    is_active=True,
                )
                user.set_unusable_password()
                User.objects.bulk_create([user])
                OrganizationMembership.objects.bulk_create(
                    [OrganizationMembership(organization_id=team.organization_id, user=user)]
                )
            self.user_ids[source.id] = user.id
            if source.uuid:
                self.user_ids[str(source.uuid)] = user.id
                self.transform.ids[source.uuid] = user.uuid
            if source.github_login:
                UserSocialAuth.objects.create(
                    user_id=user.id,
                    provider="github",
                    uid=f"eval:{self.receipt.identity_namespace}:{source.id}",
                    extra_data={"login": source.github_login},
                )
                # An existing GitHub user integration or social login takes precedence over this binding.
                if user.get_github_login() != source.github_login:
                    raise ValueError("The reconstructed member already resolves to another GitHub identity.")

    def _seed_skill(self, team: Team) -> LLMSkill:
        source = self.case.skill
        row = LLMSkill.objects.create(
            id=self.transform.identity(source.id),
            team_id=team.id,
            name=source.name,
            description=self.transform.text(source.description),
            body=self.transform.text(source.body),
            version=source.version,
            allowed_tools=source.allowed_tools,
            metadata=self.transform.value(source.metadata),
            category="scout",
            created_by_id=self._user(source.created_by),
            license=source.license,
            compatibility=source.compatibility,
            created_at=(source.created_at or self.case.checkpoint) + self.transform.delta,
        )
        for path, content in source.files.items():
            LLMSkillFile.objects.create(
                skill=row,
                path=path,
                content=self.transform.text(content),
                content_type=source.file_content_types.get(path, "text/plain"),
            )
        LLMSkill.objects.filter(team_id=team.id, id=row.id).update(
            updated_at=(source.updated_at or source.created_at or self.case.checkpoint) + self.transform.delta
        )
        for owner in source.owners:
            user_id = self._user(owner)
            if user_id is None:
                raise ValueError("A skill owner requires a supplied user identity.")
            LLMSkillOwner.objects.for_team(team.id, canonical=True).create(
                team_id=team.id,
                skill_name=source.name,
                user_id=user_id,
                created_at=(source.created_at or self.case.checkpoint) + self.transform.delta,
            )
        if scout_skill_row_origin(row) != source.origin:
            raise ValueError("Reconstructed skill metadata does not preserve its recorded origin.")
        return row

    def _seed_run(self, record: ScoutEnvironmentRecord, config: SignalScoutConfig) -> None:
        fields = dict(record.fields)
        task_id = UUID(str(fields.pop("task_id", None) or uuid5(record.id, "task")))
        task_run_id = UUID(str(fields.pop("task_run_id", None) or uuid5(record.id, "task-run")))
        status = str(fields.pop("status", TaskRun.Status.COMPLETED))
        started = fields.pop("started_at", record.created_at.isoformat())
        completed = fields.pop("completed_at", None)
        error = fields.pop("error", None)
        fields.pop("failure_reason", None)
        fields.pop("task_url", None)
        task = Task(
            id=self.transform.identity(task_id),
            team_id=self.team_id,
            title=str(fields.get("skill_name", "")),
            description="",
            origin_product="signals_scout",
            internal=True,
            created_by_id=self.receipt.user_id,
            created_at=record.created_at + self.transform.delta,
        )
        if not Task.objects.filter(team_id=self.team_id, id=task.id).exists():
            Task.objects.bulk_create([task])
            Task.objects.filter(team_id=self.team_id, id=task.id).update(
                created_at=record.created_at + self.transform.delta,
                updated_at=(record.updated_at or record.created_at) + self.transform.delta,
                last_activity_at=(record.updated_at or record.created_at) + self.transform.delta,
            )
        run = TaskRun(
            id=self.transform.identity(task_run_id),
            task_id=task.id,
            team_id=self.team_id,
            origin_product="signals_scout",
            environment=TaskRun.Environment.LOCAL,
            **self._fields(
                TaskRun,
                {"status": status, "created_at": started, "completed_at": completed, "error_message": error},
                frozenset({"status", "created_at", "completed_at", "error_message"}),
            ),
        )
        TaskRun.objects.bulk_create([run])
        TaskRun.objects.filter(team_id=self.team_id, id=run.id).update(
            created_at=run.created_at,
            updated_at=(record.updated_at or record.created_at) + self.transform.delta,
        )
        source = record.model_copy(update={"fields": fields})
        self._insert(
            SignalScoutRun,
            source,
            self._RUN_FIELDS,
            extra={
                "task_run_id": run.id,
                "scout_config_id": config.id if fields.get("skill_name") == config.skill_name else None,
            },
        )

    def _seed(self) -> ScoutEnvironmentSeed:
        identity = PreparedEnvironment.assert_local()
        receipt = self.receipt
        if receipt.phase != "complete" or not receipt.team_id or not receipt.user_id or receipt.databases != identity:
            raise ValueError("Scout state requires a complete import receipt for these local databases.")
        if (
            receipt.environment_id != self.case.environment_id
            or receipt.source_cutoff != self.case.source_cutoff
            or receipt.timezone != self.case.timezone
        ):
            raise ValueError("The scout case and event import describe different environments.")
        team = Team.objects.get(id=receipt.team_id, organization_id=receipt.organization_id, is_demo=False)
        operator = User.objects.get(id=receipt.user_id, is_active=True)
        if not OrganizationMembership.objects.filter(
            organization_id=team.organization_id, user_id=operator.id
        ).exists():
            raise ValueError("The local operator does not belong to the prepared environment.")
        for model in (SignalScoutConfig, SignalScoutRun, SignalScratchpad, SignalScoutNote, SignalProjectProfile):
            if model.objects.for_team(team.id).exists():
                raise ValueError("Scout state is already populated; restore into a fresh project before seeding.")
        if LLMSkill.objects.filter(team_id=team.id).exists() or SignalReport.objects.filter(team_id=team.id).exists():
            raise ValueError("Scout state requires an empty skill/report baseline.")
        Organization.objects.filter(id=team.organization_id).update(**self._organization_values())
        Team.objects.filter(id=team.id, organization_id=team.organization_id).update(name=self._project_name())
        Project.objects.filter(id=team.project_id, organization_id=team.organization_id).update(
            name=self._project_name()
        )
        self._seed_users(team, operator)
        skill = self._seed_skill(team)
        config_values = self._config_values()
        config = SignalScoutConfig(
            id=uuid5(receipt.identity_namespace, f"scout-config:{self.case.environment_id}"),
            team_id=team.id,
            skill_name=skill.name,
            **config_values,
        )
        SignalScoutConfig.objects.for_team(team.id).bulk_create([config])
        config_dates = {key: value for key, value in config_values.items() if key in {"created_at", "updated_at"}}
        if config_dates:
            SignalScoutConfig.objects.for_team(team.id).filter(id=config.id).update(**config_dates)
        SignalTeamConfig.objects.update_or_create(team_id=team.id, defaults={"autostart_enabled": False})
        for record in self.case.state.runs:
            self._seed_run(record, config)
        for record in self.case.state.reports:
            self._insert(SignalReport, record, self._REPORT_FIELDS)
        reviewer_report_ids: set[str] = set()
        for record in self.case.state.report_artefacts:
            artefact = cast(
                SignalReportArtefact,
                self._insert(
                    SignalReportArtefact,
                    record,
                    frozenset(
                        {
                            "report_id",
                            "type",
                            "content",
                            "actor_kind",
                            "actor_agent",
                            "created_by_id",
                            "task_id",
                            "claim_id",
                        }
                    ),
                ),
            )
            if artefact.type == SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS:
                reviewer_report_ids.add(str(artefact.report_id))
        # Bulk inserts skip the save receiver that maintains the reviewer index, so rebuild it from the restored rows.
        for report_id in sorted(reviewer_report_ids):
            sync_suggested_reviewer_index(team_id=team.id, report_id=report_id)
        for record in self.case.state.notes:
            self._insert(
                SignalScoutNote,
                record,
                frozenset({"skill_name", "content", "created_by_id", "expires_at", "origin"}),
            )
        for record in self.case.state.memory:
            self._insert(
                SignalScratchpad,
                record,
                frozenset({"key", "content", "created_by_run_id", "created_by_identity", "expires_at"}),
            )
        if profile := self.case.state.profile:
            # Local trials read the starting profile through the current-version reader, so another version is unusable.
            if profile.fields.get("source_version") != INVENTORY_SOURCE_VERSION:
                raise ValueError(
                    f"The recorded project profile must use source version {INVENTORY_SOURCE_VERSION}; "
                    "rebuild it on this checkout before preparing the environment."
                )
            self._insert(SignalProjectProfile, profile, frozenset({"expires_at", "source_version", "payload"}))
        identities = {str(source): str(target) for source, target in self.transform.ids.items()}
        identities.update({f"user:{source}": str(target) for source, target in self.user_ids.items()})
        return ScoutEnvironmentSeed(
            environment_id=self.case.environment_id,
            team_id=team.id,
            user_id=operator.id,
            config_id=config.id,
            skill_id=skill.id,
            identity_map=identities,
            time_delta_seconds=self.transform.delta.total_seconds(),
            steering=self.transform.text(self.case.steering),
        )

    @classmethod
    def seed(cls, case: ScoutEnvironmentCase, receipt: EnvironmentReceipt) -> ScoutEnvironmentSeed:
        with transaction.atomic():
            return cls(case, receipt)._seed()

    @staticmethod
    def _assert_values(row: models.Model, values: dict[str, object]) -> None:
        if any(getattr(row, name) != value for name, value in values.items()):
            raise ValueError(f"The prepared {type(row).__name__} baseline changed.")

    def _verify_records(
        self, model: type[models.Model], records: list[ScoutEnvironmentRecord], allowed: frozenset[str]
    ) -> None:
        manager = model._default_manager
        rows = (
            manager.for_team(self.receipt.team_id)
            if hasattr(manager, "for_team")
            else manager.filter(team_id=self.receipt.team_id)
        )
        if model is SignalScoutRun:
            rows = rows.exclude(pk__in=rows.filter(metadata__scout_trial__version=1).values("pk"))
        expected_ids = {self.transform.identity(record.id) for record in records}
        if set(rows.values_list("id", flat=True)) != expected_ids:
            raise ValueError(f"The prepared {model.__name__} record set changed.")
        for record in records:
            values = self._fields(model, record.fields, allowed)
            values["computed_at" if model is SignalProjectProfile else "created_at"] = (
                record.created_at + self.transform.delta
            )
            if any(field.name == "updated_at" for field in model._meta.fields):
                values["updated_at"] = (record.updated_at or record.created_at) + self.transform.delta
            self._assert_values(rows.get(id=self.transform.identity(record.id)), values)

    def _verify(self, seed: ScoutEnvironmentSeed) -> None:
        identity = PreparedEnvironment.assert_local()
        if (
            self.receipt.phase != "complete"
            or self.receipt.databases != identity
            or seed.team_id != self.receipt.team_id
            or seed.user_id != self.receipt.user_id
            or seed.environment_id != self.case.environment_id
            or self.receipt.environment_id != self.case.environment_id
            or self.receipt.source_cutoff != self.case.source_cutoff
            or self.receipt.timezone != self.case.timezone
            or seed.time_delta_seconds != self.transform.delta.total_seconds()
        ):
            raise ValueError("The scout seed does not belong to this prepared local environment.")
        team = Team.objects.get(id=seed.team_id, organization_id=self.receipt.organization_id, is_demo=False)
        if team.timezone != self.case.timezone:
            raise ValueError("The prepared project timezone changed.")
        self._assert_values(team.organization, self._organization_values())
        self._assert_values(team, {"name": self._project_name()})
        self._assert_values(team.project, {"name": self._project_name()})
        self.user_ids = {
            source.removeprefix("user:"): int(target)
            for source, target in seed.identity_map.items()
            if source.startswith("user:")
        }
        for source in self.case.users:
            user = User.objects.get(id=self._user(source.id), is_active=True)
            self._assert_values(user, {"first_name": source.first_name, "last_name": source.last_name})
            if (source.email or not source.is_operator) and user.email != (
                source.email if source.is_operator else self._member_email(source)
            ):
                raise ValueError("The prepared member identity changed.")
            if not OrganizationMembership.objects.filter(
                organization_id=team.organization_id, user_id=user.id
            ).exists():
                raise ValueError("A prepared member no longer has access to the project.")
            if source.uuid:
                self.transform.ids[source.uuid] = user.uuid
                if seed.identity_map.get(str(source.uuid)) != str(user.uuid):
                    raise ValueError("The prepared user UUID mapping changed.")
            if source.github_login and user.get_github_login() != source.github_login:
                raise ValueError("The prepared member GitHub identity changed.")
        skill = LLMSkill.objects.get(team_id=team.id, id=seed.skill_id)
        source_skill = self.case.skill
        self._assert_values(
            skill,
            {
                "name": source_skill.name,
                "body": self.transform.text(source_skill.body),
                "description": self.transform.text(source_skill.description),
                "version": source_skill.version,
                "allowed_tools": source_skill.allowed_tools,
                "metadata": self.transform.value(source_skill.metadata),
                "created_by_id": self._user(source_skill.created_by),
                "deleted": False,
                "is_latest": True,
            },
        )
        if scout_skill_row_origin(skill) != source_skill.origin:
            raise ValueError("The prepared scout origin changed.")
        files = {row.path: (row.content, row.content_type) for row in skill.files.all()}
        if files != {
            path: (self.transform.text(content), source_skill.file_content_types.get(path, "text/plain"))
            for path, content in source_skill.files.items()
        }:
            raise ValueError("The prepared skill files changed.")
        owners = set(
            LLMSkillOwner.objects.for_team(team.id, canonical=True)
            .filter(skill_name=source_skill.name)
            .values_list("user_id", flat=True)
        )
        if owners != {self._user(source) for source in source_skill.owners}:
            raise ValueError("The prepared skill owners changed.")
        config = SignalScoutConfig.objects.for_team(team.id).get(id=seed.config_id, skill_name=source_skill.name)
        self._assert_values(config, self._config_values())
        if SignalTeamConfig.objects.get(team_id=team.id).autostart_enabled is not False:
            raise ValueError("The isolated project autostart protection changed.")
        self._verify_records(
            SignalScoutNote,
            self.case.state.notes,
            frozenset({"skill_name", "content", "created_by_id", "expires_at", "origin"}),
        )
        self._verify_records(
            SignalScratchpad,
            self.case.state.memory,
            frozenset({"key", "content", "created_by_run_id", "created_by_identity", "expires_at"}),
        )
        self._verify_records(SignalReport, self.case.state.reports, self._REPORT_FIELDS)
        self._verify_records(
            SignalReportArtefact,
            self.case.state.report_artefacts,
            frozenset(
                {"report_id", "type", "content", "actor_kind", "actor_agent", "created_by_id", "task_id", "claim_id"}
            ),
        )
        self._verify_records(
            SignalProjectProfile,
            [self.case.state.profile] if self.case.state.profile else [],
            frozenset({"expires_at", "source_version", "payload"}),
        )
        run_records = []
        for record in self.case.state.runs:
            fields = {name: value for name, value in record.fields.items() if name in self._RUN_FIELDS}
            run_records.append(record.model_copy(update={"fields": fields}))
            run = (
                SignalScoutRun.objects.for_team(team.id)
                .select_related("task_run__task")
                .get(id=self.transform.identity(record.id))
            )
            expected = self._fields(
                TaskRun,
                {
                    "status": record.fields.get("status", TaskRun.Status.COMPLETED),
                    "created_at": record.fields.get("started_at", record.created_at.isoformat()),
                    "completed_at": record.fields.get("completed_at"),
                    "error_message": record.fields.get("error"),
                },
                frozenset({"status", "created_at", "completed_at", "error_message"}),
            )
            self._assert_values(run.task_run, expected)
            if run.task_run.team_id != team.id or run.task_run.task.team_id != team.id:
                raise ValueError("A historical task no longer belongs to the isolated project.")
        self._verify_records(SignalScoutRun, run_records, self._RUN_FIELDS)

    @classmethod
    def verify(cls, case: ScoutEnvironmentCase, receipt: EnvironmentReceipt, seed: ScoutEnvironmentSeed) -> None:
        cls(case, receipt)._verify(seed)
