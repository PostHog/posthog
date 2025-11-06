from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from posthog.schema import (
    AssistantFunnelsEventsNode,
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantMessage,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsEventsNode,
    AssistantTrendsQuery,
    DeepResearchNotebook,
    DeepResearchType,
    ProsemirrorJSONContent,
    TaskExecutionStatus,
)

from posthog.models import Team, User

from products.enterprise.backend.hogai.graph.deep_research.report.nodes import DeepResearchReportNode, FormattedInsight
from products.enterprise.backend.hogai.graph.deep_research.types import (
    DeepResearchIntermediateResult,
    DeepResearchState,
    PartialDeepResearchState,
)
from products.enterprise.backend.hogai.notebook.notebook_serializer import NotebookContext
from products.enterprise.backend.hogai.utils.types import InsightArtifact
from products.enterprise.backend.hogai.utils.types.base import TaskArtifact, TaskResult


class TestDeepResearchReportNode:
    def setup_method(self):
        self.team = MagicMock(spec=Team)
        self.team.id = 1
        self.user = MagicMock(spec=User)
        self.user.id = 1

        self.node = DeepResearchReportNode(self.team, self.user)
        self.config = RunnableConfig(configurable={"thread_id": str(uuid4())})

    def create_sample_artifact(self, task_id: str = "artifact_1", query_type: str = "trends") -> InsightArtifact:
        """Sample artifacts for testing."""
        query: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
        if query_type == "trends":
            query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode()])
        elif query_type == "funnels":
            query = AssistantFunnelsQuery(
                series=[AssistantFunnelsEventsNode(event="$pageview")], funnelsFilter=AssistantFunnelsFilter()
            )
        elif query_type == "retention":
            target_entity = AssistantRetentionEventsNode(name="$pageview")
            returning_entity = AssistantRetentionEventsNode(name="$identify")
            query = AssistantRetentionQuery(
                retentionFilter=AssistantRetentionFilter(targetEntity=target_entity, returningEntity=returning_entity)
            )
        elif query_type == "hogql":
            query = AssistantHogQLQuery(query="SELECT * FROM events")
        else:
            query = AssistantTrendsQuery(series=[AssistantTrendsEventsNode()])

        return InsightArtifact(id=None, task_id=task_id, query=query, content=f"Sample {query_type} insight")

    def create_sample_state(
        self,
        artifacts: list[InsightArtifact] | None = None,
        intermediate_results: list[DeepResearchIntermediateResult] | None = None,
        last_message_content: str = "Report generation complete",
    ) -> DeepResearchState:
        """Helper to create sample state for testing."""
        if artifacts is None:
            artifacts = [self.create_sample_artifact()]

        if intermediate_results is None:
            intermediate_results = [
                DeepResearchIntermediateResult(
                    content="Analysis shows user engagement trends",
                    artifact_ids=[artifacts[0].task_id] if artifacts else [],
                )
            ]

        task_results = [
            TaskResult(
                id="task_1",
                description="Analyze user behavior",
                result="Users show high engagement",
                artifacts=artifacts,
                status=TaskExecutionStatus.COMPLETED,
            )
        ]

        last_message = AssistantToolCallMessage(content=last_message_content, tool_call_id="tool_call_1")

        return DeepResearchState(
            messages=[last_message], task_results=task_results, intermediate_results=intermediate_results
        )

    def test_collect_all_artifacts_success(self):
        """Test that artifacts are collected correctly from task results."""
        artifact1 = self.create_sample_artifact("artifact_1", "trends")
        artifact2 = self.create_sample_artifact("artifact_2", "funnels")

        state = DeepResearchState(
            task_results=[
                TaskResult(
                    id="task_1",
                    description="Task 1",
                    result="Result 1",
                    artifacts=[artifact1, artifact2],
                    status=TaskExecutionStatus.COMPLETED,
                )
            ],
            intermediate_results=[
                DeepResearchIntermediateResult(content="Analysis", artifact_ids=["artifact_1", "artifact_2"])
            ],
        )

        artifacts = self.node._collect_all_artifacts(state)

        assert len(artifacts) == 2
        assert artifacts[0].task_id == "artifact_1"
        assert artifacts[1].task_id == "artifact_2"

    def test_collect_all_artifacts_filters_invalid_ids(self):
        """Test that artifacts with invalid IDs are filtered out."""
        artifact1 = self.create_sample_artifact("artifact_1", "trends")
        artifact2 = self.create_sample_artifact("artifact_2", "funnels")

        state = DeepResearchState(
            task_results=[
                TaskResult(
                    id="task_1",
                    description="Task 1",
                    result="Result 1",
                    artifacts=[artifact1, artifact2],
                    status=TaskExecutionStatus.COMPLETED,
                )
            ],
            intermediate_results=[
                DeepResearchIntermediateResult(
                    content="Analysis",
                    artifact_ids=["artifact_1"],
                )
            ],
        )

        artifacts = self.node._collect_all_artifacts(state)

        assert len(artifacts) == 1
        assert artifacts[0].task_id == "artifact_1"

    def test_collect_all_artifacts_empty_results(self):
        """Test that empty task results return empty artifact list."""
        state = DeepResearchState(task_results=[], intermediate_results=[])

        artifacts = self.node._collect_all_artifacts(state)

        assert len(artifacts) == 0

    @parameterized.expand(
        [
            ("trends", AssistantTrendsQuery, "Trends"),
            ("funnels", AssistantFunnelsQuery, "Funnel"),
            ("retention", AssistantRetentionQuery, "Retention"),
            ("hogql", AssistantHogQLQuery, "SQL Query"),
        ]
    )
    def test_get_query_type_name(self, query_type, query_class, expected_name):
        """Test that query type names are correctly identified."""
        query = self.create_sample_artifact(query_type=query_type).query
        result = self.node._get_query_type_name(query)
        assert result == expected_name

    def test_get_query_type_name_unknown_query(self):
        """Test that unknown query types return generic 'Query'."""
        unknown_query = MagicMock()
        result = self.node._get_query_type_name(unknown_query)
        assert result == "Query"

    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor")
    def test_format_insights_success(self, mock_executor_class):
        """Test that insights are formatted correctly when query execution is successful."""
        mock_executor = MagicMock()
        mock_executor.run_and_format_query.return_value = ("Formatted results", False)
        mock_executor_class.return_value = mock_executor

        artifacts: list[TaskArtifact] = [self.create_sample_artifact("artifact_1", "trends")]

        formatted_insights = self.node._format_insights(artifacts)

        assert len(formatted_insights) == 1
        insight = formatted_insights[0]
        assert insight.id == "artifact_1"
        assert insight.description == "Sample trends insight"
        assert insight.formatted_results == "Formatted results"
        assert insight.query_type == "Trends"

    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor")
    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.capture_exception")
    def test_format_insights_handles_execution_error(self, mock_capture_exception, mock_executor_class):
        """Test that insights formatting handles query execution errors gracefully."""
        mock_executor = MagicMock()
        mock_executor.run_and_format_query.side_effect = Exception("Query execution failed")
        mock_executor_class.return_value = mock_executor

        artifacts: list[TaskArtifact] = [self.create_sample_artifact("artifact_1", "trends")]

        formatted_insights = self.node._format_insights(artifacts)

        assert len(formatted_insights) == 1
        insight = formatted_insights[0]
        assert insight.id == "artifact_1"
        assert insight.description == "Sample trends insight"
        # Empty due to error
        assert insight.formatted_results == ""
        assert insight.query_type == "Trends"

        mock_capture_exception.assert_called_once()

    def test_format_insights_skips_artifacts_without_queries(self):
        """Test that artifacts without queries are skipped during formatting."""
        # Create artifact and then manually set query to None to test the edge case
        artifact = self.create_sample_artifact("artifact_1", "trends")
        artifact.query = None  # type: ignore

        formatted_insights = self.node._format_insights([artifact])

        assert len(formatted_insights) == 0

    @parameterized.expand(
        [
            # Case: Normal intermediate results
            (
                [
                    DeepResearchIntermediateResult(
                        content="First analysis result", artifact_ids=["artifact_1", "artifact_2"]
                    ),
                    DeepResearchIntermediateResult(content="Second analysis result", artifact_ids=["artifact_3"]),
                ],
                "### Intermediate Result 1\nFirst analysis result\nReferenced insights: artifact_1, artifact_2\n\n### Intermediate Result 2\nSecond analysis result\nReferenced insights: artifact_3\n",
            ),
            # Case: Results without artifact IDs
            (
                [DeepResearchIntermediateResult(content="Analysis without artifacts", artifact_ids=[])],
                "### Intermediate Result 1\nAnalysis without artifacts\n",
            ),
            # Case: Empty results
            ([], "No intermediate results available."),
        ]
    )
    def test_format_intermediate_results(self, intermediate_results, expected_output):
        """Test formatting of intermediate results for the prompt."""
        result = self.node._format_intermediate_results(intermediate_results)
        assert result == expected_output

    @parameterized.expand(
        [
            # Case: Normal formatted insights
            (
                [
                    FormattedInsight(
                        id="insight_1",
                        description="User engagement trends",
                        formatted_results="Data shows 25% increase",
                        query_type="Trends",
                    ),
                    FormattedInsight(
                        id="insight_2",
                        description="Conversion funnel analysis",
                        formatted_results="3 step funnel with 60% completion",
                        query_type="Funnel",
                    ),
                ],
                "### Insight: insight_1\n**Type**: Trends\n**Description**: User engagement trends\n**Data**:\nData shows 25% increase\n\n### Insight: insight_2\n**Type**: Funnel\n**Description**: Conversion funnel analysis\n**Data**:\n3 step funnel with 60% completion\n",
            ),
            # Case: Empty insights
            ([], "No insights available."),
        ]
    )
    def test_format_artifacts_summary(self, formatted_insights, expected_output):
        """Test formatting of artifacts summary for the prompt."""
        result = self.node._format_artifacts_summary(formatted_insights)
        assert result == expected_output

    def test_create_context(self):
        """Test that notebook context is created correctly."""
        artifacts: list[TaskArtifact] = [
            self.create_sample_artifact("artifact_1", "trends"),
            self.create_sample_artifact("artifact_2", "funnels"),
        ]

        context = self.node._create_context(artifacts)

        assert isinstance(context, NotebookContext)
        assert len(context.insights) == 2
        assert "artifact_1" in context.insights
        assert "artifact_2" in context.insights
        assert context.insights["artifact_1"] == artifacts[0]
        assert context.insights["artifact_2"] == artifacts[1]

    @pytest.mark.asyncio
    @patch.object(DeepResearchReportNode, "_get_model")
    @patch.object(DeepResearchReportNode, "_astream_notebook")
    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor")
    @patch("langgraph.config.get_config")
    @patch("langgraph.config.get_stream_writer")
    async def test_arun_success(
        self, mock_get_stream_writer, mock_get_config, mock_executor_class, mock_astream_notebook, mock_get_model
    ):
        """Test that arun successfully generates a report."""
        mock_get_stream_writer.return_value = MagicMock()
        mock_get_config.return_value = {"configurable": {"thread_id": "test_thread"}}

        mock_executor = MagicMock()
        mock_executor.run_and_format_query.return_value = ("Formatted results", False)
        mock_executor_class.return_value = mock_executor

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test_notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream_notebook.return_value = mock_notebook

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        state = self.create_sample_state()

        result = await self.node.arun(state, self.config)

        assert isinstance(result, PartialDeepResearchState)
        assert len(result.messages) == 1

        mock_get_model.assert_called_once()
        mock_astream_notebook.assert_called_once()

    @pytest.mark.asyncio
    @patch.object(DeepResearchReportNode, "_get_model")
    async def test_arun_raises_error_for_non_tool_call_message(self, mock_get_model):
        """Test that arun raises ValueError when last message is not a tool call."""
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        state = DeepResearchState(
            messages=[AssistantMessage(content="Not a tool call message")], task_results=[], intermediate_results=[]
        )

        with pytest.raises(ValueError, match="Last message is not a tool call message"):
            await self.node.arun(state, self.config)

    @pytest.mark.asyncio
    @patch.object(DeepResearchReportNode, "_get_model")
    @patch.object(DeepResearchReportNode, "_astream_notebook")
    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor")
    @patch("langgraph.config.get_config")
    @patch("langgraph.config.get_stream_writer")
    async def test_arun_handles_empty_artifacts(
        self, mock_get_stream_writer, mock_get_config, mock_executor_class, mock_astream_notebook, mock_get_model
    ):
        """Test that arun handles cases with no artifacts gracefully."""
        mock_get_stream_writer.return_value = MagicMock()
        mock_get_config.return_value = {"configurable": {"thread_id": "test_thread"}}
        mock_notebook = MagicMock()
        mock_notebook.short_id = "test_notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream_notebook.return_value = mock_notebook

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        state = DeepResearchState(
            messages=[AssistantToolCallMessage(content="Complete", tool_call_id="tool_1")],
            task_results=[],
            intermediate_results=[],
        )

        result = await self.node.arun(state, self.config)

        assert isinstance(result, PartialDeepResearchState)
        assert len(result.messages) == 1

    @pytest.mark.asyncio
    @patch.object(DeepResearchReportNode, "_get_model")
    @patch.object(DeepResearchReportNode, "_astream_notebook")
    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor")
    @patch("langgraph.config.get_config")
    @patch("langgraph.config.get_stream_writer")
    async def test_arun_handles_empty_intermediate_results(
        self, mock_get_stream_writer, mock_get_config, mock_executor_class, mock_astream_notebook, mock_get_model
    ):
        """Test that arun handles cases with no intermediate results gracefully."""
        mock_get_stream_writer.return_value = MagicMock()
        mock_get_config.return_value = {"configurable": {"thread_id": "test_thread"}}
        mock_executor = MagicMock()
        mock_executor.run_and_format_query.return_value = ("Formatted results", False)
        mock_executor_class.return_value = mock_executor

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test_notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream_notebook.return_value = mock_notebook

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        # Create state with artifacts but no intermediate results
        artifacts: list[TaskArtifact] = [self.create_sample_artifact("artifact_1", "trends")]
        state = DeepResearchState(
            messages=[AssistantToolCallMessage(content="Complete", tool_call_id="tool_1")],
            task_results=[
                TaskResult(
                    id="task_1",
                    description="Task 1",
                    result="Result",
                    artifacts=artifacts,
                    status=TaskExecutionStatus.COMPLETED,
                )
            ],
            intermediate_results=[],
        )

        result = await self.node.arun(state, self.config)

        assert isinstance(result, PartialDeepResearchState)
        assert len(result.messages) == 1

    @pytest.mark.asyncio
    @patch.object(DeepResearchReportNode, "_get_model")
    @patch.object(DeepResearchReportNode, "_astream_notebook", side_effect=Exception("Streaming failed"))
    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor")
    async def test_arun_handles_streaming_errors(self, mock_executor_class, mock_astream_notebook, mock_get_model):
        """Test that arun propagates streaming errors appropriately."""
        mock_executor = MagicMock()
        mock_executor.run_and_format_query.return_value = ("Formatted results", False)
        mock_executor_class.return_value = mock_executor

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        state = self.create_sample_state()

        with pytest.raises(Exception, match="Streaming failed"):
            await self.node.arun(state, self.config)

    @pytest.mark.asyncio
    @patch.object(DeepResearchReportNode, "_get_model")
    @patch.object(DeepResearchReportNode, "_astream_notebook")
    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor")
    @patch("langgraph.config.get_config")
    @patch("langgraph.config.get_stream_writer")
    async def test_arun_passes_correct_parameters_to_stream(
        self, mock_get_stream_writer, mock_get_config, mock_executor_class, mock_astream_notebook, mock_get_model
    ):
        """Test that arun passes the correct parameters to the streaming method."""
        mock_get_stream_writer.return_value = MagicMock()
        mock_get_config.return_value = {"configurable": {"thread_id": "test_thread"}}
        mock_executor = MagicMock()
        mock_executor.run_and_format_query.return_value = ("Formatted results", False)
        mock_executor_class.return_value = mock_executor

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test_notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream_notebook.return_value = mock_notebook

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        state = self.create_sample_state()

        await self.node.arun(state, self.config)

        call_args = mock_astream_notebook.call_args
        assert call_args[0][1] == self.config

        stream_params = call_args[1]["stream_parameters"]
        assert "intermediate_results" in stream_params
        assert "artifacts" in stream_params

        context = call_args[1]["context"]
        assert isinstance(context, NotebookContext)

    def test_collect_all_artifacts_multiple_task_results(self):
        """Test that artifacts from multiple task results are collected correctly."""
        artifact1 = self.create_sample_artifact("artifact_1", "trends")
        artifact2 = self.create_sample_artifact("artifact_2", "funnels")
        artifact3 = self.create_sample_artifact("artifact_3", "retention")

        state = DeepResearchState(
            task_results=[
                TaskResult(
                    id="task_1",
                    description="Task 1",
                    result="Result 1",
                    artifacts=[artifact1, artifact2],
                    status=TaskExecutionStatus.COMPLETED,
                ),
                TaskResult(
                    id="task_2",
                    description="Task 2",
                    result="Result 2",
                    artifacts=[artifact3],
                    status=TaskExecutionStatus.COMPLETED,
                ),
            ],
            intermediate_results=[
                DeepResearchIntermediateResult(
                    content="Analysis", artifact_ids=["artifact_1", "artifact_2", "artifact_3"]
                )
            ],
        )

        artifacts = self.node._collect_all_artifacts(state)

        assert len(artifacts) == 3
        artifact_ids = [artifact.task_id for artifact in artifacts]
        assert "artifact_1" in artifact_ids
        assert "artifact_2" in artifact_ids
        assert "artifact_3" in artifact_ids

    def test_format_intermediate_results_with_mixed_artifact_ids(self):
        """Test formatting of intermediate results with mixed artifact ID patterns."""
        intermediate_results = [
            DeepResearchIntermediateResult(
                content="Analysis with multiple artifacts", artifact_ids=["artifact_1", "artifact_2", "artifact_3"]
            ),
            DeepResearchIntermediateResult(content="Analysis with one artifact", artifact_ids=["artifact_4"]),
            DeepResearchIntermediateResult(content="Analysis with no artifacts", artifact_ids=[]),
        ]

        result = self.node._format_intermediate_results(intermediate_results)

        expected = (
            "### Intermediate Result 1\n"
            "Analysis with multiple artifacts\n"
            "Referenced insights: artifact_1, artifact_2, artifact_3\n\n"
            "### Intermediate Result 2\n"
            "Analysis with one artifact\n"
            "Referenced insights: artifact_4\n\n"
            "### Intermediate Result 3\n"
            "Analysis with no artifacts\n"
        )

        assert result == expected

    @pytest.mark.asyncio
    @patch.object(DeepResearchReportNode, "_get_model")
    @patch.object(DeepResearchReportNode, "_astream_notebook")
    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor")
    @patch("langgraph.config.get_config")
    @patch("langgraph.config.get_stream_writer")
    async def test_arun_creates_proper_message_chain(
        self, mock_get_stream_writer, mock_get_config, mock_executor_class, mock_astream_notebook, mock_get_model
    ):
        """Test that arun creates proper message chain for LLM interaction."""
        mock_get_stream_writer.return_value = MagicMock()
        mock_get_config.return_value = {"configurable": {"thread_id": "test_thread"}}
        mock_executor = MagicMock()
        mock_executor.run_and_format_query.return_value = ("Formatted results", False)
        mock_executor_class.return_value = mock_executor

        mock_notebook = MagicMock()
        mock_notebook.short_id = "test_notebook"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream_notebook.return_value = mock_notebook
        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        tool_call_message = AssistantToolCallMessage(content="Task execution complete", tool_call_id="tool_call_123")
        state = DeepResearchState(
            messages=[tool_call_message],
            task_results=[
                TaskResult(
                    id="task_1",
                    description="Test task",
                    result="Test result",
                    artifacts=[self.create_sample_artifact()],
                    status=TaskExecutionStatus.COMPLETED,
                )
            ],
            intermediate_results=[DeepResearchIntermediateResult(content="Test analysis", artifact_ids=["artifact_1"])],
        )

        await self.node.arun(state, self.config)

        call_args = mock_astream_notebook.call_args
        assert call_args[0][1] == self.config

        stream_params = call_args[1]["stream_parameters"]
        assert "intermediate_results" in stream_params
        assert "artifacts" in stream_params
        assert "Test analysis" in stream_params["intermediate_results"]

    def test_format_insights_preserves_order(self):
        """Test that insights formatting preserves the order of artifacts."""
        with patch(
            "products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor"
        ) as mock_executor_class:
            mock_executor = MagicMock()
            mock_executor.run_and_format_query.return_value = ("Results", False)
            mock_executor_class.return_value = mock_executor

            artifacts: list[TaskArtifact] = [
                self.create_sample_artifact("artifact_1", "trends"),
                self.create_sample_artifact("artifact_2", "funnels"),
                self.create_sample_artifact("artifact_3", "retention"),
            ]

            formatted_insights = self.node._format_insights(artifacts)

            assert len(formatted_insights) == 3
            assert formatted_insights[0].id == "artifact_1"
            assert formatted_insights[1].id == "artifact_2"
            assert formatted_insights[2].id == "artifact_3"

    @pytest.mark.asyncio
    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.DeepResearchReportNode._get_model")
    @patch(
        "products.enterprise.backend.hogai.graph.deep_research.report.nodes.DeepResearchReportNode._astream_notebook"
    )
    @patch("products.enterprise.backend.hogai.graph.deep_research.report.nodes.AssistantQueryExecutor")
    @patch("langgraph.config.get_config")
    @patch("langgraph.config.get_stream_writer")
    async def test_arun_includes_stage_notebooks_in_final_message(
        self, mock_get_stream_writer, mock_get_config, mock_executor_class, mock_astream_notebook, mock_get_model
    ):
        """Test that the report node includes all stage notebooks in the final message."""
        mock_get_stream_writer.return_value = MagicMock()
        mock_get_config.return_value = {"configurable": {"thread_id": "test_thread"}}
        # Using DeepResearchNotebook instead of DeepResearchNotebookInfo

        mock_executor = MagicMock()
        mock_executor.run_and_format_query.return_value = ("Results", False)
        mock_executor_class.return_value = mock_executor

        mock_notebook = MagicMock()
        mock_notebook.short_id = "report_notebook_123"
        mock_notebook.title = "Test Notebook"
        mock_notebook.content = ProsemirrorJSONContent(type="doc", content=[])
        mock_astream_notebook.return_value = mock_notebook

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        mock_notebook = MagicMock()
        mock_notebook.title = "Final Research Report"
        self.node.notebook = mock_notebook

        existing_notebooks = [
            DeepResearchNotebook(
                notebook_type=DeepResearchType.PLANNING, notebook_id="planning_123", title="Planning Doc"
            ),
            DeepResearchNotebook(
                notebook_type=DeepResearchType.REPORT, notebook_id="intermediate_456", title="Analysis"
            ),
        ]

        tool_call_message = AssistantToolCallMessage(content="Task execution complete", tool_call_id="tool_call_123")
        state = DeepResearchState(
            messages=[tool_call_message],
            conversation_notebooks=existing_notebooks,
            current_run_notebooks=existing_notebooks,
            task_results=[],
            intermediate_results=[],
        )

        result = await self.node.arun(state, self.config)

        # Check that the new report notebook was added to conversation_notebooks
        assert len(result.conversation_notebooks) == 1  # Only the new report notebook
        # The new report notebook should be a REPORT type
        report_notebook = result.conversation_notebooks[0]
        assert report_notebook.notebook_type == DeepResearchType.REPORT
        assert report_notebook.notebook_id == "report_notebook_123"
        assert report_notebook.title == "Test Notebook"

        # Check that current_run_notebooks contains all notebooks
        assert result.current_run_notebooks is not None
        assert len(result.current_run_notebooks) == 3  # 2 existing + 1 new
