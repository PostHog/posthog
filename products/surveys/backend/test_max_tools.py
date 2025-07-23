"""
Simple async test for the survey creation MaxTool.
"""

import os
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.models import Survey
from posthog.schema import (
    SurveyCreationSchema,
    SurveyQuestionSchema,
    SurveyQuestionType,
    SurveyType,
)
from posthog.test.base import BaseTest

from .max_tools import CreateSurveyTool


class TestSurveyCreatorTool(BaseTest):
    def setUp(self):
        super().setUp()
        # Set mock OpenAI API key for tests
        os.environ["OPENAI_API_KEY"] = "test-api-key"
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def tearDown(self):
        super().tearDown()
        # Clean up the mock API key
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]

    def _setup_tool(self):
        """Helper to create a SurveyCreatorTool instance with mocked dependencies"""
        tool = CreateSurveyTool()

        # Mock the internal state required by MaxTool
        tool._init_run(self._config)

        return tool

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_empty(self):
        """Test getting existing surveys summary when no surveys exist"""
        tool = self._setup_tool()

        summary = await tool._get_existing_surveys_summary()

        assert summary == "No existing surveys"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_with_surveys(self):
        """Test getting existing surveys summary with existing surveys"""
        tool = self._setup_tool()

        # Create a test survey
        await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Existing Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?"}],
            created_by=self.user,
        )

        summary = await tool._get_existing_surveys_summary()

        assert "Existing Survey" in summary
        assert "draft" in summary

    def test_get_team_survey_config(self):
        """Test team survey configuration retrieval"""
        tool = self._setup_tool()

        config = tool._get_team_survey_config(self.team)

        assert "appearance" in config
        assert "default_settings" in config
        assert config["default_settings"]["type"] == "popover"

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success(self, mock_create_survey):
        """Test successful survey creation through _arun_impl"""
        tool = self._setup_tool()

        # Mock the LLM response
        mock_output = SurveyCreationSchema(
            name="Test Survey",
            description="A simple test survey",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="How do you feel about our product?",
                    description="Please share your thoughts",
                    optional=False,
                )
            ],
            should_launch=False,
            enable_partial_responses=True,
        )

        # Set up the mock to return our test data
        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a test survey")

        # Verify success response
        assert "✅ Survey" in content
        assert "created" in content
        assert "successfully" in content
        assert "survey_id" in artifact
        assert "survey_name" in artifact

        # Verify survey was created in database
        survey = await sync_to_async(Survey.objects.get)(id=artifact["survey_id"])
        assert survey.name == "Test Survey"
        assert survey.description == "A simple test survey"
        assert survey.type == "popover"
        assert len(survey.questions) == 1
        assert not survey.archived

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_questions_validation(self, mock_create_survey):
        """Test validation error when no questions are provided"""
        tool = self._setup_tool()

        # Mock LLM response with no questions
        mock_output = SurveyCreationSchema(
            name="Test Survey",
            description="A test survey",
            type=SurveyType.POPOVER,
            questions=[],  # Empty questions list
            should_launch=False,
            enable_partial_responses=True,
        )

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a survey")

        # Verify error response
        assert "❌ Survey must have at least one question" in content
        assert artifact["error"] == "validation_failed"
        assert "No questions provided" in artifact["details"]

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_with_launch(self, mock_create_survey):
        """Test survey creation with immediate launch"""
        tool = self._setup_tool()

        # Mock the LLM response with launch=True
        mock_output = SurveyCreationSchema(
            name="Launch Survey",
            description="A survey to launch",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="Test question?",
                    optional=False,
                )
            ],
            should_launch=True,  # This should launch the survey
            enable_partial_responses=True,
        )

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create and launch a survey")

        # Verify success response with launch message
        assert "✅ Survey" in content
        assert "successfully" in content

        # Verify survey was created and launched
        survey = await sync_to_async(Survey.objects.get)(id=artifact["survey_id"])
        assert survey.start_date is not None  # Should have a start date when launched
