from __future__ import annotations

import os
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import UUID, uuid4

from django.db import transaction

from pydantic import AwareDatetime, Field, JsonValue

from posthog.dataclasses import frozen
from posthog.health import get_pending_postgres_migrations
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.product_db_migrations import collect_unapplied_product_migrations

from products.data_catalog.backend.facade.api import Metric
from products.posthog_ai.eval_harness.environment.dataset import EnvironmentDataset
from products.posthog_ai.eval_harness.environment.events import EnvironmentEvents
from products.posthog_ai.eval_harness.environment.guard import EnvironmentMigrationsPending, assert_local_databases
from products.posthog_ai.eval_harness.environment.ingestion import EnvironmentIngestion
from products.posthog_ai.eval_harness.environment.schema import EnvironmentMetric, EnvironmentModel
from products.posthog_ai.eval_harness.environment.transform import EnvironmentTransform


class EnvironmentResult(EnvironmentModel):
    team_id: int
    project_id: int
    organization_id: UUID
    user_id: int
    target_cutoff: AwareDatetime
    event_count: int
    metric_count: int
    reused: bool
    receipt_path: Path
    credentials_path: Path | None


class EnvironmentReceipt(EnvironmentModel):
    schema_version: Literal[1] = 1
    phase: Literal["pending", "failed", "complete"]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_id: str
    source_cutoff: AwareDatetime
    target_cutoff: AwareDatetime
    timezone: str
    databases: dict[str, str]
    identity_namespace: UUID
    provenance: dict[str, str]
    team_id: int | None = None
    project_id: int | None = None
    organization_id: UUID | None = None
    user_id: int | None = None
    metric_ids: list[UUID] = Field(default_factory=list)
    event_validation: dict[str, JsonValue] = Field(default_factory=dict)
    created_login: bool = False
    failure_type: str | None = None
    event_ingestion: EnvironmentIngestion | None = None


@frozen
class _ProjectOwner:
    team: Team
    user: User
    created_login: bool


class PreparedEnvironment:
    @staticmethod
    def assert_local() -> dict[str, str]:
        return assert_local_databases()

    @staticmethod
    def assert_migrations_current() -> None:
        assert_local_databases()
        pending = get_pending_postgres_migrations()
        pending_products = collect_unapplied_product_migrations()
        if pending or pending_products:
            raise EnvironmentMigrationsPending(
                "The local databases have unapplied Django migrations. Run the normal app migrations from this "
                "checkout before restoring an environment. No import was started."
            )

    @staticmethod
    def read_receipt(workspace: Path) -> EnvironmentReceipt | None:
        path = workspace / "receipt.json"
        if workspace.is_symlink() or path.is_symlink():
            raise ValueError("The environment workspace and receipt must not be symbolic links.")
        return EnvironmentReceipt.model_validate_json(path.read_bytes()) if path.exists() else None

    @staticmethod
    def _write_private(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _select_user(user_id: int | None) -> User | None:
        if user_id is not None:
            return User.objects.get(id=user_id, is_active=True)
        users = list(User.objects.filter(is_active=True).order_by("id")[:2])
        if len(users) > 1:
            raise ValueError("Multiple active local users exist; select --user-id.")
        return users[0] if users else None

    @classmethod
    def _create_project(cls, user: User | None, workspace: Path, timezone: str) -> _ProjectOwner:
        created_login = user is None
        if user is None:
            password = secrets.token_urlsafe(32)
            email = f"eval-environment-{uuid4().hex[:12]}@example.com"
            cls._write_private(
                workspace / "login-credentials.json", json.dumps({"email": email, "password": password}) + "\n"
            )
            user = User.objects.create_user(email=email, password=password, first_name="Local evaluation operator")
        organization = Organization.objects.create(
            name="Evaluation environment", is_ai_data_processing_approved=False, is_ai_training_opted_in=False
        )
        team = Team.objects.create(organization=organization, name="Evaluation environment", timezone=timezone)
        # Joining through User.join also changes the operator's current project.
        OrganizationMembership.objects.create(
            organization=organization, user=user, level=OrganizationMembership.Level.OWNER
        )
        if created_login:
            user.current_organization = organization
            user.current_team = team
            user.save(update_fields=["current_organization", "current_team"])
        return _ProjectOwner(team=team, user=user, created_login=created_login)

    @staticmethod
    def _metric_owners(metric: EnvironmentMetric, user_id: int) -> dict[str, object]:
        return {
            "owner_id": user_id if metric.owner_id is not None else None,
            "approved_by_id": user_id if metric.approved_by_id is not None else None,
            "created_by_id": user_id if metric.created_by_id is not None else None,
        }

    @classmethod
    def _install_metrics(
        cls, dataset: EnvironmentDataset, transformer: EnvironmentTransform, owner: _ProjectOwner
    ) -> None:
        for metric in dataset.metrics:
            transformer.insert(
                Metric.objects.for_team(owner.team.id),
                Metric,
                metric,
                owner.team.id,
                overrides=cls._metric_owners(metric, owner.user.id),
            )

    @staticmethod
    def _transform(
        dataset: EnvironmentDataset, cutoff: datetime, namespace: UUID | None = None
    ) -> EnvironmentTransform:
        return EnvironmentTransform(
            source_cutoff=dataset.manifest.source_cutoff,
            target_cutoff=cutoff,
            record_ids=[metric.id for metric in dataset.metrics],
            namespace=namespace,
            time_strings=dataset.manifest.time_strings,
            string_replacements=dataset.manifest.string_replacements,
        )

    @staticmethod
    def _result(
        receipt: EnvironmentReceipt, workspace: Path, dataset: EnvironmentDataset, *, reused: bool
    ) -> EnvironmentResult:
        assert receipt.team_id is not None and receipt.project_id is not None
        assert receipt.organization_id is not None and receipt.user_id is not None
        return EnvironmentResult(
            team_id=receipt.team_id,
            project_id=receipt.project_id,
            organization_id=receipt.organization_id,
            user_id=receipt.user_id,
            target_cutoff=receipt.target_cutoff,
            event_count=dataset.manifest.event_count,
            metric_count=len(receipt.metric_ids),
            reused=reused,
            receipt_path=workspace / "receipt.json",
            credentials_path=workspace / "login-credentials.json" if receipt.created_login else None,
        )

    @classmethod
    def _reuse(cls, receipt: EnvironmentReceipt, workspace: Path, dataset: EnvironmentDataset) -> EnvironmentResult:
        if receipt.team_id is None or receipt.user_id is None:
            raise ValueError("The completed import receipt has no project or operator.")
        team = Team.objects.get(
            id=receipt.team_id, project_id=receipt.project_id, organization_id=receipt.organization_id, is_demo=False
        )
        User.objects.get(
            id=receipt.user_id, is_active=True, organization_membership__organization_id=receipt.organization_id
        )
        if team.timezone != dataset.manifest.timezone:
            raise ValueError("The restored project timezone changed.")
        if receipt.event_ingestion is None:
            raise ValueError("The import receipt has no event-ingestion protection; restore into a fresh workspace.")
        receipt.event_ingestion.verify(team)
        transformer = cls._transform(dataset, receipt.target_cutoff, receipt.identity_namespace)
        expected_metric_ids = {transformer.identity(metric.id) for metric in dataset.metrics}
        if (
            set(receipt.metric_ids) != expected_metric_ids
            or set(Metric.objects.for_team(team.id).values_list("id", flat=True)) != expected_metric_ids
        ):
            raise ValueError("The restored project metrics changed.")
        for metric in dataset.metrics:
            restored_metric = Metric.objects.for_team(team.id).get(id=transformer.identity(metric.id))
            expected = cast(dict[str, object], transformer.value(metric.model_dump(exclude={"team_id"})))
            expected.update(cls._metric_owners(metric, receipt.user_id))
            expected["updated_at"] = (metric.updated_at or metric.created_at) + transformer.delta
            if any(getattr(restored_metric, field) != value for field, value in expected.items()):
                raise ValueError("The restored metric changed.")
        validation = EnvironmentEvents.validate(team.id, EnvironmentEvents.summaries(dataset, transformer))
        if validation != receipt.event_validation:
            raise ValueError("The restored event validation differs from the receipt.")
        return cls._result(receipt, workspace, dataset, reused=True)

    @classmethod
    def restore(
        cls,
        dataset: EnvironmentDataset,
        workspace: Path,
        target_cutoff: datetime | None = None,
        user_id: int | None = None,
        provenance: dict[str, str] | None = None,
    ) -> EnvironmentResult:
        databases = cls.assert_local()
        dataset.validate_files()
        receipt = cls.read_receipt(workspace)
        cutoff = target_cutoff or (receipt.target_cutoff if receipt else datetime.now(UTC))
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("The target cutoff must include a timezone.")
        cutoff = cutoff.astimezone(UTC)
        if receipt is not None:
            if receipt.phase != "complete":
                raise ValueError("The previous import is incomplete; use a fresh --state-dir. No events were appended.")
            if (
                receipt.manifest_sha256 != dataset.manifest_sha256
                or receipt.environment_id != dataset.manifest.environment_id
                or receipt.source_cutoff != dataset.manifest.source_cutoff
                or receipt.timezone != dataset.manifest.timezone
                or receipt.target_cutoff != cutoff
                or receipt.databases != databases
                or (user_id is not None and receipt.user_id != user_id)
            ):
                raise ValueError("The existing receipt belongs to different import inputs; use a fresh --state-dir.")
            cls.assert_migrations_current()
            return cls._reuse(receipt, workspace, dataset)
        cls.assert_migrations_current()
        selected_user = cls._select_user(user_id)
        EnvironmentEvents.preflight()
        transformer = cls._transform(dataset, cutoff)
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
        workspace.chmod(0o700)
        receipt = EnvironmentReceipt(
            phase="pending",
            manifest_sha256=dataset.manifest_sha256,
            environment_id=dataset.manifest.environment_id,
            source_cutoff=dataset.manifest.source_cutoff,
            target_cutoff=cutoff,
            timezone=dataset.manifest.timezone,
            databases=databases,
            identity_namespace=transformer.namespace,
            provenance=provenance or {},
        )
        receipt_path = workspace / "receipt.json"
        cls._write_private(receipt_path, receipt.model_dump_json(indent=2) + "\n")
        try:
            with transaction.atomic():
                owner = cls._create_project(selected_user, workspace, dataset.manifest.timezone)
                EnvironmentEvents.preflight(owner.team.id)
                cls._install_metrics(dataset, transformer, owner)
                event_ingestion = EnvironmentIngestion.install(owner.team, owner.user)
            receipt = receipt.model_copy(
                update={
                    "team_id": owner.team.id,
                    "project_id": owner.team.project_id,
                    "organization_id": owner.team.organization_id,
                    "user_id": owner.user.id,
                    "created_login": owner.created_login,
                    "metric_ids": [transformer.identity(metric.id) for metric in dataset.metrics],
                    "event_ingestion": event_ingestion,
                }
            )
            cls._write_private(receipt_path, receipt.model_dump_json(indent=2) + "\n")
            validation = EnvironmentEvents.restore(dataset, transformer, owner.team.id)
            Team.objects.filter(id=owner.team.id).update(
                ingested_event=bool(dataset.manifest.event_count), completed_snippet_onboarding=True
            )
            receipt = receipt.model_copy(update={"phase": "complete", "event_validation": validation})
            cls._write_private(receipt_path, receipt.model_dump_json(indent=2) + "\n")
        except BaseException as error:
            failed = receipt.model_copy(update={"phase": "failed", "failure_type": type(error).__name__})
            cls._write_private(receipt_path, failed.model_dump_json(indent=2) + "\n")
            raise
        return cls._result(receipt, workspace, dataset, reused=False)
