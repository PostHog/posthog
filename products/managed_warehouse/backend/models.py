from __future__ import annotations

from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.managed_warehouse.backend.model_observability import DuckgresServerManager, record_duckgres_server_access


class DuckgresServer(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Per-organization duckgres query server + DuckLake catalog connection details.

    Duckgres is a Postgres-protocol-compatible DuckDB server. Each org that uses
    duckgres for copy workflows/backfills needs its own connection entry. The
    DuckLake catalog is a *separate* Postgres metadata store (the duckgres server's
    query connection is not the same endpoint), so its connection is recorded here
    too under the ``catalog_*`` fields.
    """

    objects = DuckgresServerManager()

    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="duckgres_server",
    )

    # Duckgres query-server connection.
    host = models.CharField(max_length=255)
    port = models.IntegerField(default=5432)
    flight_port = models.IntegerField(default=8815)
    database = models.CharField(max_length=255, default="ducklake")
    username = models.CharField(max_length=255)
    password = EncryptedTextField(max_length=500)

    # DuckLake catalog Postgres connection — a separate metadata store from the
    # query server above. Nullable: an org may have a provisioned server before its
    # catalog row is recorded (the dev/env-var path doesn't need these at all).
    catalog_host = models.CharField(max_length=255, null=True, blank=True)
    catalog_port = models.IntegerField(default=5432)
    catalog_database = models.CharField(max_length=255, default="ducklake")
    catalog_username = models.CharField(max_length=255, null=True, blank=True)
    catalog_password = EncryptedTextField(max_length=500, null=True, blank=True)

    # S3 bucket backing the org's managed warehouse (no secrets — access is via IRSA / the
    # ClickHouse EC2 role). Written at provision time so the duckling backfill reads the
    # authoritative bucket name instead of re-deriving it. Nullable for rows provisioned
    # before this field existed.
    bucket = models.CharField(max_length=255, null=True, blank=True)
    # Region travels with the bucket: set alongside it, left NULL when no bucket is
    # recorded yet (status_for()'s self-heal fills both in once the control plane reports them).
    bucket_region = models.CharField(max_length=50, null=True, blank=True, default=None)

    class Meta:
        db_table = "posthog_duckgresserver"
        verbose_name = "Duckgres server"
        verbose_name_plural = "Duckgres servers"

    def to_catalog_public_config(self) -> dict[str, str]:
        """DuckLake catalog config without secrets (safe for logging/debugging)."""
        return {
            "DUCKLAKE_RDS_HOST": self.catalog_host or "",
            "DUCKLAKE_RDS_PORT": str(self.catalog_port),
            "DUCKLAKE_RDS_DATABASE": self.catalog_database,
            "DUCKLAKE_RDS_USERNAME": self.catalog_username or "",
            "DUCKLAKE_BUCKET": self.bucket or "",
            "DUCKLAKE_BUCKET_REGION": self.bucket_region or "",
            "DUCKLAKE_S3_ACCESS_KEY": "",
            "DUCKLAKE_S3_SECRET_KEY": "",
        }


class ManagedWarehouseSourceLifecycle(models.Model):
    """Non-secret generation fence for managed SQL-editor source lifecycle operations."""

    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="managed_warehouse_source_lifecycle",
        db_constraint=False,
    )
    generation = models.PositiveBigIntegerField(default=0)
    desired_active = models.BooleanField(default=True)
    legacy_conversion_generation = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "posthog_managedwarehousesourcelifecycle"


@receiver(post_save, sender=DuckgresServer, dispatch_uid="observe_duckgres_server_save")
def _observe_duckgres_server_save(*, created: bool, **kwargs: object) -> None:
    record_duckgres_server_access("create" if created else "update")


@receiver(post_delete, sender=DuckgresServer, dispatch_uid="observe_duckgres_server_delete")
def _observe_duckgres_server_delete(**kwargs: object) -> None:
    record_duckgres_server_access("delete")


class ManagedWarehouseSourceJob(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    class WorkflowType(models.TextChoices):
        COPY = "copy", "Copy"
        REGISTER = "register", "Register"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"
        STALE = "stale", "Stale"

    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="managed_warehouse_source_jobs",
        db_constraint=False,
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )
    environment_id = models.BigIntegerField()
    schema_id = models.UUIDField()
    source_job_id = models.CharField(max_length=400)
    attempt_id = models.CharField(max_length=500)
    workflow_type = models.CharField(max_length=16, choices=WorkflowType.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    workflow_id = models.CharField(max_length=400, null=True, blank=True)
    workflow_run_id = models.CharField(max_length=400, null=True, blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    latest_error = models.TextField(null=True, blank=True)

    class Meta(TeamScopedRootMixin.Meta):
        db_table = "posthog_managedwarehousesourcejob"
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "environment_id", "schema_id", "workflow_type", "attempt_id"],
                name="unique_managed_warehouse_source_job_attempt",
            )
        ]
        indexes = [
            models.Index(
                fields=["team", "environment_id", "schema_id", "-started_at"],
                name="mw_source_job_latest_idx",
            )
        ]
