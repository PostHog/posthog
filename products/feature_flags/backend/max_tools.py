import re
from textwrap import dedent
from typing import Any

from pydantic import BaseModel, Field

from posthog.schema import FeatureFlagGroupType

from posthog.exceptions_capture import capture_exception
from posthog.models import FeatureFlag, GroupTypeMapping, Tag, TaggedItem
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
        """Create feature flag from the structured configuration."""
        try:
            flag_schema = feature_flag

            # Validate feature flag key format
            if not re.match(r"^[a-zA-Z0-9_-]+$", flag_schema.key):
                return (
                    f"Invalid feature flag key '{flag_schema.key}'. Keys must contain only letters, numbers, underscores, and hyphens (matching pattern: ^[a-zA-Z0-9_-]+$)",
                    {"error": "invalid_key", "key": flag_schema.key},
                )

            # Validate and enrich group type if specified
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

            # Build filters dict using native PostHog schema
            filters: dict[str, Any] = {}
            if aggregation_group_type_index is not None:
                filters["aggregation_group_type_index"] = aggregation_group_type_index

            # Convert Pydantic models to dicts for JSON storage
            filters["groups"] = [group.model_dump(exclude_none=True) for group in flag_schema.groups]

            # Add multivariate configuration if variants are specified
            if flag_schema.variants:
                # Validate that variant percentages sum to 100
                total_percentage = sum(v.rollout_percentage for v in flag_schema.variants)
                if total_percentage != 100:
                    return (
                        f"Variant rollout percentages must sum to 100, but got {total_percentage}. "
                        f"Please adjust the percentages.",
                        {"error": "invalid_variant_percentages"},
                    )

                filters["multivariate"] = {
                    "variants": [variant.model_dump(exclude_none=True) for variant in flag_schema.variants]
                }

            # Create the flag
            @database_sync_to_async
            def create_flag():
                # Check if flag already exists
                existing = FeatureFlag.objects.filter(team=self._team, key=flag_schema.key, deleted=False).first()
                if existing:
                    return None, existing  # Return None to indicate flag exists

                flag = FeatureFlag.objects.create(
                    team=self._team,
                    created_by=self._user,
                    key=flag_schema.key,
                    name=flag_schema.name,  # name field stores the description/display name
                    active=flag_schema.active,
                    filters=filters,
                )

                # Add tags
                if flag_schema.tags:
                    for tag_name in flag_schema.tags:
                        tag, _ = Tag.objects.get_or_create(name=tag_name.strip(), team_id=self._team.id)
                        TaggedItem.objects.create(tag=tag, feature_flag=flag)

                return flag, None

            flag, existing_flag = await create_flag()

            # Handle case where flag already exists
            if existing_flag:
                flag_url = f"/project/{self._team.project_id}/feature_flags/{existing_flag.id}"
                return (
                    f"A feature flag with key '{flag_schema.key}' already exists. You can view it at {flag_url}",
                    {
                        "flag_id": existing_flag.id,
                    },
                )

            flag_url = f"/project/{self._team.project_id}/feature_flags/{flag.id}"

            # Build success message
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
