from typing import Any, Literal, Self

import structlog
from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.schema import HogQLQuery

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.data_warehouse.backend.max_tools import HogQLGeneratorGraph
from products.data_warehouse.backend.prompts import HOGQL_GENERATOR_USER_PROMPT

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.context import AssistantContextManager
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath

from .models import Endpoint, EndpointVersion, validate_endpoint_name

logger = structlog.get_logger(__name__)


async def generate_hogql_query(team: Team, user: User, instructions: str, current_query: str = "") -> HogQLQuery:
    """
    Generate a HogQL query using the shared HogQLGeneratorGraph.
    """
    graph = HogQLGeneratorGraph(team=team, user=user).compile_full_graph()

    user_prompt = HOGQL_GENERATOR_USER_PROMPT.format(
        instructions=instructions,
        current_query=current_query,
    )

    graph_context: dict[str, Any] = {
        "change": user_prompt,
        "output": None,
        "tool_progress_messages": [],
        "billable": True,
        "current_query": current_query,
    }

    result = await graph.ainvoke(graph_context)

    if result.get("intermediate_steps"):
        if result["intermediate_steps"][-1]:
            raise ValueError(result["intermediate_steps"][-1][0].tool_input)
        else:
            raise ValueError("Need more information to generate the query")

    output = result.get("output")
    if not output:
        raise ValueError("Failed to generate query: no output from graph")

    return HogQLQuery(query=output)


class EndpointCreationSchema(BaseModel):
    """Schema for LLM-generated endpoint metadata."""

    name: str = Field(
        description="URL-safe endpoint name in kebab-case (e.g., 'daily-active-users', 'revenue-by-country'). "
        "Must start with a letter and contain only letters, numbers, hyphens, and underscores. Max 128 chars."
    )
    description: str = Field(description="Clear description of what data this endpoint exposes and when to use it.")
    is_active: bool = Field(
        default=True,
        description="Whether the endpoint should be immediately available via the API.",
    )
    cache_age_seconds: int | None = Field(
        default=None,
        description="Custom cache duration in seconds (300-86400). Leave as null to use default caching.",
    )


class CreateEndpointArgs(BaseModel):
    instructions: str = Field(
        description="Natural language instructions for creating the endpoint, including desired name and description. "
        "If no query is in context, include what data the endpoint should return (e.g., 'create an endpoint for daily active users')."
    )


ENDPOINT_CREATION_SYSTEM_PROMPT = """
You are an expert at creating PostHog API endpoints. Your task is to generate appropriate metadata for an endpoint based on the user's instructions and the query being wrapped.

# Context
- The query to expose is provided separately - you do NOT generate the query
- You generate: name, description, is_active, and optionally cache_age_seconds

# Naming Rules
- Names must be URL-safe: start with a letter, contain only letters, numbers, hyphens (-), and underscores (_)
- Use kebab-case (e.g., "daily-active-users" not "dailyActiveUsers")
- Keep names concise but descriptive (max 128 chars)
- Names should reflect what data the endpoint returns

# Description Guidelines
- Describe what data the endpoint returns
- Mention key filters or parameters if the query has variables
- Keep it concise (1-2 sentences)

# Cache Settings
- Leave cache_age_seconds as null for default caching (recommended)
- Only set custom cache if the user specifically requests it
- Valid range: 300 (5 min) to 86400 (24 hours)

# Examples

Query: SELECT count() FROM events WHERE event = '$pageview'
User: "Create an endpoint for pageview counts"
Output:
- name: "pageview-counts"
- description: "Returns the total count of pageview events."
- is_active: true
- cache_age_seconds: null

Query: SELECT properties.$current_url, count() FROM events GROUP BY 1
User: "Create an endpoint called top-pages for the marketing team"
Output:
- name: "top-pages"
- description: "Returns page URLs with their view counts, useful for marketing analytics."
- is_active: true
- cache_age_seconds: null
""".strip()


class CreateEndpointTool(MaxTool):
    name: Literal["create_endpoint"] = "create_endpoint"
    description: str = """
Create a new API endpoint to expose query results via a REST API.

Use this tool when the user wants to:
- Create an API endpoint from the current query or insight
- Expose data via a REST API for external consumption
- Set up a reusable data endpoint
- Create a new endpoint from scratch by describing what data it should return

If a query is in context (from insight or SQL editor), it will be used.
Otherwise, the tool can generate a query from the user's description.

Examples:
- "Create an endpoint for this query"
- "Make this insight available as an API"
- "Create an endpoint called daily-active-users"
- "Create an endpoint that returns the count of signups per day"
- "Make an endpoint for top 10 pages by pageviews"
    """.strip()
    context_prompt_template: str = (
        "Creates an API endpoint. Can use an existing query from context or generate one from the user's description."
    )
    args_schema: type[BaseModel] = CreateEndpointArgs

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        return cls(team=team, user=user, state=state, node_path=node_path, config=config)

    async def _generate_endpoint_metadata(self, instructions: str, query: dict) -> EndpointCreationSchema:
        """Use LLM to generate appropriate endpoint metadata."""
        llm = MaxChatOpenAI(
            user=self._user,
            team=self._team,
            model="gpt-4.1-mini",
            temperature=0.2,
        ).with_structured_output(EndpointCreationSchema)

        query_preview = str(query)[:500]  # Truncate for prompt
        prompt = f"{ENDPOINT_CREATION_SYSTEM_PROMPT}\n\nQuery being wrapped:\n{query_preview}\n\nUser instructions: {instructions}"

        result = await llm.ainvoke([{"role": "system", "content": prompt}])

        if isinstance(result, dict):
            return EndpointCreationSchema(**result)
        return result

    async def _arun_impl(self, instructions: str) -> tuple[str, dict[str, Any]]:
        # Get query from context
        query = self.context.get("query")
        generated_query = False

        # If no query in context, generate one from instructions
        if not query:
            try:
                hogql_query = await generate_hogql_query(
                    team=self._team,
                    user=self._user,
                    instructions=instructions,
                )
                query = hogql_query.model_dump()
                generated_query = True
            except PydanticOutputParserException as e:
                return (
                    f"Failed to generate valid query from your description: {e.validation_message}. "
                    "Try being more specific about what data you want the endpoint to return.",
                    {"error": "query_generation_failed", "details": str(e)},
                )
            except Exception as e:
                return (
                    f"Failed to generate query: {e}. "
                    "You can also use the SQL editor to create a query first, then create an endpoint from it.",
                    {"error": "query_generation_failed", "details": str(e)},
                )

        insight_name = self.context.get("insight_name")
        derived_from_insight = self.context.get("insight_short_id")

        try:
            # Generate metadata using LLM
            context_hint = f" (from insight: {insight_name})" if insight_name else ""
            if generated_query:
                context_hint = " (query generated from description)"
            metadata = await self._generate_endpoint_metadata(
                f"{instructions}{context_hint}",
                query,
            )

            # Validate the generated name
            try:
                validate_endpoint_name(metadata.name)
            except Exception as e:
                return f"Generated endpoint name '{metadata.name}' is invalid: {e}", {"error": "invalid_name"}

            # Validate cache_age_seconds if provided
            if metadata.cache_age_seconds is not None:
                if not (300 <= metadata.cache_age_seconds <= 86400):
                    return (
                        f"Invalid cache duration: {metadata.cache_age_seconds}s. Must be between 300 (5 min) and 86400 (24 hours) seconds.",
                        {"error": "invalid_cache", "value": metadata.cache_age_seconds},
                    )

            # Create the endpoint
            @database_sync_to_async
            def create_endpoint() -> tuple[Endpoint | None, Endpoint | None]:
                # Check if endpoint with this name already exists
                existing = Endpoint.objects.filter(team=self._team, name=metadata.name).first()
                if existing:
                    return None, existing

                endpoint = Endpoint.objects.create(
                    team=self._team,
                    created_by=self._user,
                    name=metadata.name,
                    description=metadata.description,
                    query=query,
                    is_active=metadata.is_active,
                    cache_age_seconds=metadata.cache_age_seconds,
                    derived_from_insight=derived_from_insight,
                    current_version=1,
                )

                # Create initial version
                EndpointVersion.objects.create(
                    endpoint=endpoint,
                    version=1,
                    query=query,
                    created_by=self._user,
                )

                return endpoint, None

            endpoint, existing = await create_endpoint()

            if existing:
                endpoint_url = f"/project/{self._team.project_id}/endpoints/{existing.name}"
                return (
                    f"An endpoint with name '{metadata.name}' already exists. View it at {endpoint_url}",
                    {"error": "already_exists", "endpoint_name": existing.name, "url": endpoint_url},
                )

            if not endpoint:
                return "Failed to create endpoint: unknown error", {"error": "creation_failed"}

            endpoint_url = f"/project/{self._team.project_id}/endpoints/{endpoint.name}"
            api_path = endpoint.endpoint_path

            logger.info(
                "endpoint_created_via_max",
                endpoint_name=endpoint.name,
                endpoint_id=str(endpoint.id),
                team_id=self._team.id,
                user_id=self._user.id,
                query_generated=generated_query,
            )

            query_note = " (query generated from your description)" if generated_query else ""
            return (
                f"Created endpoint '{endpoint.name}'{query_note}. API path: `{api_path}` | View at {endpoint_url}",
                {
                    "endpoint_name": endpoint.name,
                    "endpoint_id": str(endpoint.id),
                    "api_path": api_path,
                    "url": endpoint_url,
                    "description": metadata.description,
                    "query_generated": generated_query,
                },
            )

        except Exception as e:
            logger.exception(
                "endpoint_creation_failed",
                team_id=self._team.id,
                user_id=self._user.id,
                error=str(e),
            )
            capture_exception(e)
            return f"Failed to create endpoint: {e}", {"error": str(e)}


class EndpointUpdateSchema(BaseModel):
    """Schema for LLM-generated endpoint updates."""

    description: str | None = Field(
        default=None,
        description="New description for the endpoint. Set to null to keep current.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Whether the endpoint should be active. Set to null to keep current.",
    )
    cache_age_seconds: int | None = Field(
        default=None,
        description="New cache duration in seconds (300-86400), 0 to clear custom cache, or null to keep current.",
    )
    should_update_query: bool = Field(
        default=False,
        description="Whether to update the query to the new_query from context. Only set to true if the user explicitly wants to save/apply the query that was edited in the UI.",
    )
    query_instructions: str | None = Field(
        default=None,
        description="Natural language description of changes to make to the query. "
        "Set this when the user describes a query change in words (e.g., 'change the query to count signups', "
        "'add a filter for last 7 days'). Leave null if user doesn't want to change the query via description. "
        "This will generate a new HogQL query based on the instructions.",
    )


class UpdateEndpointArgs(BaseModel):
    instructions: str = Field(description="Natural language instructions for what to change on the endpoint.")


ENDPOINT_UPDATE_SYSTEM_PROMPT = """
You are an expert at updating PostHog API endpoints. Your task is to determine what changes to make based on the user's instructions.

# Current Endpoint
Name: {name} (cannot be changed)
Description: {description}
Active: {is_active}
Cache (seconds): {cache_age_seconds}
Current Query: {current_query}

# Available Updates
- description: New description text, or null to keep current
- is_active: true/false to enable/disable, or null to keep current
- cache_age_seconds: 300-86400 to set custom cache, 0 to clear, or null to keep current
- should_update_query: true only if user wants to save/apply a query that was already edited in the UI (new_query must be in context)
- query_instructions: Natural language instructions for generating a NEW query. Use this when the user describes what query they want in words. Set to null if no query changes are described.

# Rules
- Only change what the user asks for
- The endpoint name CANNOT be changed
- Set fields to null if not being changed
- For cache: 0 means "clear custom cache and use default", null means "don't change"
- For query updates, distinguish between:
  - "Save the query" / "Apply the changes" → should_update_query=true (for UI-edited queries)
  - "Change the query to..." / "Make the query select..." → query_instructions="..." (for generating new query)

# Examples

Current: description="Old desc", is_active=true
User: "Update the description to explain this returns user metrics"
Output: description="Returns aggregated user metrics for analytics.", is_active=null, cache_age_seconds=null, should_update_query=false, query_instructions=null

Current: is_active=true
User: "Disable this endpoint"
Output: description=null, is_active=false, cache_age_seconds=null, should_update_query=false, query_instructions=null

User: "Save the query" (and new_query exists in context)
Output: description=null, is_active=null, cache_age_seconds=null, should_update_query=true, query_instructions=null

User: "Change the query to count signups instead of pageviews"
Output: description=null, is_active=null, cache_age_seconds=null, should_update_query=false, query_instructions="Count signups instead of pageviews"

User: "Make the query filter for the last 30 days and group by country"
Output: description=null, is_active=null, cache_age_seconds=null, should_update_query=false, query_instructions="Filter for the last 30 days and group results by country"
""".strip()


class UpdateEndpointTool(MaxTool):
    name: Literal["update_endpoint"] = "update_endpoint"
    description: str = """
Update an existing API endpoint's configuration or query.

Use this tool when the user wants to:
- Change an endpoint's description
- Enable or disable an endpoint
- Update the cache settings
- Update the endpoint's query (either save UI changes or generate a new query from description)

The current endpoint details come from context.
Note: Endpoint names cannot be changed after creation.

Examples:
- "Update the description to be more detailed"
- "Disable this endpoint"
- "Set cache to 1 hour"
- "Save the query" (saves UI-edited query)
- "Change the query to count signups"
- "Make the query filter for last 7 days"
    """.strip()
    context_prompt_template: str = "Updates an existing API endpoint. Current endpoint state provided in context."
    args_schema: type[BaseModel] = UpdateEndpointArgs

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        return cls(team=team, user=user, state=state, node_path=node_path, config=config)

    async def _determine_updates(self, instructions: str, current: dict) -> EndpointUpdateSchema:
        """Use LLM to determine what updates to make."""
        llm = MaxChatOpenAI(
            user=self._user,
            team=self._team,
            model="gpt-4.1-mini",
            temperature=0.1,
        ).with_structured_output(EndpointUpdateSchema)

        current_query = current.get("query", {})
        if isinstance(current_query, dict):
            current_query_str = current_query.get("query", str(current_query))
        else:
            current_query_str = str(current_query)

        prompt = ENDPOINT_UPDATE_SYSTEM_PROMPT.format(
            name=current.get("name", "unknown"),
            description=current.get("description", ""),
            is_active=current.get("is_active", True),
            cache_age_seconds=current.get("cache_age_seconds", "default"),
            current_query=current_query_str[:500],  # Truncate for prompt
        )

        has_new_query = bool(self.context.get("new_query"))
        if has_new_query:
            prompt += "\n\nNote: A new query is available in context (edited in the UI). Set should_update_query=true if user wants to save/apply it."

        prompt += f"\n\nUser instructions: {instructions}"

        result = await llm.ainvoke([{"role": "system", "content": prompt}])

        if isinstance(result, dict):
            return EndpointUpdateSchema(**result)
        return result

    async def _arun_impl(self, instructions: str) -> tuple[str, dict[str, Any]]:
        current_endpoint = self.context.get("current_endpoint")
        if not current_endpoint:
            return (
                "No endpoint context provided. Please use this tool from an endpoint detail page.",
                {"error": "no_context"},
            )

        endpoint_name = current_endpoint.get("name")
        if not endpoint_name:
            return "Endpoint name not found in context.", {"error": "no_name"}

        new_query = self.context.get("new_query")

        try:
            # Determine what to update
            updates = await self._determine_updates(instructions, current_endpoint)

            # Validate cache if being set
            if updates.cache_age_seconds is not None and updates.cache_age_seconds != 0:
                if not (300 <= updates.cache_age_seconds <= 86400):
                    return (
                        f"Cache age must be between 300 and 86400 seconds, got {updates.cache_age_seconds}",
                        {"error": "invalid_cache"},
                    )

            # Handle query generation from natural language instructions
            generated_query = None
            if updates.query_instructions:
                try:
                    current_query = current_endpoint.get("query", {})
                    current_query_str = (
                        current_query.get("query", str(current_query))
                        if isinstance(current_query, dict)
                        else str(current_query)
                    )
                    generated_query = await generate_hogql_query(
                        team=self._team,
                        user=self._user,
                        instructions=updates.query_instructions,
                        current_query=current_query_str,
                    )
                except PydanticOutputParserException as e:
                    return (
                        f"Failed to generate valid query: {e.validation_message}",
                        {"error": "query_generation_failed", "details": str(e)},
                    )
                except Exception as e:
                    return (
                        f"Failed to generate query: {e}",
                        {"error": "query_generation_failed", "details": str(e)},
                    )

            # Check if there's anything to update
            has_changes = (
                updates.description is not None
                or updates.is_active is not None
                or updates.cache_age_seconds is not None
                or (updates.should_update_query and new_query)
                or generated_query is not None
            )

            if not has_changes:
                return "No changes requested.", {"error": "no_changes"}

            if updates.should_update_query and not new_query:
                return (
                    "Cannot save query: no query changes found in the editor. Make changes in the Query tab first.",
                    {"error": "no_new_query"},
                )

            @database_sync_to_async
            def update_endpoint() -> tuple[Endpoint, list[str], bool]:
                endpoint = Endpoint.objects.filter(team=self._team, name=endpoint_name).first()
                if not endpoint:
                    raise ValueError(f"Endpoint '{endpoint_name}' not found")

                changes: list[str] = []
                update_fields = ["updated_at"]
                created_new_version = False

                if updates.description is not None:
                    endpoint.description = updates.description
                    update_fields.append("description")
                    changes.append("description")

                if updates.is_active is not None:
                    endpoint.is_active = updates.is_active
                    update_fields.append("is_active")
                    changes.append("active" if updates.is_active else "inactive")

                if updates.cache_age_seconds is not None:
                    if updates.cache_age_seconds == 0:
                        endpoint.cache_age_seconds = None
                        changes.append("cache cleared")
                    else:
                        endpoint.cache_age_seconds = updates.cache_age_seconds
                        changes.append(f"cache set to {updates.cache_age_seconds}s")
                    update_fields.append("cache_age_seconds")

                # Handle UI-edited query
                if updates.should_update_query and new_query:
                    if endpoint.has_query_changed(new_query):
                        endpoint.create_new_version(new_query, self._user)
                        changes.append(f"query saved (v{endpoint.current_version})")
                        created_new_version = True

                # Handle generated query
                elif generated_query is not None:
                    query_dict = generated_query.model_dump()
                    if endpoint.has_query_changed(query_dict):
                        endpoint.create_new_version(query_dict, self._user)
                        changes.append(f"query generated and saved (v{endpoint.current_version})")
                        created_new_version = True

                if update_fields != ["updated_at"]:
                    endpoint.save(update_fields=update_fields)

                return endpoint, changes, created_new_version

            endpoint, changes, new_version = await update_endpoint()
            endpoint_url = f"/project/{self._team.project_id}/endpoints/{endpoint.name}"

            logger.info(
                "endpoint_updated_via_max",
                endpoint_name=endpoint.name,
                endpoint_id=str(endpoint.id),
                team_id=self._team.id,
                user_id=self._user.id,
                changes=changes,
                new_version=new_version,
            )

            changes_str = ", ".join(changes) if changes else "no changes"

            return (
                f"Updated endpoint '{endpoint.name}': {changes_str}. View at {endpoint_url}",
                {
                    "endpoint_name": endpoint.name,
                    "endpoint_id": str(endpoint.id),
                    "changes": changes,
                    "new_version": endpoint.current_version if new_version else None,
                    "url": endpoint_url,
                },
            )

        except ValueError as e:
            return f"Failed to update endpoint: {e}", {"error": str(e)}
        except Exception as e:
            logger.exception(
                "endpoint_update_failed",
                endpoint_name=endpoint_name,
                team_id=self._team.id,
                user_id=self._user.id,
                error=str(e),
            )
            capture_exception(e)
            return f"Failed to update endpoint: {e}", {"error": str(e)}
