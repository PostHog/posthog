from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import DeletedMetaFields, UpdatedMetaFields, UUIDTModel, sane_repr


class ExternalDataDestination(TeamScopedRootMixin, UpdatedMetaFields, DeletedMetaFields, UUIDTModel):
    """Somewhere a warehouse source writes its synced rows.

    The PostHog warehouse is one of these, not a special case: a schema's destination set
    decides where its rows land, and an empty set resolves to the team's warehouse row so
    sources configured before this feature keep their existing behavior.

    Credentials live on the linked `Integration`, never in `config` — the same split batch
    exports use, so both products share the integration setup UI and connection tests.
    """

    class Type(models.TextChoices):
        POSTHOG_WAREHOUSE = "PostHogWarehouse", "PostHog warehouse"
        # Values match `BatchExportDestination.Destination` so a destination type resolves to
        # the same writer vocabulary in both products. Spelled out rather than imported to
        # keep a model migration from depending on another product's enum.
        REDSHIFT = "Redshift", "Redshift"
        SNOWFLAKE = "Snowflake", "Snowflake"
        BIGQUERY = "BigQuery", "BigQuery"
        POSTGRES = "Postgres", "Postgres"
        DATABRICKS = "Databricks", "Databricks"
        AZURE_BLOB = "AzureBlob", "Azure Blob"
        S3 = "S3", "S3"

    # `db_constraint=False`: a real FK constraint to the hot `posthog_team` table would
    # take a lock on it while being created. Team scoping is enforced at the app level
    # via `TeamScopedRootMixin`. See products/README.md "Adding or moving backend models
    # and migrations".
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    type = models.CharField(max_length=64, choices=Type)
    name = models.CharField(max_length=400)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Non-secret shape config: target database/schema/dataset, bucket and prefix, file format.",
    )
    integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Credentials for this destination. Null for the PostHog warehouse.",
    )
    # `db_constraint=False`: `posthog_user` is a hot table, same reasoning as `team`.
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("id", "team_id", "type", "name")

    class Meta:
        db_table = "posthog_externaldatadestination"
        constraints = [
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(type="PostHogWarehouse", deleted=False),
                name="wsd_one_warehouse_dest_per_team",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "type"], name="wsd_team_type_idx"),
            models.Index(fields=["updated_at"], name="wsd_dest_updated_idx"),
        ]

    @property
    def is_posthog_warehouse(self) -> bool:
        return self.type == self.Type.POSTHOG_WAREHOUSE


class ExternalDataSourceDestination(TeamScopedRootMixin, UpdatedMetaFields, UUIDTModel):
    """Source-level default destination set, inherited by every schema that does not override it."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    source = models.ForeignKey(
        "warehouse_sources.ExternalDataSource", on_delete=models.CASCADE, related_name="destination_links"
    )
    destination = models.ForeignKey(ExternalDataDestination, on_delete=models.CASCADE, related_name="source_links")
    enabled = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("id", "source_id", "destination_id", "enabled")

    class Meta:
        db_table = "posthog_externaldatasourcedestination"
        constraints = [
            models.UniqueConstraint(fields=["source", "destination"], name="wsd_source_dest_uniq"),
        ]
        indexes = [
            models.Index(fields=["updated_at"], name="wsd_src_link_updated_idx"),
        ]


class ExternalDataSchemaDestination(TeamScopedRootMixin, UpdatedMetaFields, UUIDTModel):
    """Schema-level destination override.

    Any row here — even a fully disabled set — replaces the source-level set for that schema,
    mirroring how `ExternalDataSchema.api_version` overrides the source pin.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    schema = models.ForeignKey(
        "warehouse_sources.ExternalDataSchema", on_delete=models.CASCADE, related_name="destination_links"
    )
    destination = models.ForeignKey(ExternalDataDestination, on_delete=models.CASCADE, related_name="schema_links")
    enabled = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("id", "schema_id", "destination_id", "enabled")

    class Meta:
        db_table = "posthog_externaldataschemadestination"
        constraints = [
            models.UniqueConstraint(fields=["schema", "destination"], name="wsd_schema_dest_uniq"),
        ]
        indexes = [
            models.Index(fields=["updated_at"], name="wsd_schema_link_upd_idx"),
        ]


DEFAULT_WAREHOUSE_DESTINATION_NAME = "PostHog warehouse"


def get_or_create_warehouse_destination(team_id: int) -> ExternalDataDestination:
    """Return the team's PostHog warehouse destination, creating it on first use.

    Rows are created lazily rather than backfilled: a team that never opts into extra
    destinations never needs one, and `resolve_destinations` only reaches here when a
    schema has no destination configured at all.
    """
    destination, _ = ExternalDataDestination.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        type=ExternalDataDestination.Type.POSTHOG_WAREHOUSE,
        deleted=False,
        defaults={"name": DEFAULT_WAREHOUSE_DESTINATION_NAME, "config": {}},
    )
    return destination


def resolve_destinations(schema: "ExternalDataSchema") -> list[ExternalDataDestination]:  # type: ignore[name-defined] # noqa: F821
    """Resolve where one schema's rows should be written.

    Schema-level links win over source-level links whenever any exist, so clearing a
    schema's override is what restores inheritance — the same precedence
    `ExternalDataSchema.api_version` uses against the source pin.

    No links at either level means the source predates destinations, which must keep
    syncing to the PostHog warehouse exactly as it did before.

    Queried through `for_team` rather than `schema.destination_links`: the related manager
    is the fail-closed one, so traversing it raises `TeamScopeError` in the Temporal
    activities and management commands that resolve destinations outside a request.
    """
    team_id = schema.team_id
    links: list = list(
        ExternalDataSchemaDestination.objects.for_team(team_id)
        .filter(schema_id=schema.id)
        .select_related("destination")
    ) or list(
        ExternalDataSourceDestination.objects.for_team(team_id)
        .filter(source_id=schema.source_id)
        .select_related("destination")
    )
    if links:
        return [link.destination for link in links if link.enabled and not link.destination.deleted]
    return [get_or_create_warehouse_destination(team_id)]
