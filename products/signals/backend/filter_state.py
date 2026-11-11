from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class SignalSourceFilterState(TeamScopedRootMixin, UUIDModel):
    """Fetch state of a filtered warehouse source, so a window that failed to fetch is read again.

    The fetch window starts at the import's `last_synced_at`, which the next sync advances whether or not
    emission succeeded. A failed fetch emitted nothing, so the next fetch reads from `pending_window_start`
    instead, and a successful fetch clears it.
    """

    # See `SignalScoutConfig.all_teams` for the rationale on the unscoped sibling manager.
    all_teams = models.Manager()  # noqa: DJ012

    # No single-column index: the unique constraint below leads with team_id.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    source_product = models.CharField(max_length=100)
    source_type = models.CharField(max_length=100)
    # Each warehouse schema has its own sync cursor, so two connections of one source keep separate windows.
    # Not a foreign key: schemas belong to another product.
    schema_id = models.UUIDField()
    pending_window_start = models.DateTimeField(null=True, blank=True)
    # Set when a capped batch stopped partway through `pending_window_start`: the cursor id of its last row.
    pending_window_id = models.CharField(max_length=200, blank=True, default="")
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    # Only messages the filter code wrote. A query error stores its type, because its text can carry row values.
    last_error_message = models.CharField(max_length=500, blank=True, default="")
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_malformed_count = models.PositiveIntegerField(default=0)
    last_success_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "signals"
        verbose_name = "Signal source filter state"
        verbose_name_plural = "Signal source filter states"
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_product", "source_type", "schema_id"], name="signals_source_filter_state_unique"
            ),
        ]
