import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantHogQLQuery, AssistantToolCall, AssistantToolCallMessage, TaskExecutionStatus

from posthog.models import Dashboard, Insight, Team, User

from products.enterprise.backend.hogai.graph.dashboards.nodes import (
    DashboardCreationExecutorNode,
    DashboardCreationNode,
    QueryMetadata,
)
from products.enterprise.backend.hogai.utils.helpers import build_dashboard_url, build_insight_url
from products.enterprise.backend.hogai.utils.types import AssistantState, PartialAssistantState
from products.enterprise.backend.hogai.utils.types.base import (
    AssistantNodeName,
    BaseStateWithTasks,
    InsightArtifact,
    InsightQuery,
    NodePath,
    TaskResult,
)


class TestQueryMetadata(BaseTest):
    def test_query_metadata_initialization(self):
        """Test QueryMetadata initialization with all fields."""
        query = InsightQuery(name="Test Query", description="Test Description")
        metadata = QueryMetadata(
            found_insight_ids={1, 2, 3},
            created_insight_ids={4, 5},
            found_insight_messages=["Found message 1", "Found message 2"],
            created_insight_messages=["Created message 1"],
            query=query,
        )

        self.assertEqual(metadata.found_insight_ids, {1, 2, 3})
        self.assertEqual(metadata.created_insight_ids, {4, 5})
        self.assertEqual(metadata.found_insight_messages, ["Found message 1", "Found message 2"])
        self.assertEqual(metadata.created_insight_messages, ["Created message 1"])
        self.assertEqual(metadata.query, query)


class TestDashboardCreationExecutorNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock(spec=Team)
        self.mock_team.id = 1
        self.mock_user = MagicMock(spec=User)
        self.mock_user.id = 1
        self.node = DashboardCreationExecutorNode(
            self.mock_team,
            self.mock_user,
            (
                NodePath(
                    name=AssistantNodeName.DASHBOARD_CREATION_EXECUTOR.value,
                    message_id="test_message_id",
                    tool_call_id="test_tool_call_id",
                ),
            ),
        )

    def test_initialization(self):
        """Test node initialization."""
        assert self.node._team == self.mock_team
        assert self.node._user == self.mock_user

    async def test_aget_input_tuples_search_insights(self):
        """Test _aget_input_tuples for search_insights tasks."""
        tool_calls = [
            AssistantToolCall(id="task_1", name="search_insights", args={"search_insights_query": "Test prompt"})
        ]

        input_tuples = await self.node._aget_input_tuples(tool_calls)

        assert len(input_tuples) == 1
        task, artifacts, callable_func = input_tuples[0]
        assert task.id == "task_1"
        assert task.name == "search_insights"
        assert callable_func == self.node._execute_search_insights

    async def test_aget_input_tuples_create_insight(self):
        """Test _aget_input_tuples for create_insight tasks."""
        tool_calls = [AssistantToolCall(id="task_1", name="create_insight", args={"query_description": "Test prompt"})]

        input_tuples = await self.node._aget_input_tuples(tool_calls)

        assert len(input_tuples) == 1
        task, artifacts, callable_func = input_tuples[0]
        assert task.id == "task_1"
        assert task.name == "create_insight"
        assert callable_func == self.node._execute_create_insight

    async def test_aget_input_tuples_unsupported_task(self):
        """Test _aget_input_tuples raises error for unsupported task type."""
        tool_calls = [AssistantToolCall(id="task_1", name="unsupported_type", args={"query": "Test prompt"})]

        with pytest.raises(ValueError) as exc_info:
            await self.node._aget_input_tuples(tool_calls)

        assert "Unsupported task type: unsupported_type" in str(exc_info.value)

    async def test_aget_input_tuples_no_tasks(self):
        """Test _aget_input_tuples returns empty list when no tasks."""
        tool_calls: list[AssistantToolCall] = []

        input_tuples = await self.node._aget_input_tuples(tool_calls)

        assert len(input_tuples) == 0


class TestDashboardCreationNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock(spec=Team)
        self.mock_team.id = 1
        self.mock_user = MagicMock(spec=User)
        self.mock_user.id = 1
        self.node = DashboardCreationNode(
            self.mock_team,
            self.mock_user,
            (
                NodePath(
                    name=AssistantNodeName.DASHBOARD_CREATION.value,
                    message_id="test_message_id",
                    tool_call_id="test_tool_call_id",
                ),
            ),
        )

    def test_get_found_insight_count(self):
        """Test _get_found_insight_count calculates correct count."""
        queries_metadata = {
            "query_1": QueryMetadata(
                found_insight_ids={1, 2, 3},
                created_insight_ids=set(),
                found_insight_messages=[],
                created_insight_messages=[],
                query=InsightQuery(name="Query 1", description="Description 1"),
            ),
            "query_2": QueryMetadata(
                found_insight_ids={4, 5},
                created_insight_ids=set(),
                found_insight_messages=[],
                created_insight_messages=[],
                query=InsightQuery(name="Query 2", description="Description 2"),
            ),
        }

        count = self.node._get_found_insight_count(queries_metadata)
        assert count == 5  # 3 + 2

    def test_build_insight_url(self):
        """Test _build_insight_url creates correct URL."""
        insight_id = "test_insight_id"
        url = build_insight_url(self.mock_team, insight_id)
        expected_url = f"/project/{self.mock_team.id}/insights/{insight_id}"
        assert url == expected_url

    def test_build_dashboard_url(self):
        """Test _build_dashboard_url creates correct URL."""
        dashboard_id = 123
        url = build_dashboard_url(self.mock_team, dashboard_id)
        expected_url = f"/project/{self.mock_team.id}/dashboard/{dashboard_id}"
        assert url == expected_url

    @patch("products.enterprise.backend.hogai.graph.dashboards.nodes.DashboardCreationExecutorNode")
    async def test_arun_missing_search_insights_queries(self, mock_executor_node_class):
        """Test arun returns error when search_insights_queries is missing."""
        mock_executor_node = MagicMock()
        mock_executor_node_class.return_value = mock_executor_node

        state = AssistantState(
            dashboard_name="Create dashboard",
            search_insights_queries=None,
            root_tool_call_id="test_tool_call_id",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        assert isinstance(result, PartialAssistantState)
        assert len(result.messages) == 1
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        assert "Search insights queries are required" in result.messages[0].content

    @patch("products.enterprise.backend.hogai.graph.dashboards.nodes.DashboardCreationExecutorNode")
    @patch.object(DashboardCreationNode, "_search_insights")
    @patch.object(DashboardCreationNode, "_create_insights")
    @patch.object(DashboardCreationNode, "_create_dashboard_with_insights")
    async def test_arun_successful_flow(
        self,
        mock_create_dashboard,
        mock_create_insights,
        mock_search_insights,
        mock_executor_node_class,
    ):
        """Test successful arun flow with found insights."""
        mock_executor_node = MagicMock()
        mock_executor_node_class.return_value = mock_executor_node

        # Setup mocks
        mock_dashboard = MagicMock(spec=Dashboard)
        mock_dashboard.id = 1
        mock_dashboard.name = "Test Dashboard"
        mock_insights = [MagicMock(spec=Insight), MagicMock(spec=Insight)]
        mock_insights[0].short_id = "insight_1"
        mock_insights[0].name = "Insight 1"
        mock_insights[1].short_id = "insight_2"
        mock_insights[1].name = "Insight 2"

        mock_create_dashboard.return_value = (mock_dashboard, mock_insights)

        # Setup search results with found insights
        search_result = {
            "query_1": QueryMetadata(
                found_insight_ids={1, 2},
                created_insight_ids=set(),
                found_insight_messages=["Found insights"],
                created_insight_messages=[],
                query=InsightQuery(name="Query 1", description="Description 1"),
            )
        }
        mock_search_insights.return_value = search_result
        mock_create_insights.return_value = search_result

        state = AssistantState(
            dashboard_name="Create dashboard",
            search_insights_queries=[InsightQuery(name="Query 1", description="Description 1")],
            root_tool_call_id="test_tool_call_id",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        assert isinstance(result, PartialAssistantState)
        assert len(result.messages) == 1
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        assert "Dashboard Created" in result.messages[0].content
        assert "Test Dashboard" in result.messages[0].content

    @patch("products.enterprise.backend.hogai.graph.dashboards.nodes.DashboardCreationExecutorNode")
    @patch.object(DashboardCreationNode, "_search_insights")
    @patch.object(DashboardCreationNode, "_create_insights")
    async def test_arun_no_insights_found_or_created(
        self, mock_create_insights, mock_search_insights, mock_executor_node_class
    ):
        """Test arun when no insights are found or created."""
        mock_executor_node = MagicMock()
        mock_executor_node_class.return_value = mock_executor_node

        # Setup search results with no insights
        search_result = {
            "query_1": QueryMetadata(
                found_insight_ids=set(),
                created_insight_ids=set(),
                found_insight_messages=["No insights found"],
                created_insight_messages=[],
                query=InsightQuery(name="Query 1", description="Description 1"),
            )
        }
        mock_search_insights.return_value = search_result
        mock_create_insights.return_value = search_result

        state = AssistantState(
            dashboard_name="Create dashboard",
            search_insights_queries=[InsightQuery(name="Query 1", description="Description 1")],
            root_tool_call_id="test_tool_call_id",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        assert isinstance(result, PartialAssistantState)
        assert len(result.messages) == 1
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        assert "No existing insights matched" in result.messages[0].content

    @patch("products.enterprise.backend.hogai.graph.dashboards.nodes.DashboardCreationExecutorNode")
    @patch.object(DashboardCreationNode, "_search_insights")
    @patch("products.enterprise.backend.hogai.graph.dashboards.nodes.logger")
    async def test_arun_exception_handling(self, mock_logger, mock_search_insights, mock_executor_node_class):
        """Test arun handles exceptions properly."""
        mock_executor_node = MagicMock()
        mock_executor_node_class.return_value = mock_executor_node
        mock_search_insights.side_effect = Exception("Test error")

        state = AssistantState(
            dashboard_name="Create dashboard",
            search_insights_queries=[InsightQuery(name="Query 1", description="Description 1")],
            root_tool_call_id="test_tool_call_id",
        )
        config = RunnableConfig()

        result = await self.node.arun(state, config)

        assert isinstance(result, PartialAssistantState)
        assert len(result.messages) == 1
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        assert "I encountered an issue while creating the dashboard" in result.messages[0].content
        mock_logger.exception.assert_called_once()

    def test_create_success_response(self):
        """Test _create_success_response creates correct success message."""
        mock_dashboard = MagicMock(spec=Dashboard)
        mock_dashboard.id = 1
        mock_dashboard.name = "Test Dashboard"

        mock_insights = [MagicMock(spec=Insight), MagicMock(spec=Insight)]
        mock_insights[0].short_id = "insight_1"
        mock_insights[0].name = "Insight 1"
        mock_insights[1].short_id = "insight_2"
        mock_insights[1].name = "Insight 2"

        result = self.node._create_success_response(
            mock_dashboard,
            mock_insights,  # type: ignore[arg-type]
            "test_tool_call_id",
            ["Query without insights"],
        )

        assert isinstance(result, PartialAssistantState)
        assert len(result.messages) == 1
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        assert "Dashboard Created" in result.messages[0].content
        assert "Test Dashboard" in result.messages[0].content
        assert "2 insights" in result.messages[0].content
        assert "Query without insights" in result.messages[0].content

    def test_create_no_insights_response(self):
        """Test _create_no_insights_response creates correct no insights message."""
        result = self.node._create_no_insights_response("test_tool_call_id", "No insights found")

        assert isinstance(result, PartialAssistantState)
        assert len(result.messages) == 1
        assert isinstance(result.messages[0], AssistantToolCallMessage)
        assert "No existing insights matched" in result.messages[0].content
        assert "No insights found" in result.messages[0].content

    def test_create_error_response(self):
        """Test _create_error_response creates correct error message."""
        with patch("products.enterprise.backend.hogai.graph.dashboards.nodes.capture_exception") as mock_capture:
            result = self.node._create_error_response("Test error", "test_tool_call_id")

            assert isinstance(result, PartialAssistantState)
            assert len(result.messages) == 1
            assert isinstance(result.messages[0], AssistantToolCallMessage)
            assert result.messages[0].content == "Test error"
            assert isinstance(result.messages[0], AssistantToolCallMessage)
            assert result.messages[0].tool_call_id == "test_tool_call_id"
            mock_capture.assert_called_once()


class TestDashboardCreationNodeAsyncMethods(BaseTest):
    def setUp(self):
        super().setUp()
        self.mock_team = MagicMock(spec=Team)
        self.mock_team.id = 1
        self.mock_user = MagicMock(spec=User)
        self.mock_user.id = 1
        self.node = DashboardCreationNode(
            self.mock_team,
            self.mock_user,
            node_path=(NodePath(name="test_node", message_id="test-id", tool_call_id="test_tool_call_id"),),
        )

    @patch("products.enterprise.backend.hogai.graph.dashboards.nodes.DashboardCreationExecutorNode")
    async def test_create_insights(self, mock_executor_node_class):
        """Test _create_insights method."""
        # Setup mocks
        mock_executor_node = MagicMock()
        mock_executor_node_class.return_value = mock_executor_node

        mock_task_result = TaskResult(
            id="task_1",
            result="Task completed successfully",
            artifacts=[
                InsightArtifact(
                    task_id="task_1", id=None, content="Test content", query=AssistantHogQLQuery(query="SELECT 1")
                )
            ],
            status=TaskExecutionStatus.COMPLETED,
        )
        mock_executor_node.arun = AsyncMock(return_value=BaseStateWithTasks(task_results=[mock_task_result]))

        # Mock _process_insight_creation_results to return the modified query_metadata
        async def mock_process_insight_creation_results(tool_calls, task_results, query_metadata):
            query_metadata["task_1"].created_insight_ids.add(1)
            query_metadata["task_1"].created_insight_ids.add(2)
            query_metadata["task_1"].created_insight_messages.append("Insight created")
            return query_metadata

        with patch.object(
            self.node, "_process_insight_creation_results", side_effect=mock_process_insight_creation_results
        ):
            left_to_create = {"task_1": InsightQuery(name="Query 1", description="Description 1")}
            query_metadata = {
                "task_1": QueryMetadata(
                    found_insight_ids=set(),
                    created_insight_ids=set(),
                    found_insight_messages=[],
                    created_insight_messages=[],
                    query=InsightQuery(name="Query 1", description="Description 1"),
                )
            }

            config = RunnableConfig()

            result = await self.node._create_insights(left_to_create, query_metadata, config)

            assert "task_1" in result
            assert len(result["task_1"].created_insight_ids) == 2
            assert len(result["task_1"].created_insight_messages) == 1

    @patch("products.enterprise.backend.hogai.graph.dashboards.nodes.DashboardCreationExecutorNode")
    async def test_search_insights(self, mock_executor_node_class):
        """Test _search_insights method."""
        # Setup mocks
        mock_executor_node = MagicMock()
        mock_executor_node_class.return_value = mock_executor_node

        mock_task_result = TaskResult(
            id="task_1",
            result="Task completed successfully",
            artifacts=[
                InsightArtifact(
                    task_id="task_1", id=1, content="Test reason", query=AssistantHogQLQuery(query="SELECT 1")
                ),
                InsightArtifact(
                    task_id="task_1", id=2, content="Test reason", query=AssistantHogQLQuery(query="SELECT 1")
                ),
            ],
            status=TaskExecutionStatus.COMPLETED,
        )
        mock_executor_node.arun = AsyncMock(return_value=BaseStateWithTasks(task_results=[mock_task_result]))

        queries_metadata = {
            "task_1": QueryMetadata(
                found_insight_ids=set(),
                created_insight_ids=set(),
                found_insight_messages=[],
                created_insight_messages=[],
                query=InsightQuery(name="Query 1", description="Description 1"),
            )
        }

        config = RunnableConfig()

        result = await self.node._search_insights(queries_metadata, config)

        assert "task_1" in result
        assert len(result["task_1"].found_insight_ids) == 2
        assert len(result["task_1"].found_insight_messages) == 2

    @patch("products.enterprise.backend.hogai.graph.dashboards.nodes.database_sync_to_async")
    async def test_create_dashboard_with_insights(self, mock_db_sync):
        """Test _create_dashboard_with_insights method."""

        mock_dashboard = MagicMock(spec=Dashboard)
        mock_dashboard.id = 1
        mock_dashboard.name = "Test Dashboard"

        mock_insights = [MagicMock(spec=Insight), MagicMock(spec=Insight)]
        mock_insights[0].id = 1
        mock_insights[1].id = 2

        mock_sync_func = AsyncMock(return_value=(mock_dashboard, mock_insights))
        mock_db_sync.return_value = mock_sync_func

        result = await self.node._create_dashboard_with_insights("Test Dashboard", {1, 2})

        assert result[0] == mock_dashboard
        assert result[1] == mock_insights
        mock_sync_func.assert_called_once()

    async def test_process_insight_creation_results(self):
        """Test _process_insight_creation_results method."""
        # Create simple mocked Team and User instances like other tests
        team = MagicMock(spec=Team)
        team.id = 1
        team._state = MagicMock()
        team._state.db = None

        user = MagicMock(spec=User)
        user.id = 1
        user._state = MagicMock()
        user._state.db = None

        # Create a node with mocked models
        node = DashboardCreationNode(team, user)

        tool_calls = [
            AssistantToolCall(id="task_1", name="create_insight", args={"query_description": "Description 1"}),
            AssistantToolCall(id="task_2", name="create_insight", args={"query_description": "Description 2"}),
        ]

        task_results = [
            TaskResult(
                id="task_1",
                result="Task completed successfully",
                artifacts=[
                    InsightArtifact(
                        task_id="task_1", id=None, content="Test content", query=AssistantHogQLQuery(query="SELECT 1")
                    )
                ],
                status=TaskExecutionStatus.COMPLETED,
            ),
            TaskResult(
                id="task_2",
                result="Task failed",
                artifacts=[
                    InsightArtifact(
                        task_id="task_2", id=None, content="Test content", query=AssistantHogQLQuery(query="SELECT 1")
                    )
                ],
                status=TaskExecutionStatus.FAILED,
            ),
        ]
        query_metadata = {
            "task_1": QueryMetadata(
                found_insight_ids=set(),
                created_insight_ids=set(),
                found_insight_messages=[],
                created_insight_messages=[],
                query=InsightQuery(name="Query 1", description="Description 1"),
            ),
            "task_2": QueryMetadata(
                found_insight_ids=set(),
                created_insight_ids=set(),
                found_insight_messages=[],
                created_insight_messages=[],
                query=InsightQuery(name="Query 2", description="Description 2"),
            ),
        }

        # Mock only the database bulk creation method
        mock_insight = MagicMock(spec=Insight)
        mock_insight.id = 123

        with patch.object(node, "_save_insights", return_value=[mock_insight]):
            result = await node._process_insight_creation_results(tool_calls, task_results, query_metadata)

        assert "task_1" in result
        # Check that exactly one insight was created
        assert len(result["task_1"].created_insight_ids) == 1
        assert 123 in result["task_1"].created_insight_ids
        assert len(result["task_1"].created_insight_messages) == 1
        assert (
            result["task_1"].created_insight_messages[0]
            == "\n -Query 1: Insight was created successfully with the description **Description 1**"
        )
        assert "task_2" in result
        assert len(result["task_2"].created_insight_ids) == 0
        assert len(result["task_2"].created_insight_messages) == 1
        assert (
            result["task_2"].created_insight_messages[0]
            == "\n -Query 2: Could not create insights for the query with the description **Description 2**"
        )
