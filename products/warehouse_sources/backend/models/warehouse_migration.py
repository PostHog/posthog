from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel, sane_repr


class WarehouseMigration(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """One import of a team's Fivetran account setup into PostHog sources.

    `credentials` holds the customer's read-only vendor API key, encrypted, and is never returned by the
    API. `snapshot` is what we read from the vendor, with every secret already removed.
    """

    class Provider(models.TextChoices):
        FIVETRAN = "fivetran", "Fivetran"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CRAWLING = "crawling", "Crawling"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    # db_constraint=False on FKs to hot tables: see WarehouseColumnStatistics.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    provider = models.CharField(max_length=32, choices=Provider.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    credentials = EncryptedJSONField(default=dict)
    account_name = models.CharField(max_length=400, blank=True, default="")
    snapshot = models.JSONField(null=True, blank=True)
    crawled_at = models.DateTimeField(null=True, blank=True)
    workflow_id = models.CharField(max_length=400, blank=True, default="")
    latest_error = models.TextField(blank=True, default="")

    __repr__ = sane_repr("id", "team_id", "provider", "status")


class WarehouseMigrationItem(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """One vendor connection inside a `WarehouseMigration`, with what PostHog plans to create for it."""

    class Verdict(models.TextChoices):
        AS_IS = "as_is", "Moves as is"
        CAVEATS = "caveats", "Moves with caveats"
        UNSUPPORTED = "unsupported", "Not supported"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        # Claimed by one apply request, so a second request cannot create the source twice.
        APPLYING = "applying", "Applying"
        APPLIED = "applied", "Applied"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    migration = models.ForeignKey(WarehouseMigration, on_delete=models.CASCADE, related_name="items")
    vendor_connection_id = models.CharField(max_length=400)
    vendor_service = models.CharField(max_length=400)
    name = models.CharField(max_length=400)
    verdict = models.CharField(max_length=32, choices=Verdict.choices)
    caveats = models.JSONField(default=list)
    # An `ItemProposal` as JSON. Null when the connection cannot move to PostHog.
    proposal = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    external_data_source_id = models.UUIDField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    # When the latest apply claimed the item, and the prefix it created the source with. A failed or
    # dead apply can leave a source behind, and these let the next attempt find it instead of a second one.
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_prefix = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["migration", "vendor_connection_id"], name="unique_warehouse_migration_item_connection"
            )
        ]

    __repr__ = sane_repr("id", "team_id", "vendor_service", "verdict", "status")
