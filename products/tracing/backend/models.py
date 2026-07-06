"""Django models for tracing."""

import logging

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team.extensions import register_team_extension_signal
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel
from posthog.utils import generate_short_id

logger = logging.getLogger(__name__)

# Default span attribute key whose value matches a PostHog person's distinct_id. Same
# convention as logs (see DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY and
# https://posthog.com/docs/logs/link-session-replay): traces arrive via plain OTel, so
# instrumentation must attach the key itself — e.g. via baggage + a BaggageSpanProcessor.
# Customers whose pipeline uses a different key can override via the `tracing_config`
# endpoint.
DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEY = "posthogDistinctId"

# Define your models here
# Important:
# - Keep models thin, no business logic, use logic.py instead
# - Use types from facade/contracts.py or facade/enums.py where applicable
# - Do not use ForeignKeys to models outside this app unless allowed, as you will make implicit dependencies.
# - If you make a ForeignKey to a common model, disallow reverse relations with related_name='+'


class TracingView(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A saved set of tracing filters (date range, services, attribute filters, sort, view mode).

    Content-only storage — `filters` mirrors the frontend `TracingFilters` shape; restoring a view
    just replays those filters into `tracingFiltersLogic`.
    """

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating this
    # table takes no lock on those parents; the real constraints are added lock-free via
    # AddForeignKeyNotValid in the migration. created_by overrides CreatedMetaFields for the same reason.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    # Human-friendly id used in the API/URL instead of exposing the UUID primary key.
    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    name = models.CharField(max_length=400)
    filters = models.JSONField(default=dict)
    pinned = models.BooleanField(default=False)

    class Meta:
        db_table = "tracing_tracingview"
        unique_together = ("team", "short_id")
        indexes = [
            models.Index(fields=["team_id", "-created_at"], name="tracing_view_team_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} (Team: {self.team})"


class TeamTracingConfig(models.Model):
    # Plain `models.Model` (not `TeamScopedRootMixin`) — span ingestion and querying are
    # per-environment, and so is this config. Inheriting the root-mixin would rewrite
    # writes to the parent project on save, letting a member of one child environment
    # mutate config that affects sibling environments they may not have access to.
    # Mirrors the `TeamLogsConfig` precedent.
    # db_constraint=False keeps the CREATE TABLE lock-free on hot posthog_team; the real
    # constraint is added lock-free via AddForeignKeyNotValid in the migration.
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    # Span attribute key whose value matches a PostHog person's distinct_id. Used by the
    # person profile Traces tab to filter spans to a single user without needing per-team
    # prompt engineering.
    tracing_distinct_id_attribute_key = models.CharField(
        max_length=200,
        default=DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEY,
        db_default=DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEY,
    )


register_team_extension_signal(TeamTracingConfig, logger=logger)
