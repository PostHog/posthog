import re
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


class Endpoint(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """Model for storing endpoints that can be accessed via API endpoints.

    Endpoints allow creating reusable query endpoints like:
    /api/environments/{team_id}/endpoints/{endpoint_name}/run

    The query field follows the same structure as QueryRequest.query, supporting
    any query type accepted by the /query endpoint (HogQLQuery, TrendsQuery, etc.).
    """

    name = models.CharField(
        max_length=128, validators=[validate_endpoint_name], help_text="URL-safe name for the endpoint"
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    # Use JSONField to store the query, following the same pattern as QueryRequest.query
    # This can store any of the query types: HogQLQuery, TrendsQuery, FunnelsQuery, etc.
    query = models.JSONField(help_text="Query definition following QueryRequest.query schema")

    description = models.TextField(blank=True, help_text="Human-readable description of what this query does")

    # Parameter schema for query customization
    parameters = models.JSONField(
        default=dict, blank=True, help_text="JSON schema defining expected parameters for query customization"
    )

    is_active = models.BooleanField(default=True, help_text="Whether this endpoint is available via the API")

    cache_age_seconds = models.IntegerField(
        null=True,
        blank=True,
        help_text="Custom cache age in seconds. If not set, uses default caching. Must be between 300 and 86400 seconds.",
    )

    saved_query = models.ForeignKey(
        "data_warehouse.DataWarehouseSavedQuery",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="endpoints",
        help_text="The underlying materialized view that backs this endpoint",
    )

    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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

    def get_query_with_parameters(self, request_params: dict[str, Any]) -> dict[str, Any]:
        """Apply request parameters to the stored query.

        This method handles parameter injection for query customization.
        For now, it returns the query as-is, but can be extended to support
        parameter substitution in the future.
        """
        # TODO: Implement parameter substitution logic
        # For example, replacing {parameter_name} placeholders in HogQL queries
        return self.query

    def validate_parameters(self, request_params: dict[str, Any]) -> None:
        """Validate request parameters against the parameter schema.

        This method can be extended to implement JSON schema validation
        of incoming parameters.
        """
        # TODO: Implement parameter validation logic
        pass

    @property
    def is_materialized(self) -> bool:
        """Whether this endpoint's query results are materialized to S3."""
        if self.saved_query is None:
            return False
        return bool(self.saved_query.is_materialized)

    @property
    def materialization_status(self) -> str:
        """Get status from saved_query."""
        if not self.saved_query:
            return "not_materialized"
        return self.saved_query.status or "Unknown"

    @property
    def last_materialized_at(self):
        """Get last run time from saved_query."""
        if not self.saved_query:
            return None
        return self.saved_query.last_run_at

    @property
    def materialization_error(self) -> str:
        """Get error from saved_query."""
        if not self.saved_query:
            return ""
        return self.saved_query.latest_error or ""

    def can_materialize(self) -> tuple[bool, str]:
        """Check if endpoint can be materialized.

        Returns: (can_materialize: bool, reason: str)
        """
        if self.query.get("kind") != "HogQLQuery":
            return False, "Only HogQL queries can be materialized."

        if self.query.get("variables"):
            return False, "Queries with variables cannot be materialized."

        hogql_query = self.query.get("query")
        if not hogql_query or not isinstance(hogql_query, str):
            return False, "Query is empty or invalid."

        return True, ""
