from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import FeatureFlagGroupType

from posthog.exceptions_capture import capture_exception
from posthog.models import FeatureFlag, GroupTypeMapping, Tag, TaggedItem, Team, User
from posthog.models.property_definition import PropertyDefinition
from posthog.sync import database_sync_to_async

from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.tools import TaxonomyTool, ask_user_for_help, base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.tool import MaxTool


class FeatureFlagCreationSchema(BaseModel):
    """Structured schema for AI-powered feature flag creation using PostHog's native types."""

    key: str = Field(description="Unique flag key in kebab-case (e.g., 'new-dashboard', 'dark-mode')")
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


FEATURE_FLAG_CREATION_SYSTEM_PROMPT = """
You are an expert at creating PostHog feature flags with precise targeting using property filters.

# Your Task
Generate a structured feature flag configuration from the user's natural language instructions.

# Available Group Types
{{{available_group_types}}}

**IMPORTANT**: When the user mentions a group (like "organization", "company", "account"), you MUST:
1. Use `retrieve_entity_properties` for EACH available group type above
2. Check which group has properties that match what the user wants
3. Use the EXACT group type name from the list above (e.g., if the list shows "account", use "account" not "organization")

# Process

1. **Understand the request:**
   - What is the flag for? (extract key and name)
   - Who should see it? (targeting criteria)
   - What percentage? (rollout percentage if specified)

2. **Discover properties** (if targeting by properties):
   - Use `retrieve_entity_properties` to see available properties
   - For user-based targeting: entity="person"
   - For group-based targeting: entity=[EXACT group type name from the available types list above]
   - Review the properties to find ones that match the user's intent
   - If unsure which group type to use, check properties for ALL group types to find the right one

3. **Get property values** (optional, for validation):
   - Use `retrieve_entity_property_values` to see example values
   - Helps ensure you're using the right property and format

4. **Validate property filters:**
   - Use `validate_property_filter` to check EACH filter before including it
   - Fix any validation errors by adjusting the operator or finding the correct property
   - NEVER skip validation - it prevents errors

5. **Generate structured output:**
   - Use `final_answer` with complete FeatureFlagCreationSchema
   - Create a `groups` array with at least one group containing:
     - `properties`: array of validated property filters (empty array [] if no property-based filtering)
     - `rollout_percentage`: percentage number (0-100) for partial rollout, or null/100 for full rollout to all users
     - NOTE: ALWAYS include at least one group in the groups array, never an empty array

# Property Filter Guidelines

**Operators:**
- `exact`: Exact match (case-sensitive)
- `is_not`: Not equal to
- `icontains`: Contains substring (case-insensitive) - use for email domains, partial text
- `not_icontains`: Does not contain substring
- `gt`, `lt`, `gte`, `lte`: Numeric comparisons (greater than, less than, etc.)
- `is_set`: Property exists
- `is_not_set`: Property does not exist

**Property Types:**
- `person`: For user properties (email, name, country, etc.)
- `group`: For group properties (plan, size, industry, etc.) - must include group_type_index
- `cohort`: For cohort membership (advanced use case)

**Examples:**

User-based filter (email contains domain):
```json
{
  "key": "email",
  "value": "@company.com",
  "operator": "icontains",
  "type": "person"
}
```

User-based filter (country is US):
```json
{
  "key": "country",
  "value": "US",
  "operator": "exact",
  "type": "person"
}
```

Group-based filter (plan is enterprise):
```json
{
  "key": "plan",
  "value": "enterprise",
  "operator": "exact",
  "type": "group",
  "group_type_index": 0
}
```

Multiple filters (AND logic - all must match):
```json
[
  {
    "key": "country",
    "value": "US",
    "operator": "exact",
    "type": "person"
  },
  {
    "key": "age",
    "value": 25,
    "operator": "gte",
    "type": "person"
  }
]
```

# Important Rules

- **ALWAYS** use `retrieve_entity_properties` BEFORE creating property filters
- **ALWAYS** validate filters with `validate_property_filter` BEFORE using final_answer
- Use exact property names from taxonomy (case-sensitive)
- For group-based flags:
  - Set `group_type` field to the group type name
  - Include `group_type_index` in each group property filter
  - Use group properties, not person properties
- Rollout percentage in each group applies AFTER property filtering in that group (e.g., "10% of users where email contains X")
- Always create a `groups` array with at least one group (even if properties is empty)
- Use `ask_user_for_help` if requirements are unclear or ambiguous
- Generate keys in kebab-case (e.g., "new-dashboard" not "new_dashboard" or "NewDashboard")

# Common Patterns

**Pattern 1: Percentage rollout (no property filters)**
Input: "Create a flag for dark mode at 50%"
- Targets ALL users, but only 50% will see the flag
- Create one group with `properties: []` (empty) and `rollout_percentage: 50`

**Pattern 2: Full rollout (no property filters, 100%)**
Input: "Create a flag for dark mode" or "Create a flag with 100% rollout"
- Targets ALL users, 100% will see the flag
- Create one group with `properties: []` (empty) and `rollout_percentage: 100`
- NOTE: Use explicit 100 rather than null for clarity

**Pattern 3: Property-based filtering (100% of matching users)**
Input: "Create a flag for users with @company.com email"
- Targets only users whose email contains @company.com
- Discover "email" property
- Validate filter with operator "icontains"
- Create one group with the property filter and `rollout_percentage: null` or `100` (meaning 100% of users who match the filter)

**Pattern 4: Property filtering + percentage rollout**
Input: "Create a flag for 25% of enterprise organizations"
- Targets only 25% of organizations where plan=enterprise
- Set group_type to "organization"
- Discover group properties
- Find "plan" property
- Validate filter
- Create one group with the property filter and `rollout_percentage: 25` (25% of orgs that match the filter)

**Pattern 5: Multiple property conditions (AND logic)**
Input: "Create a flag for US users over 25 years old"
- Targets only users where country=US AND age>=25
- Discover "country" and "age" properties
- Validate both filters
- Create one group with both property filters in the properties array (AND logic within a group)
- Use `rollout_percentage: null` or `100` to target 100% of matching users

# Output Format

Always use `final_answer` tool with complete FeatureFlagCreationSchema.

The schema uses PostHog's native `FeatureFlagGroupType` format with a `groups` array.
Each group contains `properties` (optional) and `rollout_percentage` (optional).

**Simple rollout (no property filtering):**
```json
{
  "key": "kebab-case-key",
  "name": "Human Readable Name",
  "description": "What this flag controls (optional but recommended)",
  "active": true,
  "group_type": null,
  "groups": [
    {
      "properties": [],
      "rollout_percentage": 50
    }
  ],
  "tags": ["experiment", "frontend"]
}
```

**Property-based targeting (100% of matching):**
```json
{
  "key": "kebab-case-key",
  "name": "Human Readable Name",
  "active": true,
  "group_type": null,
  "groups": [
    {
      "properties": [
        {
          "key": "email",
          "value": "@company.com",
          "operator": "icontains",
          "type": "person"
        }
      ],
      "rollout_percentage": null
    }
  ],
  "tags": []
}
```

**Combined (property filtering + percentage):**
```json
{
  "key": "kebab-case-key",
  "name": "Human Readable Name",
  "active": true,
  "group_type": "organization",
  "groups": [
    {
      "properties": [
        {
          "key": "plan",
          "value": "enterprise",
          "operator": "exact",
          "type": "group",
          "group_type_index": 0
        }
      ],
      "rollout_percentage": 25
    }
  ],
  "tags": []
}
```

**Multiple conditions (OR logic):**
If you need OR logic between different property sets, create multiple groups.
Each group is evaluated independently (OR logic between groups, AND logic within a group's properties).

**IMPORTANT**:
- ALWAYS include at least ONE group in the `groups` array
- NEVER use an empty groups array `[]`
- The `properties` array can be empty `[]` when there's no property-based filtering (targeting all users)
- The `rollout_percentage` controls what percentage of the (possibly filtered) users see the flag:
  - Explicit percentage (e.g., 50): Only that percentage sees the flag
  - 100 or null: All users (who match the property filters, if any) see the flag

# Error Handling

If you encounter validation errors:
1. Read the error message carefully
2. Use the suggested property name if provided
3. Try a different operator if the current one is invalid
4. Use `ask_user_for_help` if you can't resolve the issue

Remember: Your goal is to create a precise, validated feature flag configuration that matches the user's intent.
""".strip()


class FeatureFlagToolkit(TaxonomyAgentToolkit):
    """Toolkit for feature flag creation with property discovery and validation."""

    def __init__(self, team: Team, user: User):
        super().__init__(team, user)

    def _get_custom_tools(self) -> list:
        """Get custom tools for feature flag creation."""

        class validate_property_filter(BaseModel):
            """
            Validate that a property filter is correctly structured before including it in the feature flag.
            Returns validation result with suggestions if invalid.

            Use this tool to verify:
            - Property exists for the entity type
            - Operator is valid for the property type
            - Value format is correct

            Always validate filters before using final_answer.
            """

            key: str = Field(description="Property name to validate")
            entity: str = Field(description="Entity type (e.g., 'person', 'organization', 'company', 'team')")
            operator: str = Field(description="Operator to use (e.g., 'exact', 'icontains', 'gt')")
            value: str = Field(description="Property value to match")

        class final_answer(base_final_answer[FeatureFlagCreationSchema]):
            __doc__ = base_final_answer.__doc__

        return [
            validate_property_filter,
            final_answer,
            ask_user_for_help,
        ]

    async def handle_tools(self, tool_metadata: dict[str, list[tuple[TaxonomyTool, str]]]) -> dict[str, str]:
        """Handle custom tool execution."""
        results = {}
        unhandled_tools = {}

        for tool_name, tool_inputs in tool_metadata.items():
            if tool_name == "validate_property_filter":
                if tool_inputs:
                    for tool_input, tool_call_id in tool_inputs:
                        result = await self._validate_property_filter(
                            tool_input.arguments.key,  # type: ignore
                            tool_input.arguments.entity,  # type: ignore
                            tool_input.arguments.operator,  # type: ignore
                            tool_input.arguments.value,  # type: ignore
                        )
                        results[tool_call_id] = result
            else:
                unhandled_tools[tool_name] = tool_inputs

        if unhandled_tools:
            results.update(await super().handle_tools(unhandled_tools))
        return results

    async def _validate_property_filter(self, key: str, entity: str, operator: str, value: str) -> str:
        """Validate a property filter configuration."""

        @database_sync_to_async
        def check_property():
            # Determine property type from entity - PropertyDefinition.type is an integer field
            if entity == "person":
                prop_type = PropertyDefinition.Type.PERSON
            elif entity == "session":
                prop_type = PropertyDefinition.Type.SESSION
            else:
                # It's a group type
                prop_type = PropertyDefinition.Type.GROUP

            # Check if property exists
            prop_def = PropertyDefinition.objects.filter(team=self._team, name=key, type=prop_type).first()

            if not prop_def:
                # Try to be helpful with suggestions
                similar_props = PropertyDefinition.objects.filter(team=self._team, type=prop_type)[:5]
                if similar_props:
                    suggestions = ", ".join([p.name for p in similar_props])
                    return f"❌ Property '{key}' not found for {entity}. Similar properties: {suggestions}. Use retrieve_entity_properties to see all available properties."
                else:
                    return f"❌ Property '{key}' not found for {entity}. Use retrieve_entity_properties to see available properties."

            # Validate operator for property type
            valid_operators = self._get_valid_operators_for_property_type(prop_def.property_type or "String")

            if operator not in valid_operators:
                return f"❌ Operator '{operator}' not valid for property '{key}' (type: {prop_def.property_type}). Valid operators: {', '.join(valid_operators)}"

            # All validations passed
            return f"✅ Property filter valid: {key} {operator} {value} for {entity}"

        return await check_property()

    def _get_valid_operators_for_property_type(self, prop_type: str) -> list[str]:
        """Get valid operators for a property type."""
        if prop_type in ["Numeric", "DateTime"]:
            return ["exact", "is_not", "gt", "lt", "gte", "lte", "is_set", "is_not_set"]
        else:
            # String and other types
            return ["exact", "is_not", "icontains", "not_icontains", "is_set", "is_not_set"]


class FeatureFlagCreationNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[FeatureFlagCreationSchema]]):
    """Node for feature flag creation with property discovery and validation."""

    def __init__(self, team: Team, user: User, toolkit_class: type[FeatureFlagToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    def _get_system_prompt(self) -> ChatPromptTemplate:
        """Get system prompts for feature flag creation."""
        # Format the system prompt with available group types
        prompt = ChatPromptTemplate(
            [("system", FEATURE_FLAG_CREATION_SYSTEM_PROMPT)], template_format="mustache"
        ).format(
            available_group_types=self._team_group_types,
        )

        return ChatPromptTemplate([("system", prompt)], template_format="mustache")


class FeatureFlagCreationToolsNode(
    TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[FeatureFlagCreationSchema]]
):
    """Tools node for feature flag creation operations."""

    def __init__(self, team: Team, user: User, toolkit_class: type[FeatureFlagToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)


class FeatureFlagGeneratorGraph(TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[FeatureFlagCreationSchema]]):
    """
    Graph for AI-powered feature flag generation with property-based targeting.

    This graph uses a TaxonomyAgent to:
    1. Understand natural language instructions
    2. Discover available properties via read_taxonomy
    3. Validate property filters
    4. Generate structured feature flag configuration
    """

    def __init__(self, team: Team, user: User):
        super().__init__(
            team,
            user,
            loop_node_class=FeatureFlagCreationNode,
            tools_node_class=FeatureFlagCreationToolsNode,
            toolkit_class=FeatureFlagToolkit,
        )


class CreateFeatureFlagArgs(BaseModel):
    instructions: str = Field(
        description="Natural language description of the feature flag to create, "
        "including targeting criteria (e.g., 'Create a flag for 10% of users where email contains @company.com')"
    )


class CreateFeatureFlagTool(MaxTool):
    name: str = "create_feature_flag"
    description: str = """
Create a feature flag with optional property-based targeting from natural language instructions.

Use this tool when the user wants to:
- Create feature flags with basic rollout percentages
- Target specific user segments by properties (email, country, etc.)
- Roll out to specific groups (organizations, companies, teams)
- Combine rollout percentages with property filters

The tool will automatically:
1. Discover available properties using taxonomy
2. Validate property filters
3. Generate correct filter structure
4. Create the flag with targeting rules

# Examples

**Simple rollout:**
- "Create a flag for dark mode at 50% rollout"
- "Create a feature toggle for the new dashboard"

**Property-based targeting:**
- "Create a flag for users where email contains @company.com"
- "Create a flag targeting enterprise organizations"
- "Create a flag for users in the US"

**Combined targeting:**
- "Create a flag for 10% of users where email contains @company.com"
- "Create a flag for 25% of organizations where plan is enterprise"
- "Create a flag for US users over 25 years old at 50% rollout"

**Group-based:**
- "Create a flag targeting organizations"
- "Create a flag for companies where employee count > 100"
    """.strip()
    context_system_prompt_template: str = (
        "Creates a new feature flag in the project with optional property-based targeting"
    )
    billable: bool = True
    args_schema: type[BaseModel] = CreateFeatureFlagArgs

    async def _create_flag_from_instructions(self, instructions: str) -> FeatureFlagCreationSchema:
        """Use TaxonomyAgent graph to generate structured flag configuration."""
        graph = FeatureFlagGeneratorGraph(team=self._team, user=self._user)

        graph_context = {
            "change": f"Create a feature flag based on these instructions: {instructions}",
            "output": None,
            "tool_progress_messages": [],
            "billable": self.billable,
            **self.context,
        }

        result = await graph.compile_full_graph().ainvoke(graph_context, self._config)

        if isinstance(result["output"], FeatureFlagCreationSchema):
            return result["output"]
        else:
            # Fallback if graph didn't return expected output
            capture_exception(
                Exception(f"Flag generation graph returned unexpected output type: {type(result.get('output'))}"),
                {"team_id": self._team.id, "user_id": self._user.id, "result": str(result)},
            )
            raise ValueError("Failed to generate flag configuration from instructions")

    async def _arun_impl(self, instructions: str) -> tuple[str, dict[str, Any]]:
        """Create feature flag from natural language instructions."""
        try:
            # Use graph to generate structured configuration
            flag_schema = await self._create_flag_from_instructions(instructions)

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
            # The schema already provides groups in the correct format (FeatureFlagGroupType)
            filters = {}
            if aggregation_group_type_index is not None:
                filters["aggregation_group_type_index"] = aggregation_group_type_index

            # Convert Pydantic models to dicts for JSON storage
            filters["groups"] = [group.model_dump(exclude_none=True) for group in flag_schema.groups]

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
