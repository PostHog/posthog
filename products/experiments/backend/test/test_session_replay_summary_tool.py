from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.session_recordings.models.session_recording import SessionRecording

from products.experiments.backend.max_tools import SessionReplaySummaryTool
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.hogai.utils.types import AssistantState


@freeze_time("2025-01-15T12:00:00Z")
class TestSessionReplaySummaryTool(APIBaseTest):
    """Comprehensive tests for SessionReplaySummaryTool"""

    async def acreate_feature_flag(self, key="test-experiment", variant_keys=None):
        """
        Create a feature flag with multivariate variants for experiments.

        Args:
            key: Feature flag key
            variant_keys: List of variant keys, defaults to ["control", "test"]
        """
        if variant_keys is None:
            variant_keys = ["control", "test"]

        variants = [
            {"key": variant_key, "name": variant_key.title(), "rollout_percentage": 100 // len(variant_keys)}
            for variant_key in variant_keys
        ]

        return await FeatureFlag.objects.acreate(
            name=f"Test experiment flag: {key}",
            key=key,
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {"variants": variants},
            },
            created_by=self.user,
        )

    async def acreate_experiment(
        self, name="test-experiment", feature_flag=None, started=True, start_days_ago=7, end_days_ahead=7
    ):
        """
        Create an experiment with optional started state.

        Args:
            name: Experiment name
            feature_flag: FeatureFlag instance, creates one if None
            started: Whether experiment has started (start_date is set)
            start_days_ago: Days before now for start_date
            end_days_ahead: Days after now for end_date
        """
        if feature_flag is None:
            feature_flag = await self.acreate_feature_flag(name)

        return await Experiment.objects.acreate(
            name=name,
            team=self.team,
            feature_flag=feature_flag,
            start_date=(datetime(2025, 1, 15, 12, 0, 0) - timedelta(days=start_days_ago) if started else None),
            end_date=(datetime(2025, 1, 15, 12, 0, 0) + timedelta(days=end_days_ahead) if started else None),
        )

    def create_mock_session_recording(self, session_id, distinct_id="user_1"):
        """Create a mock SessionRecording object for testing."""
        recording = SessionRecording(
            session_id=session_id,
            team=self.team,
            distinct_id=distinct_id,
            start_time=datetime(2025, 1, 10, 10, 0, 0),
            duration=300,
        )
        return recording

    async def create_tool(self):
        """Create SessionReplaySummaryTool instance for testing."""
        return await SessionReplaySummaryTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
        )

    @patch("products.experiments.backend.max_tools.list_recordings_from_query")
    async def test_experiment_with_recordings_returns_counts(self, mock_list_recordings):
        """Test successful analysis of experiment with recordings for each variant."""
        experiment = await self.acreate_experiment(name="test-experiment")

        # Mock recordings for each variant
        mock_recordings_control = [self.create_mock_session_recording(f"session_control_{i}") for i in range(50)]
        mock_recordings_test = [self.create_mock_session_recording(f"session_test_{i}") for i in range(75)]

        mock_list_recordings.side_effect = [
            (mock_recordings_control, False, "", None),
            (mock_recordings_test, False, "", None),
        ]

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        # Assert result message
        assert "Session Replay Summary" in result
        assert "test-experiment" in result
        assert "Total recordings: 125" in result
        assert "control: 50" in result
        assert "test: 75" in result
        assert "40.0%" in result
        assert "60.0%" in result
        assert "What would you like to explore?" in result

        # Assert artifact structure
        assert isinstance(artifact, dict)
        assert artifact["experiment_id"] == experiment.id
        assert artifact["experiment_name"] == "test-experiment"
        assert artifact["recording_counts"] == {"control": 50, "test": 75}
        assert artifact["total_recordings"] == 125
        assert artifact["variants"] == ["control", "test"]
        assert "date_range" in artifact
        assert artifact["date_range"]["start"] is not None
        assert artifact["date_range"]["end"] is not None

        assert mock_list_recordings.call_count == 2

    @patch("products.experiments.backend.max_tools.list_recordings_from_query")
    async def test_experiment_with_100_plus_recordings(self, mock_list_recordings):
        """Test that tool correctly handles has_more=True (100+ recordings)."""
        experiment = await self.acreate_experiment()

        mock_recordings = [self.create_mock_session_recording(f"session_{i}") for i in range(100)]

        mock_list_recordings.side_effect = [
            (mock_recordings, True, "", None),
            (mock_recordings, True, "", None),
        ]

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        assert artifact["recording_counts"] == {"control": 100, "test": 100}
        assert artifact["total_recordings"] == 200
        assert "200" in result

    @patch("products.experiments.backend.max_tools.list_recordings_from_query")
    async def test_experiment_with_no_recordings(self, mock_list_recordings):
        """Test error message when no recordings found for any variant."""
        experiment = await self.acreate_experiment()

        mock_list_recordings.side_effect = [
            ([], False, "", None),
            ([], False, "", None),
        ]

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        assert "No session recordings found" in result
        assert "test-experiment" in result
        assert "session replay is enabled" in result

        assert artifact["error"] == "no_recordings"
        assert artifact["experiment_id"] == experiment.id
        assert artifact["recording_counts"] == {"control": 0, "test": 0}

    async def test_experiment_not_found(self):
        """Test error when experiment ID doesn't exist."""
        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=99999)

        assert "Experiment 99999 not found" in result
        assert artifact["error"] == "validation_error"
        assert "not found" in artifact["details"]

    async def test_experiment_not_started(self):
        """Test error when experiment hasn't been started yet."""
        experiment = await self.acreate_experiment(started=False)

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        assert "Experiment has not started yet" in result
        assert "No session replays available" in result
        assert artifact["error"] == "not_started"
        assert artifact["experiment_id"] == experiment.id

    async def test_experiment_with_no_variants(self):
        """Test error when feature flag has no multivariate variants configured."""
        feature_flag = await FeatureFlag.objects.acreate(
            name="No variants flag",
            key="no-variants",
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        experiment = await self.acreate_experiment(name="no-variants-exp", feature_flag=feature_flag, started=True)

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        assert "No variants configured" in result
        assert artifact["error"] == "no_variants"
        assert artifact["experiment_id"] == experiment.id

    @patch("products.experiments.backend.max_tools.capture_exception")
    @patch("products.experiments.backend.max_tools.list_recordings_from_query")
    async def test_recording_query_exception_graceful_handling(self, mock_list_recordings, mock_capture_exception):
        """Test that query exceptions for individual variants are caught and logged."""
        experiment = await self.acreate_experiment()

        mock_recordings = [self.create_mock_session_recording(f"session_{i}") for i in range(25)]
        mock_list_recordings.side_effect = [
            (mock_recordings, False, "", None),
            Exception("ClickHouse connection failed"),
        ]

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        assert artifact["recording_counts"] == {"control": 25, "test": 0}
        assert artifact["total_recordings"] == 25

        assert mock_capture_exception.call_count == 1
        captured_exception = mock_capture_exception.call_args[0][0]
        assert "ClickHouse connection failed" in str(captured_exception)

    @patch("products.experiments.backend.max_tools.list_recordings_from_query")
    async def test_experiment_with_multiple_variants(self, mock_list_recordings):
        """Test experiment with 3+ variants."""
        feature_flag = await self.acreate_feature_flag(
            key="multi-variant", variant_keys=["control", "variant_a", "variant_b"]
        )
        experiment = await self.acreate_experiment(name="multi-variant-exp", feature_flag=feature_flag)

        mock_list_recordings.side_effect = [
            ([self.create_mock_session_recording(f"c_{i}") for i in range(20)], False, "", None),
            ([self.create_mock_session_recording(f"a_{i}") for i in range(30)], False, "", None),
            ([self.create_mock_session_recording(f"b_{i}") for i in range(50)], False, "", None),
        ]

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        assert artifact["variants"] == ["control", "variant_a", "variant_b"]
        assert artifact["recording_counts"]["control"] == 20
        assert artifact["recording_counts"]["variant_a"] == 30
        assert artifact["recording_counts"]["variant_b"] == 50
        assert artifact["total_recordings"] == 100

        assert "control: 20 (20.0%)" in result
        assert "variant_a: 30 (30.0%)" in result
        assert "variant_b: 50 (50.0%)" in result

    async def test_build_experiment_recording_filters(self):
        """Test that recording filters are built correctly for experiment variants."""
        feature_flag = await self.acreate_feature_flag(key="test-flag")
        experiment = await self.acreate_experiment(name="filter-test", feature_flag=feature_flag)

        tool = await self.create_tool()
        filters = tool._build_experiment_recording_filters(experiment, "control")

        # Verify filter structure
        assert "date_from" in filters
        assert "date_to" in filters
        assert "events" in filters
        assert len(filters["events"]) == 1

        # Verify event filter
        event_filter = filters["events"][0]
        assert event_filter["id"] == "$feature_flag_called"
        assert event_filter["type"] == "events"

        # Verify properties
        properties = event_filter["properties"]
        assert len(properties) == 2

        assert properties[0]["key"] == "$feature_flag"
        assert properties[0]["value"] == ["test-flag"]
        assert properties[0]["operator"] == "exact"

        assert properties[1]["key"] == "$feature/test-flag"
        assert properties[1]["value"] == ["control"]
        assert properties[1]["operator"] == "exact"

    @patch("products.experiments.backend.max_tools.list_recordings_from_query")
    async def test_date_range_in_artifact(self, mock_list_recordings):
        """Test that date range is correctly included in artifact."""
        experiment = await self.acreate_experiment(start_days_ago=10, end_days_ahead=5)

        mock_list_recordings.side_effect = [
            ([self.create_mock_session_recording("s1")], False, "", None),
            ([self.create_mock_session_recording("s2")], False, "", None),
        ]

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        assert "date_range" in artifact
        # Django adds timezone info, so check if it starts with the expected date
        assert artifact["date_range"]["start"].startswith("2025-01-05T12:00:00")
        assert artifact["date_range"]["end"].startswith("2025-01-20T12:00:00")

    @patch("products.experiments.backend.max_tools.database_sync_to_async")
    @patch("products.experiments.backend.max_tools.capture_exception")
    async def test_general_exception_handling(self, mock_capture_exception, mock_db_sync):
        """Test that unexpected exceptions in get_experiment are caught and logged."""
        # Make database_sync_to_async raise an exception when fetching experiment
        mock_db_sync.side_effect = RuntimeError("Database connection lost")

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=123)

        assert "Failed to analyze session replays" in result
        assert artifact["error"] == "analysis_failed"
        assert "Database connection lost" in artifact["details"]

        assert mock_capture_exception.call_count == 1
        call_kwargs = mock_capture_exception.call_args[1]
        assert call_kwargs["properties"]["team_id"] == self.team.id
        assert call_kwargs["properties"]["user_id"] == self.user.id
        assert call_kwargs["properties"]["experiment_id"] == 123

    async def test_format_summary_for_user_structure(self):
        """Test the structure and content of formatted user message."""
        tool = await self.create_tool()

        recording_counts = {"control": 100, "test": 150, "variant_c": 50}
        message = tool._format_summary_for_user(
            experiment_name="My Test Experiment", recording_counts=recording_counts, total_recordings=300
        )

        assert "📹 Session Replay Summary for 'My Test Experiment'" in message
        assert "Total recordings: 300" in message
        assert "Recordings by variant:" in message
        assert "control: 100 (33.3%)" in message
        assert "test: 150 (50.0%)" in message
        assert "variant_c: 50 (16.7%)" in message
        assert "To analyze user behavior patterns:" in message
        assert "filter and view specific recordings" in message
        assert "Compare behavior differences" in message
        assert "What would you like to explore?" in message

    async def test_experiment_with_empty_multivariate_variants_list(self):
        """Test handling when multivariate.variants is an empty list."""
        feature_flag = await FeatureFlag.objects.acreate(
            name="Empty variants flag",
            key="empty-variants",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {"variants": []},
            },
            created_by=self.user,
        )

        experiment = await self.acreate_experiment(name="empty-variants-exp", feature_flag=feature_flag, started=True)

        tool = await self.create_tool()
        result, artifact = await tool._arun_impl(experiment_id=experiment.id)

        assert "No variants configured" in result
        assert artifact["error"] == "no_variants"
