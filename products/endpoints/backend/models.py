import re
import json
import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel


def validate_endpoint_name(value: str) -> None:
    """Validate that the endpoint name is URL-safe and follows naming conventions."""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", value):
        raise ValidationError(
            f"{value} is not a valid endpoint name. Endpoint names must start with a letter and contain only letters, numbers, hyphens, and underscores.",
            params={"value": value},
        )

    if len(value) > 128:
        raise ValidationError(
            f"Endpoint name '{value}' is too long. Maximum length is 128 characters.",
            params={"value": value},
        )


class EndpointVersion(models.Model):
    """Immutable snapshot of an endpoint's query at a specific version.

    Each time an endpoint's query is modified, a new version is created.
    This allows users to execute specific versions or track query evolution over time.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.ForeignKey("Endpoint", on_delete=models.CASCADE, related_name="versions")
    version = models.IntegerField()
    query = models.JSONField(help_text="Immutable query snapshot")
    description = models.TextField(blank=True, default="", help_text="Optional description for this endpoint version")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="endpoint_versions_created")

    cache_age_seconds = models.IntegerField(
        null=True,
        blank=True,
        help_text="Cache age in seconds. If null, uses default interval-based caching.",
    )
    is_materialized = models.BooleanField(
        default=False,
        help_text="Whether this version's query results are materialized",
    )
    saved_query = models.ForeignKey(
        "data_warehouse.DataWarehouseSavedQuery",
        null=True,
        blank=True,
        db_index=False,
        on_delete=models.SET_NULL,
        related_name="endpoint_versions",
        help_text="The underlying materialized view for this version",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this version is available for execution. Inactive versions cannot be run.",
    )

    class Meta:
        db_table = "endpoints_endpointversion"
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "version"],
                name="unique_endpoint_version",
            )
        ]
        indexes = [
            models.Index(fields=["endpoint", "version"], name="endpoint_version_idx"),
            models.Index(fields=["endpoint", "-version"], name="endpoint_version_desc_idx"),
            models.Index(fields=["created_at"], name="endpoint_version_created_idx"),
            models.Index(fields=["saved_query"], name="endpointvers_saved_q_0dc3_idx"),
        ]
        ordering = ["-version"]

    def __str__(self) -> str:
        return f"{self.endpoint.name} v{self.version}"

    def can_materialize(self) -> tuple[bool, str]:
        """Check if this version can be materialized.

        Returns: (can_materialize: bool, reason: str)
        """
        query_kind = self.query.get("kind") if self.query else None

        MATERIALIZABLE_QUERY_TYPES = {
            "HogQLQuery",
            "TrendsQuery",
            "FunnelsQuery",
            "LifecycleQuery",
            "RetentionQuery",
            "PathsQuery",
            "StickinessQuery",
        }

        if query_kind not in MATERIALIZABLE_QUERY_TYPES:
            supported = ", ".join(sorted(MATERIALIZABLE_QUERY_TYPES))
            return (
                False,
                f"Query type '{query_kind}' cannot be materialized. Supported types: {supported}",
            )

        if self.query.get("variables"):
            return False, "Queries with variables cannot be materialized."

        if query_kind == "HogQLQuery":
            hogql_query = self.query.get("query")
            if not hogql_query or not isinstance(hogql_query, str):
                return False, "Query is empty or invalid."

        return True, ""


class Endpoint(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """Model for storing endpoints that can be accessed via API endpoints.

    Endpoints allow creating reusable query endpoints like:
    /api/environments/{team_id}/endpoints/{endpoint_name}/run

    Query, description, cache_age_seconds, and materialization settings are stored
    in EndpointVersion, allowing per-version configuration.
    """

    name = models.CharField(
        max_length=128, validators=[validate_endpoint_name], help_text="URL-safe name for the endpoint"
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    derived_from_insight = models.CharField(
        max_length=12,
        null=True,
        blank=True,
        help_text="Short ID of the insight this endpoint was created from",
    )

    is_active = models.BooleanField(default=True, help_text="Whether this endpoint is available via the API")

    current_version = models.IntegerField(default=1, help_text="Current version number of the endpoint query")

    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this endpoint was last executed via the run API. Updated with hour granularity.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_team_endpoint_name",
            )
        ]
        indexes = [
            models.Index(fields=["team", "is_active"]),
            models.Index(fields=["team", "name"]),
        ]

    def __str__(self) -> str:
        return f"{self.team.name}: {self.name}"

    @property
    def endpoint_path(self) -> str:
        """Return the API endpoint path for this endpoint."""
        return f"/api/environments/{self.team.id}/endpoints/{self.name}/run"

    def has_query_changed(self, new_query: dict[str, Any]) -> bool:
        """Deep comparison to check if query has actually changed.

        We normalize JSON before comparison to handle key ordering differences.
        Compares against the current version's query.
        """
        current_version = self.get_version()
        current_query = current_version.query
        current_normalized = json.loads(json.dumps(current_query, sort_keys=True))
        new_normalized = json.loads(json.dumps(new_query, sort_keys=True))
        return current_normalized != new_normalized

    def create_new_version(self, query: dict[str, Any], user: User) -> "EndpointVersion":
        """Create a new version with the given query.

        This increments current_version and creates an EndpointVersion record.
        Should be called when the query changes during an update.
        Snapshots current configuration values from previous version.
        """
        # Get previous version's settings before incrementing
        previous_version = self.get_version()
        previous_cache_age = previous_version.cache_age_seconds if previous_version else None
        previous_description = previous_version.description if previous_version else ""

        self.current_version += 1
        self.save(update_fields=["current_version", "updated_at"])

        # Create new version, inheriting settings from previous version
        version = EndpointVersion.objects.create(
            endpoint=self,
            version=self.current_version,
            query=query,
            created_by=user,
            cache_age_seconds=previous_cache_age,
            description=previous_description,
            is_materialized=False,
        )

        return version

    def get_version(self, version: int | None = None) -> EndpointVersion:
        """Get a specific version, or the latest (highest version number) if version is None.

        Raises EndpointVersion.DoesNotExist if the requested version doesn't exist.
        """
        if version is not None:
            return self.versions.get(version=version)

        latest = self.versions.first()  # Model ordering is -version
        if latest is None:
            raise EndpointVersion.DoesNotExist("Endpoint has no versions")
        return latest
