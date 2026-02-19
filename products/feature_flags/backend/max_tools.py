from textwrap import dedent
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field
from rest_framework.exceptions import ValidationError

from posthog.schema import FeatureFlagGroupType

from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.exceptions_capture import capture_exception
from posthog.models import FeatureFlag, GroupTypeMapping
from posthog.sync import database_sync_to_async

from ee.hogai.tool import MaxTool


class MultivariateVariant(BaseModel):
    """Schema for a multivariate flag variant."""

    key: str = Field(description="Variant key (e.g., 'control', 'test', 'variant_a')")
    name: str | None = Field(default=None, description="Optional human-readable variant name")
    rollout_percentage: int = Field(ge=0, le=100, description="Percentage of users assigned to this variant (0-100)")


class FeatureFlagCreationSchema(BaseModel):
    """Structured schema for AI-powered feature flag creation using PostHog's native types."""

    key: str = Field(
        description="Unique flag key in kebab-case (e.g., 'new-dashboard', 'dark-mode'). "
        "Must only contain letters, numbers, underscores, and hyphens. Pattern: ^[a-zA-Z0-9_-]+$"
    )
    name: str = Field(description="Human-readable flag name")
    description: str | None = Field(default=None, description="Optional description of what the flag controls")
    active: bool = Field(default=True, description="Whether the flag is active")
    group_type: str | None = Field(
        default=None, description="Group type name for group-based targeting (e.g., 'organization', 'company')"
    )
    groups: list[FeatureFlagGroupType] = Field(
        default_factory=list,
        description="Feature flag groups containing properties and rollout percentage. "
        "Uses PostHog's native FeatureFlagGroupType schema.",
    )
    tags: list[str] = Field(default_factory=list, description="Tags for organizing and categorizing the flag")
    variants: list[MultivariateVariant] | None = Field(
        default=None,
        description="Multivariate variants for A/B testing. If provided, creates a multivariate flag. "
        "Variant rollout percentages should sum to 100. "
        "Common example: [{'key': 'control', 'name': 'Control', 'rollout_percentage': 50}, "
        "{'key': 'test', 'name': 'Test', 'rollout_percentage': 50}]",
    )


FEATURE_FLAG_CREATION_TOOL_DESCRIPTION = dedent("""
    Use this tool to create feature flags with optional property-based targeting and multivariate variants.

    # When to use
    - The user wants to create a new feature flag
    - The user wants to roll out a feature to a percentage of users
    - The user wants to target specific users by properties (email, country, etc.)
    - The user wants to create an A/B test or experiment with multiple variants

    # Flag Types

    ## Simple Boolean Flags
    - Roll out to all users (100% rollout)
    - Roll out to a percentage of users (e.g., 10% rollout)

    ## Property-Based Targeting
    - Target users by person properties (email, country, etc.)
    - Target groups by group properties (plan, employee_count, etc.)
    - Combine property filters with rollout percentages

    ## Multivariate Flags (A/B Tests)
    - Create flags with multiple variants (control, test, etc.)
    - Specify rollout percentages for each variant (must sum to 100)
    - Can be combined with property targeting for segmented experiments
    """).strip()


class CreateFeatureFlagToolArgs(BaseModel):
    feature_flag: FeatureFlagCreationSchema = Field(
        description=dedent("""
        The complete feature flag configuration to create.

        # Required Fields
        - **key**: Unique flag key in kebab-case (e.g., 'new-dashboard', 'dark-mode')
          Must only contain letters, numbers, underscores, and hyphens
        - **name**: Human-readable flag name (e.g., 'New Dashboard Feature')

        # Optional Fields
        - **description**: Description of what the flag controls
        - **active**: Whether the flag is active (default: true)
        - **group_type**: Group type name for group-based targeting (e.g., 'organization')
        - **groups**: Array of targeting groups (see Groups Structure below)
        - **tags**: Array of tag strings for organizing flags
        - **variants**: Array of variants for A/B testing (see Variants Structure below)

        # Groups Structure
        Each group defines targeting criteria with AND logic within the group:
        - **properties**: Array of property filters (empty array [] for no property filtering)
        - **rollout_percentage**: Percentage of matching users to target (0-100, or null for 100%)

        Property filter structure:
        ```json
        {
            "key": "email",
            "value": "@company.com",
            "operator": "icontains",
            "type": "person"
        }
        ```

        Operators: "exact", "is_not", "icontains", "not_icontains", "gt", "lt", "gte", "lte", "is_set", "is_not_set"
        Types: "person" for user properties, "group" for group properties (requires group_type_index)

        # Variants Structure (for A/B tests)
        - **key**: Variant identifier (e.g., 'control', 'test')
        - **name**: Human-readable variant name (optional)
        - **rollout_percentage**: Percentage for this variant (all variants must sum to 100)

        # Examples

        ## Simple 50% Rollout
        ```json
        {
            "key": "new-feature",
            "name": "New Feature",
            "groups": [{"properties": [], "rollout_percentage": 50}]
        }
        ```

        ## Property-Based Targeting
        ```json
        {
            "key": "beta-feature",
            "name": "Beta Feature",
            "groups": [{
                "properties": [{
                    "key": "email",
                    "value": "@company.com",
                    "operator": "icontains",
                    "type": "person"
                }],
                "rollout_percentage": null
            }]
        }
        ```

        ## A/B Test with 2 Variants
        ```json
        {
            "key": "checkout-test",
            "name": "Checkout Flow A/B Test",
            "variants": [
                {"key": "control", "name": "Current Flow", "rollout_percentage": 50},
                {"key": "test", "name": "New Flow", "rollout_percentage": 50}
            ],
            "groups": [{"properties": [], "rollout_percentage": null}]
        }
        ```

        ## Group-Based Flag (Organizations)
        ```json
        {
            "key": "enterprise-feature",
            "name": "Enterprise Feature",
            "group_type": "organization",
            "groups": [{
                "properties": [{
                    "key": "plan",
                    "value": "enterprise",
                    "operator": "exact",
                    "type": "group",
                    "group_type_index": 0
                }],
                "rollout_percentage": null
            }]
        }
        ```

        # Critical Rules
        - Keys must match pattern ^[a-zA-Z0-9_-]+$ (no spaces or special characters)
        - For A/B tests, variant rollout_percentages MUST sum to 100
        - Always include at least one group (even if properties is empty)
        - For group-based flags, set group_type and include group_type_index in property filters
        """).strip()
    )


class CreateFeatureFlagTool(MaxTool):
    name: str = "create_feature_flag"
    description: str = FEATURE_FLAG_CREATION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateFeatureFlagToolArgs

    def get_required_resource_access(self):
        """
        Creating a feature flag requires editor-level access to feature flags.
        This check runs before the tool executes.
        """

        return [("feature_flag", "editor")]

    async def _arun_impl(self, feature_flag: FeatureFlagCreationSchema) -> tuple[str, dict[str, Any]]:
        """Create feature flag"""
        try:
            flag_schema = feature_flag

            aggregation_group_type_index = None
            group_type_display_name = None
            if flag_schema.group_type:

                @database_sync_to_async
                def get_group_mapping():
                    return GroupTypeMapping.objects.filter(
                        team=self._team, group_type=flag_schema.group_type.lower() if flag_schema.group_type else None
                    ).first()

                group_mapping = await get_group_mapping()
                if not group_mapping:
                    return (
                        f"Group type '{flag_schema.group_type}' does not exist for this project",
                        {"error": "group_type_not_found"},
                    )

                aggregation_group_type_index = group_mapping.group_type_index
                group_type_display_name = group_mapping.name_plural or flag_schema.group_type

            filters: dict[str, Any] = {}
            if aggregation_group_type_index is not None:
                filters["aggregation_group_type_index"] = aggregation_group_type_index
            filters["groups"] = [group.model_dump(exclude_none=True) for group in flag_schema.groups]
            if flag_schema.variants:
                filters["multivariate"] = {
                    "variants": [variant.model_dump(exclude_none=True) for variant in flag_schema.variants]
                }

            serializer_data: dict[str, Any] = {
                "key": flag_schema.key,
                "name": flag_schema.name,
                "active": flag_schema.active,
                "filters": filters,
                "tags": flag_schema.tags,
                "_should_create_usage_dashboard": False,
            }

            # Mock request following established patterns
            mock_request = SimpleNamespace(
                user=self._user,
                method="POST",
                successful_authenticator=None,
                session={},
                data=serializer_data,
            )
            team = self._team
            context = {
                "request": mock_request,
                "team_id": team.id,
                "project_id": team.project_id,
                "get_team": lambda: team,
            }

            @database_sync_to_async
            def create_flag_via_serializer():
                serializer = FeatureFlagSerializer(data=serializer_data, context=context)
                serializer.is_valid(raise_exception=True)
                return serializer.save()

            flag = await create_flag_via_serializer()

            flag_url = f"/project/{self._team.project_id}/feature_flags/{flag.id}"
            targeting_info = self._format_targeting_info(flag_schema, group_type_display_name)

            return (
                f"Successfully created feature flag '{flag_schema.name}' (key: {flag_schema.key}){targeting_info}. View at {flag_url}",
                {
                    "flag_id": flag.id,
                    "flag_key": flag_schema.key,
                    "flag_name": flag_schema.name,
                    "url": flag_url,
                },
            )

        except ValidationError as e:
            errors = e.detail if hasattr(e, "detail") else str(e)

            if isinstance(errors, dict) and "key" in errors:
                key_errors = errors["key"]
                if any("already" in str(err).lower() for err in key_errors):

                    @database_sync_to_async
                    def get_existing_flag():
                        return FeatureFlag.objects.filter(team=self._team, key=flag_schema.key, deleted=False).first()

                    existing = await get_existing_flag()
                    if existing:
                        flag_url = f"/project/{self._team.project_id}/feature_flags/{existing.id}"
                        return (
                            f"A feature flag with key '{flag_schema.key}' already exists. You can view it at {flag_url}",
                            {"flag_id": existing.id},
                        )

            if isinstance(errors, dict):
                error_messages = []
                for field, field_errors in errors.items():
                    for error in field_errors if isinstance(field_errors, list) else [field_errors]:
                        error_messages.append(f"{field}: {error}")
                return (
                    f"Failed to create feature flag: {'; '.join(error_messages)}",
                    {"error": "validation_error", "details": errors},
                )

            return f"Failed to create feature flag: {errors}", {"error": "validation_error"}
        except ValueError as e:
            return f"Failed to create feature flag: {str(e)}", {"error": str(e)}
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create feature flag: {str(e)}", {"error": str(e)}

    def _format_targeting_info(self, schema: FeatureFlagCreationSchema, group_display_name: str | None) -> str:
        """Format targeting information for success message."""
        parts = []

        # Add multivariate info first if present
        if schema.variants:
            variant_count = len(schema.variants)
            if variant_count == 2:
                parts.append("A/B test with 2 variants")
            else:
                parts.append(f"multivariate with {variant_count} variants")

        # Count total property filters across all groups
        total_properties = sum(len(group.properties or []) for group in schema.groups)
        if total_properties > 0:
            parts.append(f"{total_properties} property filter(s)")

        if group_display_name:
            parts.append(f"targeting {group_display_name}")

        # Check if any group has a rollout percentage
        rollout_percentages = [
            group.rollout_percentage for group in schema.groups if group.rollout_percentage is not None
        ]
        if rollout_percentages:
            # If there's just one group with a percentage, show it
            if len(rollout_percentages) == 1:
                pct = rollout_percentages[0]
                # Format as int if it's a whole number, otherwise as float
                pct_str = f"{int(pct)}" if pct == int(pct) else f"{pct}"
                parts.append(f"{pct_str}% rollout")
            else:
                parts.append("multiple rollout rules")

        if parts:
            return " with " + ", ".join(parts)
        return ""
