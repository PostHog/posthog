from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async
from parameterized import parameterized_class

from posthog.schema import HogQLQuery

from products.endpoints.backend.max_tools import CreateEndpointTool, EndpointCreationSchema, UpdateEndpointTool
from products.endpoints.backend.models import Endpoint, EndpointVersion

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


class BaseEndpointToolTest(BaseTest):
    def setUp(self):
        super().setUp()
        self.tool_call_id = str(uuid4())
        self.state = AssistantState(messages=[], root_tool_call_id=self.tool_call_id)
        self.sample_query = {
            "kind": "HogQLQuery",
            "query": "SELECT event, count() FROM events WHERE event = '$pageview' GROUP BY event",
        }

    def _create_context_manager(self, tool_name: str, context: dict | None = None):
        mock_context_manager = MagicMock()
        mock_context_manager.get_contextual_tools = MagicMock(
            return_value={tool_name: context if context is not None else {}}
        )
        return mock_context_manager

    def _create_create_tool(self, context: dict | None = None):
        return CreateEndpointTool(
            team=self.team,
            user=self.user,
            state=self.state,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
            context_manager=self._create_context_manager("create_endpoint", context),
        )

    def _create_update_tool(self, context: dict | None = None):
        return UpdateEndpointTool(
            team=self.team,
            user=self.user,
            state=self.state,
            node_path=(NodePath(name="test_node", tool_call_id=self.tool_call_id, message_id="test"),),
            context_manager=self._create_context_manager("update_endpoint", context),
        )

    def _create_endpoint_sync(
        self,
        name="test-endpoint",
        description="Test description",
        is_active=True,
        cache_age_seconds=None,
    ):
        endpoint = Endpoint.objects.create(
            team=self.team,
            created_by=self.user,
            name=name,
            description=description,
            query=self.sample_query,
            is_active=is_active,
            cache_age_seconds=cache_age_seconds,
            current_version=1,
        )
        EndpointVersion.objects.create(
            endpoint=endpoint,
            version=1,
            query=self.sample_query,
            created_by=self.user,
        )
        return endpoint

    async def _create_endpoint(self, **kwargs):
        return await sync_to_async(self._create_endpoint_sync)(**kwargs)


class TestCreateEndpointTool(BaseEndpointToolTest):
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_endpoint_with_query_in_context(self):
        context = {"query": self.sample_query, "insight_short_id": "abc123"}
        tool = self._create_create_tool(context=context)
        mock_metadata = EndpointCreationSchema(
            name="pageview-counts",
            description="Returns pageview counts",
            is_active=True,
            cache_age_seconds=None,
        )

        with patch.object(tool, "_generate_endpoint_metadata", AsyncMock(return_value=mock_metadata)):
            result_text, result_data = await tool._arun_impl(instructions="Create an endpoint")

        assert "pageview-counts" in result_text
        assert "api_path" in result_data
        assert result_data["query_generated"] is False

        endpoint = await sync_to_async(Endpoint.objects.get)(team=self.team, name="pageview-counts")
        assert endpoint.query == self.sample_query
        assert endpoint.derived_from_insight == "abc123"
        assert endpoint.current_version == 1

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_endpoint_generates_query_from_instructions(self):
        tool = self._create_create_tool(context={})
        mock_metadata = EndpointCreationSchema(
            name="daily-active-users",
            description="Returns daily active users",
            is_active=True,
            cache_age_seconds=None,
        )
        generated_query_str = "SELECT count(distinct person_id) FROM events"

        with patch(
            "products.endpoints.backend.max_tools.generate_hogql_query",
            AsyncMock(return_value=HogQLQuery(query=generated_query_str)),
        ):
            with patch.object(tool, "_generate_endpoint_metadata", AsyncMock(return_value=mock_metadata)):
                result_text, result_data = await tool._arun_impl(instructions="Create endpoint for DAU")

        assert "daily-active-users" in result_text
        assert result_data["query_generated"] is True

        endpoint = await sync_to_async(Endpoint.objects.get)(team=self.team, name="daily-active-users")
        assert endpoint.query["query"] == generated_query_str

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_endpoint_existing_name_returns_error(self):
        await self._create_endpoint(name="existing-endpoint")
        tool = self._create_create_tool(context={"query": self.sample_query})
        mock_metadata = EndpointCreationSchema(
            name="existing-endpoint",
            description="Duplicate",
            is_active=True,
            cache_age_seconds=None,
        )

        with patch.object(tool, "_generate_endpoint_metadata", AsyncMock(return_value=mock_metadata)):
            result_text, result_data = await tool._arun_impl(instructions="Create endpoint")

        assert "already exists" in result_text
        assert result_data["error"] == "already_exists"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_endpoint_query_generation_fails(self):
        tool = self._create_create_tool(context={})

        with patch(
            "products.endpoints.backend.max_tools.generate_hogql_query",
            AsyncMock(side_effect=ValueError("Failed to generate query: no output from graph")),
        ):
            result_text, result_data = await tool._arun_impl(instructions="Create endpoint")

        assert "Failed to generate query" in result_text
        assert result_data["error"] == "query_generation_failed"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_endpoint_query_generation_parser_exception(self):
        tool = self._create_create_tool(context={})
        mock_exception = PydanticOutputParserException(
            llm_output="SELECT invalid",
            validation_message="Query validation failed",
        )

        with patch(
            "products.endpoints.backend.max_tools.generate_hogql_query",
            AsyncMock(side_effect=mock_exception),
        ):
            result_text, result_data = await tool._arun_impl(instructions="Create endpoint")

        assert "Failed to generate valid query" in result_text
        assert result_data["error"] == "query_generation_failed"


class TestUpdateEndpointTool(BaseEndpointToolTest):
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_endpoint_no_context_returns_error(self):
        tool = self._create_update_tool(context={})

        result_text, result_data = await tool._arun_impl(instructions="Update")

        assert "No endpoint context provided" in result_text
        assert result_data["error"] == "no_context"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_endpoint_changes_description(self):
        endpoint = await self._create_endpoint()
        context = {
            "current_endpoint": {
                "name": endpoint.name,
                "description": endpoint.description,
                "is_active": endpoint.is_active,
                "cache_age_seconds": endpoint.cache_age_seconds,
                "query": self.sample_query,
            }
        }
        tool = self._create_update_tool(context=context)
        mock_updates = MagicMock(
            description="Updated description",
            is_active=None,
            cache_age_seconds=None,
            should_update_query=False,
            query_instructions=None,
        )

        with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
            result_text, result_data = await tool._arun_impl(instructions="Update description")

        assert "description" in result_data["changes"]
        await sync_to_async(endpoint.refresh_from_db)()
        assert endpoint.description == "Updated description"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_endpoint_toggles_active_status(self):
        endpoint = await self._create_endpoint(is_active=True)
        context = {
            "current_endpoint": {
                "name": endpoint.name,
                "description": endpoint.description,
                "is_active": True,
                "cache_age_seconds": None,
                "query": self.sample_query,
            }
        }
        tool = self._create_update_tool(context=context)
        mock_updates = MagicMock(
            description=None,
            is_active=False,
            cache_age_seconds=None,
            should_update_query=False,
            query_instructions=None,
        )

        with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
            result_text, result_data = await tool._arun_impl(instructions="Disable endpoint")

        assert "inactive" in result_data["changes"]
        await sync_to_async(endpoint.refresh_from_db)()
        assert endpoint.is_active is False

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_endpoint_saves_ui_edited_query(self):
        endpoint = await self._create_endpoint()
        new_query = {"kind": "HogQLQuery", "query": "SELECT count() FROM events"}
        context = {
            "current_endpoint": {
                "name": endpoint.name,
                "description": endpoint.description,
                "is_active": endpoint.is_active,
                "cache_age_seconds": None,
                "query": self.sample_query,
            },
            "new_query": new_query,
        }
        tool = self._create_update_tool(context=context)
        mock_updates = MagicMock(
            description=None,
            is_active=None,
            cache_age_seconds=None,
            should_update_query=True,
            query_instructions=None,
        )

        with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
            result_text, result_data = await tool._arun_impl(instructions="Save the query")

        assert "query saved" in " ".join(result_data["changes"])
        assert result_data["new_version"] == 2
        await sync_to_async(endpoint.refresh_from_db)()
        assert endpoint.query == new_query
        assert endpoint.current_version == 2

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_endpoint_generates_query_from_instructions(self):
        endpoint = await self._create_endpoint()
        context = {
            "current_endpoint": {
                "name": endpoint.name,
                "description": endpoint.description,
                "is_active": endpoint.is_active,
                "cache_age_seconds": None,
                "query": self.sample_query,
            }
        }
        tool = self._create_update_tool(context=context)
        new_query_str = "SELECT event FROM events WHERE event = '$signup'"
        mock_updates = MagicMock(
            description=None,
            is_active=None,
            cache_age_seconds=None,
            should_update_query=False,
            query_instructions="Change to signups",
        )

        with patch(
            "products.endpoints.backend.max_tools.generate_hogql_query",
            AsyncMock(return_value=HogQLQuery(query=new_query_str)),
        ):
            with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
                result_text, result_data = await tool._arun_impl(instructions="Change to signups")

        assert result_data["new_version"] == 2
        await sync_to_async(endpoint.refresh_from_db)()
        assert endpoint.query["query"] == new_query_str

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_endpoint_no_changes_returns_error(self):
        endpoint = await self._create_endpoint()
        context = {
            "current_endpoint": {
                "name": endpoint.name,
                "description": endpoint.description,
                "is_active": endpoint.is_active,
                "cache_age_seconds": None,
                "query": self.sample_query,
            }
        }
        tool = self._create_update_tool(context=context)
        mock_updates = MagicMock(
            description=None,
            is_active=None,
            cache_age_seconds=None,
            should_update_query=False,
            query_instructions=None,
        )

        with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
            result_text, result_data = await tool._arun_impl(instructions="Do nothing")

        assert "No changes requested" in result_text
        assert result_data["error"] == "no_changes"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_update_endpoint_not_found(self):
        context = {
            "current_endpoint": {
                "name": "nonexistent",
                "description": "Does not exist",
                "is_active": True,
                "cache_age_seconds": None,
                "query": self.sample_query,
            }
        }
        tool = self._create_update_tool(context=context)
        mock_updates = MagicMock(
            description="Updated",
            is_active=None,
            cache_age_seconds=None,
            should_update_query=False,
            query_instructions=None,
        )

        with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
            result_text, result_data = await tool._arun_impl(instructions="Update description")

        assert "Failed to update endpoint" in result_text
        assert "not found" in str(result_data["error"])


@parameterized_class(
    ("cache_value", "expected_in_changes"),
    [
        (3600, "cache set to 3600s"),
        (0, "cache cleared"),
    ],
)
class TestUpdateEndpointToolCacheSettings(BaseEndpointToolTest):
    cache_value: int
    expected_in_changes: str

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_cache_update(self):
        endpoint = await self._create_endpoint(cache_age_seconds=1800 if self.cache_value == 0 else None)
        context = {
            "current_endpoint": {
                "name": endpoint.name,
                "description": endpoint.description,
                "is_active": endpoint.is_active,
                "cache_age_seconds": endpoint.cache_age_seconds,
                "query": self.sample_query,
            }
        }
        tool = self._create_update_tool(context=context)
        mock_updates = MagicMock(
            description=None,
            is_active=None,
            cache_age_seconds=self.cache_value,
            should_update_query=False,
            query_instructions=None,
        )

        with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
            result_text, result_data = await tool._arun_impl(instructions="Update cache")

        assert self.expected_in_changes in result_data["changes"]
        await sync_to_async(endpoint.refresh_from_db)()
        expected_db_value = None if self.cache_value == 0 else self.cache_value
        assert endpoint.cache_age_seconds == expected_db_value


@parameterized_class(
    ("error_type", "error_key", "expected_message"),
    [
        ("invalid_cache", "invalid_cache", "Cache age must be between"),
        ("no_new_query", "no_new_query", "no query changes found"),
        ("query_generation_failed", "query_generation_failed", "Failed to generate valid query"),
    ],
)
class TestUpdateEndpointToolErrors(BaseEndpointToolTest):
    error_type: str
    error_key: str
    expected_message: str

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_error_scenario(self):
        endpoint = await self._create_endpoint()
        context = {
            "current_endpoint": {
                "name": endpoint.name,
                "description": endpoint.description,
                "is_active": endpoint.is_active,
                "cache_age_seconds": None,
                "query": self.sample_query,
            }
        }
        tool = self._create_update_tool(context=context)

        if self.error_type == "invalid_cache":
            mock_updates = MagicMock(
                description=None,
                is_active=None,
                cache_age_seconds=100000,
                should_update_query=False,
                query_instructions=None,
            )
            with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
                result_text, result_data = await tool._arun_impl(instructions="Set invalid cache")

        elif self.error_type == "no_new_query":
            mock_updates = MagicMock(
                description="Updated",
                is_active=None,
                cache_age_seconds=None,
                should_update_query=True,
                query_instructions=None,
            )
            with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
                result_text, result_data = await tool._arun_impl(instructions="Save query without changes")

        elif self.error_type == "query_generation_failed":
            mock_updates = MagicMock(
                description=None,
                is_active=None,
                cache_age_seconds=None,
                should_update_query=False,
                query_instructions="Make invalid query",
            )
            mock_exception = PydanticOutputParserException(
                llm_output="SELECT invalid",
                validation_message="Query parsing failed",
            )
            with patch(
                "products.endpoints.backend.max_tools.generate_hogql_query",
                AsyncMock(side_effect=mock_exception),
            ):
                with patch.object(tool, "_determine_updates", AsyncMock(return_value=mock_updates)):
                    result_text, result_data = await tool._arun_impl(instructions="Generate bad query")

        assert self.expected_message in result_text
        assert result_data["error"] == self.error_key
