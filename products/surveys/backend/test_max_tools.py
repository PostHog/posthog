"""
Simple async test for the survey creation MaxTool.
"""

import os

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    SurveyCreationSchema,
    SurveyDisplayConditionsSchema,
    SurveyMatchType,
    SurveyQuestionSchema,
    SurveyQuestionType,
    SurveyType,
)

from posthog.models import FeatureFlag, Insight, Survey

from products.surveys.backend.max_tools import SurveyUpdateSchema

from .max_tools import CreateSurveyTool, EditSurveyTool, SurveyAnalysisTool


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
        tool = CreateSurveyTool(team=self.team, user=self.user, config=self._config)
        return tool

    def test_get_team_survey_config(self):
        """Test team survey configuration function"""
        from products.surveys.backend.max_tools import get_team_survey_config

        config = get_team_survey_config(self.team)

        assert "appearance" in config
        assert "default_settings" in config
        assert config["default_settings"]["type"] == "popover"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success(self):
        """Test successful survey creation through _arun_impl"""
        tool = self._setup_tool()

        # Create the survey schema directly (no more LLM call)
        survey_schema = SurveyCreationSchema(
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

        # Run the method with the schema directly
        content, artifact = await tool._arun_impl(survey=survey_schema)

        # Verify success response
        assert "Survey" in content
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

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_questions_validation(self):
        """Test validation error when no questions are provided"""
        tool = self._setup_tool()

        # Create schema with no questions
        survey_schema = SurveyCreationSchema(
            name="Test Survey",
            description="A test survey",
            type=SurveyType.POPOVER,
            questions=[],  # Empty questions list
            should_launch=False,
            enable_partial_responses=True,
        )

        # Run the method
        content, artifact = await tool._arun_impl(survey=survey_schema)

        # Verify error response
        assert "Survey must have at least one question" in content
        assert artifact["error"] == "validation_failed"
        assert "No questions provided" in artifact["error_message"]

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_with_launch(self):
        """Test survey creation with immediate launch"""
        tool = self._setup_tool()

        # Create schema with launch=True
        survey_schema = SurveyCreationSchema(
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

        # Run the method
        content, artifact = await tool._arun_impl(survey=survey_schema)

        # Verify success response with launch message
        assert "Survey" in content
        assert "successfully" in content

        # Verify survey was created and launched
        survey = await sync_to_async(Survey.objects.get)(id=artifact["survey_id"])
        assert survey.start_date is not None  # Should have a start date when launched

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag(self):
        """Test creating a survey with a linked feature flag"""
        tool = self._setup_tool()

        # Create a test feature flag
        flag = await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="test-feature",
            name="Test Feature",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create schema with linked flag
        survey_schema = SurveyCreationSchema(
            name="Feature Flag Survey",
            description="Survey for users with test feature",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.RATING,
                    question="How satisfied are you with the new feature?",
                    scale=5,
                    optional=False,
                )
            ],
            linked_flag_id=flag.id,
            should_launch=False,
            enable_partial_responses=True,
        )

        # Run the method
        content, artifact = await tool._arun_impl(survey=survey_schema)

        # Verify success response
        assert "Survey" in content
        assert "successfully" in content

        # Verify survey was created with feature flag
        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        assert survey.name == "Feature Flag Survey"
        assert survey.linked_flag_id == flag.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag_variant(self):
        """Test creating a survey with a feature flag variant"""
        tool = self._setup_tool()

        # Create a multivariate feature flag
        flag = await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="ab-test-feature",
            name="A/B Test Feature",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "treatment", "rollout_percentage": 50},
                    ]
                },
            },
        )

        # Create schema with linked flag and variant
        survey_schema = SurveyCreationSchema(
            name="A/B Test Control Survey",
            description="Survey for users in control variant",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.SINGLE_CHOICE,
                    question="Which version do you prefer?",
                    choices=["Version A", "Version B", "No preference"],
                    optional=False,
                )
            ],
            linked_flag_id=flag.id,
            conditions={"linkedFlagVariant": "control"},
            should_launch=False,
            enable_partial_responses=True,
        )

        # Run the method
        content, artifact = await tool._arun_impl(survey=survey_schema)

        # Verify success response
        assert "Survey" in content
        assert "successfully" in content

        # Verify survey was created with feature flag and variant
        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        assert survey.name == "A/B Test Control Survey"
        assert survey.linked_flag_id == flag.id
        assert survey.conditions["linkedFlagVariant"] == "control"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag_variant_any(self):
        """Test creating a survey with linkedFlagVariant set to 'any'"""
        tool = self._setup_tool()

        # Create a multivariate feature flag
        flag = await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="multivariate-feature",
            name="Multivariate Feature",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "variant-a", "rollout_percentage": 33},
                        {"key": "variant-b", "rollout_percentage": 33},
                        {"key": "variant-c", "rollout_percentage": 34},
                    ]
                },
            },
        )

        # Create schema with linked flag and 'any' variant
        survey_schema = SurveyCreationSchema(
            name="All Variants Survey",
            description="Survey for all users with the feature enabled",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="How is the new feature working for you?",
                    optional=False,
                )
            ],
            linked_flag_id=flag.id,
            conditions={"linkedFlagVariant": "any"},
            should_launch=False,
            enable_partial_responses=True,
        )

        # Run the method
        content, artifact = await tool._arun_impl(survey=survey_schema)

        # Verify success response
        assert "Survey" in content
        assert "successfully" in content

        # Verify survey was created with feature flag and 'any' variant
        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        assert survey.name == "All Variants Survey"
        assert survey.linked_flag_id == flag.id
        assert survey.conditions["linkedFlagVariant"] == "any"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_with_launch(self):
        """Test that creating a survey with should_launch=True is a dangerous operation"""
        tool = self._setup_tool()

        survey_schema = SurveyCreationSchema(
            name="Test Survey",
            description="A test survey",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="Test?",
                    optional=False,
                )
            ],
            should_launch=True,
        )

        is_dangerous = await tool.is_dangerous_operation(survey=survey_schema)
        assert is_dangerous is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_without_launch(self):
        """Test that creating a survey without launching is NOT a dangerous operation"""
        tool = self._setup_tool()

        survey_schema = SurveyCreationSchema(
            name="Test Survey",
            description="A test survey",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="Test?",
                    optional=False,
                )
            ],
            should_launch=False,
        )

        is_dangerous = await tool.is_dangerous_operation(survey=survey_schema)
        assert is_dangerous is False

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_format_dangerous_operation_preview(self):
        """Test the dangerous operation preview message for survey creation"""
        tool = self._setup_tool()

        survey_schema = SurveyCreationSchema(
            name="NPS Survey",
            description="A test survey",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.RATING,
                    question="How likely are you to recommend us?",
                    scale=10,
                ),
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="Why?",
                    optional=True,
                ),
            ],
            should_launch=True,
        )

        preview = await tool.format_dangerous_operation_preview(survey=survey_schema)

        assert "Create and launch" in preview
        assert "NPS Survey" in preview
        assert "2 question(s)" in preview
        assert "start collecting responses" in preview

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_linked_insight(self):
        """Test creating a survey with a linked insight (from funnel cross-sell)"""
        # Create a test insight
        insight = await sync_to_async(Insight.objects.create)(
            team=self.team,
            name="Test Funnel",
            created_by=self.user,
        )

        # Create tool with insight_id in context
        tool = CreateSurveyTool(
            team=self.team,
            user=self.user,
            config={
                **self._config,
                "configurable": {
                    **self._config.get("configurable", {}),
                    "contextual_tools": {"create_survey": {"insight_id": insight.id}},
                },
            },
        )

        # Create schema
        survey_schema = SurveyCreationSchema(
            name="Funnel Survey",
            description="Survey for funnel conversion",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="Why didn't you complete the checkout?",
                    optional=False,
                )
            ],
            should_launch=False,
            enable_partial_responses=True,
        )

        # Run the method
        content, artifact = await tool._arun_impl(survey=survey_schema)

        # Verify success response
        assert "Survey" in content
        assert "successfully" in content

        # Verify survey was created with linked insight
        survey = await sync_to_async(Survey.objects.select_related("linked_insight").get)(id=artifact["survey_id"])
        assert survey.name == "Funnel Survey"
        assert survey.linked_insight_id == insight.id


class TestSurveyAnalysisTool(BaseTest):
    def setUp(self):
        super().setUp()
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def _setup_tool(self):
        """Helper to create a SurveyAnalysisTool instance"""
        tool = SurveyAnalysisTool(
            team=self.team,
            user=self.user,
            config=self._config,
        )
        return tool

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_survey_id(self):
        """Test _arun_impl with no survey_id provided"""
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl()

        assert "no survey id provided" in content.lower()
        assert artifact["error"] == "no_survey_id"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_survey_not_found(self):
        """Test _arun_impl with invalid survey_id"""
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(survey_id="00000000-0000-0000-0000-000000000000")

        assert "not found" in content.lower()
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    @patch("products.surveys.backend.max_tools.fetch_responses")
    async def test_arun_impl_no_responses(self, mock_fetch):
        """Test _arun_impl with survey but no open-ended responses"""
        mock_fetch.return_value = []

        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?", "id": "q1"}],
            created_by=self.user,
        )
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(survey_id=str(survey.id))

        assert "no open-ended responses" in content.lower()
        assert artifact["response_count"] == 0

    @pytest.mark.django_db
    @pytest.mark.asyncio
    @patch("products.surveys.backend.max_tools.fetch_responses")
    async def test_arun_impl_returns_formatted_responses(self, mock_fetch):
        """Test _arun_impl returns formatted responses for agent analysis"""
        mock_fetch.return_value = [
            "Love the app but need dark mode",
            "Mobile version is slow",
            "Great overall experience",
        ]

        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Product Feedback Survey",
            type="popover",
            questions=[{"type": "open", "question": "How can we improve?", "id": "q1"}],
            created_by=self.user,
        )
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(survey_id=str(survey.id))

        # Verify content includes survey name
        assert "Product Feedback Survey" in content
        # Verify content includes response count
        assert "3" in content
        # Verify content includes the question
        assert "How can we improve?" in content
        # Verify content includes responses
        assert "Love the app but need dark mode" in content
        assert "Mobile version is slow" in content
        assert "Great overall experience" in content
        # Verify content includes analysis instructions
        assert "themes" in content.lower()
        assert "sentiment" in content.lower()
        assert "insights" in content.lower()
        assert "recommendations" in content.lower()

        # Verify artifact structure
        assert artifact["survey_id"] == str(survey.id)
        assert artifact["survey_name"] == "Product Feedback Survey"
        assert artifact["response_count"] == 3

    @pytest.mark.django_db
    @pytest.mark.asyncio
    @patch("products.surveys.backend.max_tools.fetch_responses")
    async def test_arun_impl_multiple_questions(self, mock_fetch):
        """Test _arun_impl with multiple questions"""
        # Return different responses for each call (one per question)
        mock_fetch.side_effect = [
            ["Great UI", "Fast performance"],  # First question
            ["Add dark mode"],  # Second question
        ]

        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Multi-Question Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "What do you like?", "id": "q1"},
                {"type": "open", "question": "What could be better?", "id": "q2"},
            ],
            created_by=self.user,
        )
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(survey_id=str(survey.id))

        # Verify both questions are included
        assert "What do you like?" in content
        assert "What could be better?" in content
        # Verify all responses are included
        assert "Great UI" in content
        assert "Fast performance" in content
        assert "Add dark mode" in content
        # Verify total response count
        assert artifact["response_count"] == 3

    def test_format_responses_for_analysis(self):
        """Test _format_responses_for_analysis formats data correctly"""
        from posthog.schema import SurveyAnalysisQuestionGroup, SurveyAnalysisResponseItem

        tool = self._setup_tool()

        question_groups = [
            SurveyAnalysisQuestionGroup(
                questionName="What do you think?",
                questionId="q1",
                responses=[
                    SurveyAnalysisResponseItem(
                        responseText="Great product",
                        isOpenEnded=True,
                    ),
                    SurveyAnalysisResponseItem(
                        responseText="Could be better",
                        isOpenEnded=True,
                    ),
                ],
            ),
        ]

        formatted = tool._format_responses_for_analysis(question_groups)

        assert 'Question: "What do you think?"' in formatted
        assert '- "Great product"' in formatted
        assert '- "Could be better"' in formatted

    def test_format_responses_for_analysis_empty_responses(self):
        """Test _format_responses_for_analysis handles empty responses"""
        from posthog.schema import SurveyAnalysisQuestionGroup

        tool = self._setup_tool()

        question_groups = [
            SurveyAnalysisQuestionGroup(
                questionName="Empty question",
                questionId="q1",
                responses=[],
            ),
        ]

        formatted = tool._format_responses_for_analysis(question_groups)

        assert 'Question: "Empty question"' in formatted
        assert "Responses: (none)" in formatted


class TestEditSurveyTool(BaseTest):
    def setUp(self):
        super().setUp()
        os.environ["OPENAI_API_KEY"] = "test-api-key"
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def tearDown(self):
        super().tearDown()
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]

    def _setup_tool(self):
        tool = EditSurveyTool(team=self.team, user=self.user, config=self._config)
        return tool

    async def _create_test_survey(self, **kwargs):
        defaults = {
            "team": self.team,
            "name": "Test Survey",
            "description": "A test survey",
            "type": "popover",
            "questions": [{"type": "open", "question": "Test question?", "id": "q1"}],
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return await sync_to_async(Survey.objects.create)(**defaults)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_name_description(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        updates = SurveyUpdateSchema(name="Updated Name", description="Updated description")
        content, artifact = await tool._arun_impl(survey_id=str(survey.id), updates=updates)

        assert "Updated Name" in content
        assert "updated_fields" in artifact
        assert "name" in artifact["updated_fields"]
        assert "description" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.name == "Updated Name"
        assert updated_survey.description == "Updated description"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_questions(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        new_questions = [
            SurveyQuestionSchema(type=SurveyQuestionType.RATING, question="New rating question?", scale=5),
            SurveyQuestionSchema(type=SurveyQuestionType.OPEN, question="Follow-up?", optional=True),
        ]
        updates = SurveyUpdateSchema(questions=new_questions)
        content, artifact = await tool._arun_impl(survey_id=str(survey.id), updates=updates)

        assert "updated successfully" in content
        assert "questions" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.questions is not None
        assert len(updated_survey.questions) == 2
        assert updated_survey.questions[0]["type"] == "rating"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_conditions(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        conditions = SurveyDisplayConditionsSchema(url="/dashboard", urlMatchType=SurveyMatchType.ICONTAINS)
        updates = SurveyUpdateSchema(conditions=conditions)
        content, artifact = await tool._arun_impl(survey_id=str(survey.id), updates=updates)

        assert "updated successfully" in content
        assert "conditions" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.conditions is not None
        assert updated_survey.conditions["url"] == "/dashboard"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_launch(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        updates = SurveyUpdateSchema(start_date="now")
        content, artifact = await tool._arun_impl(survey_id=str(survey.id), updates=updates)

        assert "launched" in content
        assert "start_date" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.start_date is not None

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_stop(self):
        import django.utils.timezone

        tool = self._setup_tool()
        survey = await self._create_test_survey(start_date=django.utils.timezone.now())

        updates = SurveyUpdateSchema(end_date="now")
        content, artifact = await tool._arun_impl(survey_id=str(survey.id), updates=updates)

        assert "stopped" in content
        assert "end_date" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.end_date is not None

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_archive(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        updates = SurveyUpdateSchema(archived=True)
        content, artifact = await tool._arun_impl(survey_id=str(survey.id), updates=updates)

        assert "archived" in content
        assert "archived" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.archived is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_not_found(self):
        tool = self._setup_tool()

        updates = SurveyUpdateSchema(name="New Name")
        content, artifact = await tool._arun_impl(survey_id="00000000-0000-0000-0000-000000000000", updates=updates)

        assert "not found" in content.lower()
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_wrong_team(self):
        from posthog.models import Organization, Team

        other_org = await sync_to_async(Organization.objects.create)(name="Other Org")
        other_team = await sync_to_async(Team.objects.create)(organization=other_org, name="Other Team")
        other_survey = await sync_to_async(Survey.objects.create)(
            team=other_team,
            name="Other Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?"}],
            created_by=self.user,
        )

        tool = self._setup_tool()
        updates = SurveyUpdateSchema(name="Hacked Name")
        content, artifact = await tool._arun_impl(survey_id=str(other_survey.id), updates=updates)

        assert "not found" in content.lower()
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_no_updates(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        updates = SurveyUpdateSchema()
        content, artifact = await tool._arun_impl(survey_id=str(survey.id), updates=updates)

        assert "no updates" in content.lower()
        assert artifact["error"] == "no_updates"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_stop_and_archive(self):
        import django.utils.timezone

        tool = self._setup_tool()
        survey = await self._create_test_survey(start_date=django.utils.timezone.now())

        updates = SurveyUpdateSchema(end_date="now", archived=True)
        content, artifact = await tool._arun_impl(survey_id=str(survey.id), updates=updates)

        assert "stopped" in content
        assert "archived" in content
        assert "end_date" in artifact["updated_fields"]
        assert "archived" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.end_date is not None
        assert updated_survey.archived is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_launch(self):
        """Test that launching a survey is a dangerous operation"""
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        updates = SurveyUpdateSchema(start_date="now")
        is_dangerous = await tool.is_dangerous_operation(survey_id=str(survey.id), updates=updates)
        assert is_dangerous is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_stop(self):
        """Test that stopping a survey is a dangerous operation"""
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        updates = SurveyUpdateSchema(end_date="now")
        is_dangerous = await tool.is_dangerous_operation(survey_id=str(survey.id), updates=updates)
        assert is_dangerous is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_archive(self):
        """Test that archiving a survey is a dangerous operation"""
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        updates = SurveyUpdateSchema(archived=True)
        is_dangerous = await tool.is_dangerous_operation(survey_id=str(survey.id), updates=updates)
        assert is_dangerous is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_regular_update(self):
        """Test that regular updates are NOT dangerous operations"""
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        updates = SurveyUpdateSchema(name="New Name", description="New description")
        is_dangerous = await tool.is_dangerous_operation(survey_id=str(survey.id), updates=updates)
        assert is_dangerous is False

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_format_dangerous_operation_preview_launch(self):
        """Test dangerous operation preview for launching a survey"""
        tool = self._setup_tool()
        survey = await self._create_test_survey(name="My NPS Survey")

        updates = SurveyUpdateSchema(start_date="now")
        preview = await tool.format_dangerous_operation_preview(survey_id=str(survey.id), updates=updates)

        assert "Launch" in preview
        assert "My NPS Survey" in preview
        assert "start collecting responses" in preview

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_format_dangerous_operation_preview_multiple_actions(self):
        """Test dangerous operation preview with multiple actions"""
        tool = self._setup_tool()
        survey = await self._create_test_survey(name="Survey to Archive")

        updates = SurveyUpdateSchema(end_date="now", archived=True)
        preview = await tool.format_dangerous_operation_preview(survey_id=str(survey.id), updates=updates)

        assert "Stop" in preview
        assert "Archive" in preview
        assert "Survey to Archive" in preview
