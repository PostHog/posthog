import uuid
from pathlib import Path

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models.user import User

from products.enterprise.backend.hogai.videos.session_moments import SessionMomentInput, SessionMomentsLLMAnalyzer


class TestSessionMomentsLLMAnalyzer(BaseTest):
    def setUp(self):
        super().setUp()
        self.session_id = str(uuid.uuid4())
        self.user = User.objects.create_and_join(
            organization=self.organization,
            email="test@posthog.com",
            password=None,
        )

    @pytest.mark.asyncio
    @patch("ee.hogai.videos.session_moments.GeminiVideoUnderstandingProvider")
    @patch("ee.hogai.videos.session_moments.async_connect")
    @patch("ee.hogai.videos.session_moments.ExportedAsset.objects")
    async def test_generate_videos_for_moments_partial_failure_within_threshold(
        self, mock_asset_objects, mock_async_connect, mock_gemini_provider
    ):
        """Test when some videos fail but still meet the minimum ratio"""
        # Setup
        analyzer = SessionMomentsLLMAnalyzer(
            session_id=self.session_id,
            team_id=self.team.id,
            user=self.user,
        )
        moments_input = [
            SessionMomentInput(moment_id=f"event_{i}", timestamp_s=i * 1000, duration_s=5, prompt="Test prompt")
            for i in range(10)
        ]
        # Mock asset creation - all 10 assets created, but some workflows will fail
        mock_assets = [MagicMock(id=i) for i in range(1, 11)]
        mock_asset_objects.acreate = AsyncMock(side_effect=mock_assets)
        # Mock workflow execution - 2 failures
        mock_client = AsyncMock()

        async def workflow_side_effect(*args, **kwargs):
            workflow_id = kwargs.get("id", "")
            # Make event_0 and event_1 fail
            if "event_0" in workflow_id or "event_1" in workflow_id:
                raise Exception("Workflow failed")

        mock_client.execute_workflow = AsyncMock(side_effect=workflow_side_effect)
        mock_async_connect.return_value = mock_client
        # Execute - 80% threshold, 8/10 should pass
        result = await analyzer._generate_videos_for_moments(
            moments_input=moments_input,
            expires_after_days=30,
            failed_moments_min_ratio=0.8,
        )
        # Assert - 8 successful videos
        assert len(result) == 8
        for i in range(2, 10):
            assert f"event_{i}" in result

    @pytest.mark.asyncio
    @patch("ee.hogai.videos.session_moments.GeminiVideoUnderstandingProvider")
    @patch("ee.hogai.videos.session_moments.async_connect")
    @patch("ee.hogai.videos.session_moments.ExportedAsset.objects")
    async def test_generate_videos_for_moments_too_many_failures(
        self, mock_asset_objects, mock_async_connect, mock_gemini_provider
    ):
        """Test when too many videos fail and don't meet the minimum ratio - should cleanup and raise"""
        # Setup
        analyzer = SessionMomentsLLMAnalyzer(
            session_id=self.session_id,
            team_id=self.team.id,
            user=self.user,
        )
        moments_input = [
            SessionMomentInput(moment_id=f"event_{i}", timestamp_s=i * 1000, duration_s=5, prompt="Test prompt")
            for i in range(10)
        ]
        # Mock asset creation
        mock_assets = [MagicMock(id=i) for i in range(1, 11)]
        mock_asset_objects.acreate = AsyncMock(side_effect=mock_assets)
        # Mock workflow execution - 6 failures (only 4 succeed, need 8)
        mock_client = AsyncMock()

        async def workflow_side_effect(*args, **kwargs):
            workflow_id = kwargs.get("id", "")
            # Make 6 events fail
            for i in range(6):
                if f"event_{i}" in workflow_id:
                    raise Exception("Workflow failed")

        mock_client.execute_workflow = AsyncMock(side_effect=workflow_side_effect)
        mock_async_connect.return_value = mock_client
        # Mock delete - filter().adelete() chain
        mock_filter = MagicMock()
        mock_filter.adelete = AsyncMock()
        mock_asset_objects.filter.return_value = mock_filter
        # Execute and expect exception
        with pytest.raises(Exception) as exc_info:
            await analyzer._generate_videos_for_moments(
                moments_input=moments_input,
                expires_after_days=30,
                failed_moments_min_ratio=0.8,  # Need 8, only get 4
            )
        # Assert cleanup was called
        assert "Not enough moments were generated" in str(exc_info.value)
        mock_asset_objects.filter.assert_called_once()
        mock_filter.adelete.assert_called_once()

    def test_get_webm_duration(self):
        """Test extracting duration from a real WEBM video file"""
        # Load the test video file
        video_path = Path(__file__).parent / "assets" / "moment_video.webm"
        with open(video_path, "rb") as f:
            video_bytes = f.read()

        # Extract duration
        duration_s = SessionMomentsLLMAnalyzer._get_webm_duration(video_bytes)

        # Assert it returns 34 seconds
        assert duration_s == 34
