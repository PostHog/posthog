from __future__ import annotations

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class DuckgresServer(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Per-organization duckgres query server + DuckLake catalog connection details.

    Duckgres is a Postgres-protocol-compatible DuckDB server. Each org that uses
    duckgres for copy workflows/backfills needs its own connection entry. The
    DuckLake catalog is a *separate* Postgres metadata store (the duckgres server's
    query connection is not the same endpoint), so its connection is recorded here
    too under the ``catalog_*`` fields.
    """

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


class DuckgresDailyUsage(UUIDModel):
    """One UTC day of managed-warehouse compute usage for one (team, query_source, worker size).

    Local durable mirror of duckgres's billing pull API (duckgres
    `docs/design/billing-pull-api.md`): a Temporal poller promotes complete
    day-so-far snapshots per organization and acks duckgres only at UTC day
    boundaries. A regressed org retains its last-good rows while healthy orgs
    advance. Once duckgres GCs an acked day this is the surviving copy until
    the usage report ships it, so it's a system of record, not a scratch
    buffer. Usage reports (v1 gathers and, later, v2 queries) read from this
    table; nothing else writes to it.
    """

    date = models.DateField()
    organization_id = models.UUIDField()
    # Not an FK: duckgres attributes usage to the org's default team, rows are
    # bulk-replaced every poll, and the billing mirror must survive team deletion.
    team_id = models.IntegerField()
    # "standard" | "endpoints" (open set — duckgres session GUC).
    query_source = models.CharField(max_length=32)
    # Worker size the usage accrued on, as exact decimals (e.g. 8 / 1.5 / 0.5).
    cpu = models.DecimalField(max_digits=12, decimal_places=6)
    mem_gib = models.DecimalField(max_digits=12, decimal_places=6)
    cpu_seconds = models.BigIntegerField()
    memory_seconds = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_duckgresdailyusage"
        verbose_name = "Duckgres daily usage"
        verbose_name_plural = "Duckgres daily usage"
        constraints = [
            # The org is part of the identity because an unresolved team stamp can be
            # shared across orgs (notably duckgres's sentinel team_id=0).
            models.UniqueConstraint(
                fields=["date", "organization_id", "team_id", "query_source", "cpu", "mem_gib"],
                name="duckgres_daily_usage_key",
            )
        ]


class DuckgresDailyStorageUsage(UUIDModel):
    """One UTC day of managed-warehouse storage usage (footprint integral) per team.

    Sibling of DuckgresDailyUsage for the pull API's `storage` array: one row
    per (org's default team, day), `gib_seconds` = tracked bytes x seconds /
    2^30 as duckgres's exact decimal. Maintained by the same poller
    transaction; read by the storage usage-report gather (which converts to
    decimal-GB hours — GiB vs GB conversion lives there, not here).
    """

    date = models.DateField()
    organization_id = models.UUIDField()
    team_id = models.IntegerField()
    # Up to ~13 integer digits (PB-month scale) + exactly 30 fractional digits.
    gib_seconds = models.DecimalField(max_digits=45, decimal_places=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_duckgresdailystorageusage"
        verbose_name = "Duckgres daily storage usage"
        verbose_name_plural = "Duckgres daily storage usage"
        constraints = [
            models.UniqueConstraint(fields=["date", "organization_id", "team_id"], name="duckgres_daily_storage_key"),
        ]


class DuckgresUsageCursor(UUIDModel):
    """Single-row record of the poller's progress against duckgres.

    Three watermarks, protecting three different things:

    - ``last_acked_watermark`` — the last watermark the poller acked. Load-bearing
      for custody: the poller cross-checks it against duckgres's own cursor
      (`watermark_low`) each pull and refuses to ack when duckgres is ahead of it
      (a possible hole in billable usage). Null until the first ack.
    - ``last_applied_watermark`` — the ``watermark_high`` of the last response whose
      rows were evaluated for promotion to the mirror. It keeps response processing
      monotone so a timed-out poll attempt cannot overwrite a newer snapshot.
    - ``last_complete_watermark`` — the newest response known to have no recoverable
      anomaly or regressed org. Complete usage reports require this watermark to
      cover their full UTC day before they publish.

    Written in the same transaction as the mirror rows, before the ack. One row per
    deployment — `singleton` is a unique constant so it's addressable without
    relying on a magic pk.
    """

    singleton = models.PositiveSmallIntegerField(default=1, unique=True)
    last_acked_watermark = models.DateTimeField(null=True, blank=True)
    last_applied_watermark = models.DateTimeField(null=True, blank=True)
    last_complete_watermark = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_duckgresusagecursor"
        verbose_name = "Duckgres usage cursor"
        verbose_name_plural = "Duckgres usage cursors"


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
