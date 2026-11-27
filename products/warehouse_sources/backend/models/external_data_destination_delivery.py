from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel, sane_repr


class ExternalDataDestinationDelivery(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """One batch of a sync run delivered to one external destination, with the egress it cost.

    Billing sums `bytes_exported` per team over the jobs that finished in a period. The unique
    constraint makes a retried or replayed batch insert nothing, so it is never counted twice.
    It includes `run_uuid` because every attempt of a job numbers its batches from zero again.
    The PostHog warehouse never gets a row.
    """

    # Overridden from CreatedMetaFields. The delivery path writes every row, so the column is
    # always NULL. No constraint or index, so a user delete neither checks nor scans this table.
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        db_index=False,
        db_constraint=False,
        related_name="+",
    )
    # `db_constraint=False`: a real FK constraint to the hot `posthog_team` table would take a
    # lock on it while being created. No index of its own because the (team, created_at) index
    # below leads with `team`.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    # No index of its own because the unique constraint below leads with `job`.
    job = models.ForeignKey(
        "warehouse_sources.ExternalDataJob", on_delete=models.CASCADE, db_index=False, related_name="+"
    )
    destination = models.ForeignKey(
        "warehouse_sources.ExternalDataDestination", on_delete=models.CASCADE, related_name="+"
    )
    run_uuid = models.CharField(max_length=200)
    batch_index = models.IntegerField()
    rows_written = models.BigIntegerField()
    bytes_exported = models.BigIntegerField()

    __repr__ = sane_repr("id", "job_id", "destination_id", "run_uuid", "batch_index", "bytes_exported")

    class Meta:
        db_table = "posthog_externaldatadestinationdelivery"
        constraints = [
            # The billing query finds the jobs that finished in a period and then reads their
            # rows here by `job`. Including `team` and `bytes_exported` lets that read be an
            # index-only scan.
            models.UniqueConstraint(
                fields=["job", "destination", "run_uuid", "batch_index"],
                include=["team", "bytes_exported"],
                name="wsd_delivery_job_dest_batch_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "created_at"], name="wsd_delivery_team_created_idx"),
        ]
