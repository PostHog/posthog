"""
Simple async test for the survey creation MaxTool.
"""

import os

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import django.utils.timezone

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.schema import SurveyCreationSchema, SurveyQuestionSchema, SurveyQuestionType, SurveyType

from posthog.models import FeatureFlag, Survey

from .max_tools import CreateSurveyTool, SurveyAnalysisTool, SurveyLoopNode, SurveyToolkit


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
        tool = CreateSurveyTool(team=self.team, user=self.user)

        # Mock the internal state required by MaxTool
        tool._init_run(self._config)

        return tool

    def test_get_team_survey_config(self):
        """Test team survey configuration function"""
        from products.surveys.backend.max_tools import get_team_survey_config

        config = get_team_survey_config(self.team)

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

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag(self, mock_create_survey):
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

        # Mock the LLM response with linked flag
        mock_output = SurveyCreationSchema(
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

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a survey for users with test-feature flag")

        # Verify success response
        assert "✅ Survey" in content
        assert "successfully" in content

        # Verify survey was created with feature flag
        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        assert survey.name == "Feature Flag Survey"
        assert survey.linked_flag_id == flag.id

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag_variant(self, mock_create_survey):
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

        # Mock the LLM response with linked flag and variant
        mock_output = SurveyCreationSchema(
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

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a survey for users in control variant of ab-test-feature")

        # Verify success response
        assert "✅ Survey" in content
        assert "successfully" in content

        # Verify survey was created with feature flag and variant
        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        assert survey.name == "A/B Test Control Survey"
        assert survey.linked_flag_id == flag.id
        assert survey.conditions["linkedFlagVariant"] == "control"

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag_variant_any(self, mock_create_survey):
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

        # Mock the LLM response with linked flag and 'any' variant
        mock_output = SurveyCreationSchema(
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

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a survey for all users with multivariate-feature enabled")

        # Verify success response
        assert "✅ Survey" in content
        assert "successfully" in content

        # Verify survey was created with feature flag and 'any' variant
        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        assert survey.name == "All Variants Survey"
        assert survey.linked_flag_id == flag.id
        assert survey.conditions["linkedFlagVariant"] == "any"


class TestSurveyLoopNode(BaseTest):
    def setUp(self):
        super().setUp()

    def _setup_node(self):
        """Helper to create a TestSurveyLoopNode instance"""
        return SurveyLoopNode(team=self.team, user=self.user, toolkit_class=SurveyToolkit)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_empty(self):
        """Test getting existing surveys summary when no surveys exist"""
        node = self._setup_node()

        summary = await node._get_existing_surveys_summary()

        assert summary == "No existing surveys"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_with_surveys(self):
        """Test getting existing surveys summary with existing surveys"""
        node = self._setup_node()

        # Create test surveys
        await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Draft Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?"}],
            created_by=self.user,
        )

        # Create an active survey (with start_date but no end_date)
        await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Active Survey",
            type="email",
            questions=[{"type": "rating", "question": "How satisfied?", "scale": 5}],
            created_by=self.user,
            start_date=django.utils.timezone.now(),
        )

        summary = await node._get_existing_surveys_summary()

        # Verify both surveys are included
        assert "Draft Survey" in summary
        assert "Active Survey" in summary
        assert "draft" in summary
        assert "active" in summary
        assert "popover" in summary
        assert "email" in summary

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_excludes_archived(self):
        """Test that archived surveys are excluded from the summary"""
        node = self._setup_node()

        # Create a regular survey
        await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Regular Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?"}],
            created_by=self.user,
        )

        # Create an archived survey (should be excluded)
        await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Archived Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?"}],
            created_by=self.user,
            archived=True,
        )

        summary = await node._get_existing_surveys_summary()

        # Only the non-archived survey should be included
        assert "Regular Survey" in summary
        assert "Archived Survey" not in summary

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_limits_to_five(self):
        """Test that the summary is limited to 5 surveys"""
        node = self._setup_node()

        # Create 6 surveys
        survey_names = []
        for i in range(6):
            name = f"Survey {i+1}"
            survey_names.append(name)
            await sync_to_async(Survey.objects.create)(
                team=self.team,
                name=name,
                type="popover",
                questions=[{"type": "open", "question": "Test?"}],
                created_by=self.user,
            )

        summary = await node._get_existing_surveys_summary()

        # Count the number of survey entries (lines starting with "- '")
        summary_lines = [line for line in summary.split("\n") if line.strip().startswith("- '")]
        assert len(summary_lines) == 5  # Should be limited to 5

        # Verify it contains survey information
        assert "Survey" in summary
        assert "draft" in summary


class TestSurveyAnalysisTool(BaseTest):
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

    def _setup_tool_with_context(self, context=None):
        """Helper to create a SurveyAnalysisTool instance with context"""
        tool = SurveyAnalysisTool(team=self.team, user=self.user)
        tool._init_run(self._config)

        if context:
            tool._context = context

        return tool

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_extract_open_ended_responses_empty_context(self):
        """Test _extract_open_ended_responses with empty context"""
        tool = self._setup_tool_with_context()

        # Create a mock survey
        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?", "id": "q1"}],
            created_by=self.user,
        )

        responses = await tool._extract_open_ended_responses(survey)

        assert responses == []

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_extract_open_ended_responses_null_context(self):
        """Test _extract_open_ended_responses with null context"""
        tool = self._setup_tool_with_context(context=None)

        # Create a mock survey
        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?", "id": "q1"}],
            created_by=self.user,
        )

        responses = await tool._extract_open_ended_responses(survey)

        assert responses == []

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_extract_open_ended_responses_no_formatted_responses(self):
        """Test _extract_open_ended_responses with context but no formatted_responses"""
        context = {"survey_id": "test-id", "survey_name": "Test Survey"}
        tool = self._setup_tool_with_context(context)

        # Create a mock survey
        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?", "id": "q1"}],
            created_by=self.user,
        )

        responses = await tool._extract_open_ended_responses(survey)

        assert responses == []

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_extract_open_ended_responses_valid_data(self):
        """Test _extract_open_ended_responses with valid data"""
        context = {
            "survey_id": "test-id",
            "survey_name": "Test Survey",
            "formatted_responses": [
                {
                    "questionName": "What do you think?",
                    "questionId": "q1",
                    "responses": [
                        {
                            "responseText": "Great product",
                            "userDistinctId": "user1",
                            "email": "user1@test.com",
                            "isOpenEnded": True,
                        },
                        {
                            "responseText": "Could be better",
                            "userDistinctId": "user2",
                            "email": None,
                            "isOpenEnded": True,
                        },
                    ],
                },
                {
                    "questionName": "Any suggestions?",
                    "questionId": "q2",
                    "responses": [
                        {
                            "responseText": "Add dark mode",
                            "userDistinctId": "user3",
                            "email": "user3@test.com",
                            "isOpenEnded": True,
                        },
                    ],
                },
            ],
        }
        tool = self._setup_tool_with_context(context)

        # Create a mock survey for the method
        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "What do you think?", "id": "q1"},
                {"type": "open", "question": "Any suggestions?", "id": "q2"},
            ],
            created_by=self.user,
        )

        responses = await tool._extract_open_ended_responses(survey)

        assert len(responses) == 2
        assert responses[0]["questionName"] == "What do you think?"
        assert len(responses[0]["responses"]) == 2
        assert responses[1]["questionName"] == "Any suggestions?"
        assert len(responses[1]["responses"]) == 1

    @patch("products.surveys.backend.max_tools.MaxChatOpenAI")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_analyze_responses_success(self, mock_chat_openai):
        """Test successful response analysis with mocked LLM"""
        # Mock LLM response
        mock_response = {
            "themes": ["User Interface", "Performance"],
            "sentiment": "constructive",
            "insights": ["Users appreciate the design but want improvements"],
            "recommendations": ["Implement dark mode", "Optimize loading speed"],
            "response_count": 3,
        }
        mock_chat_openai.return_value.invoke.return_value.content = f"```json\n{mock_response}\n```"

        tool = self._setup_tool_with_context()
        responses_data = [
            {
                "questionName": "What do you think?",
                "questionId": "q1",
                "responses": [
                    {
                        "responseText": "Great UI design",
                        "userDistinctId": "user1",
                        "email": "user1@test.com",
                        "isOpenEnded": True,
                    },
                    {"responseText": "Slow loading", "userDistinctId": "user2", "email": None, "isOpenEnded": True},
                    {
                        "responseText": "Add dark mode",
                        "userDistinctId": "user3",
                        "email": "user3@test.com",
                        "isOpenEnded": True,
                    },
                ],
            }
        ]

        result = await tool._analyze_responses(responses_data)

        assert result == mock_response
        mock_chat_openai.return_value.invoke.assert_called_once()

    @patch("products.surveys.backend.max_tools.MaxChatOpenAI")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_analyze_responses_json_parsing_error(self, mock_chat_openai):
        """Test LLM response with malformed JSON"""
        # Mock malformed JSON response
        mock_chat_openai.return_value.invoke.return_value.content = "This is not JSON"

        tool = self._setup_tool_with_context()
        responses_data = [
            {"questionName": "What do you think?", "responses": [{"responseText": "Good", "userDistinctId": "user1"}]}
        ]

        result = await tool._analyze_responses(responses_data)

        # Should return error structure for JSON parsing failure
        assert "error" in result
        assert "JSON parsing failed" in result["error"]

    @patch("products.surveys.backend.max_tools.MaxChatOpenAI")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_analyze_responses_llm_error(self, mock_chat_openai):
        """Test LLM invocation error handling"""
        # Mock LLM error
        mock_chat_openai.return_value.invoke.side_effect = Exception("LLM API error")

        tool = self._setup_tool_with_context()
        responses_data = [
            {"questionName": "What do you think?", "responses": [{"responseText": "Good", "userDistinctId": "user1"}]}
        ]

        result = await tool._analyze_responses(responses_data)

        # Should return error structure for LLM failure
        assert "error" in result
        assert "LLM API error" in result["error"]

    def test_format_analysis_for_user_success(self):
        """Test successful analysis formatting"""
        analysis = {
            "themes": ["User Interface", "Performance"],
            "sentiment": "constructive feedback",
            "insights": ["Users love the design but want faster loading"],
            "recommendations": ["Implement caching", "Optimize images"],
            "response_count": 5,
        }

        tool = self._setup_tool_with_context()
        formatted = tool._format_analysis_for_user(analysis, "Test Product Survey")

        assert "✅ **Survey Analysis: 'Test Product Survey'**" in formatted
        assert "🎯 **Key Themes Identified:**" in formatted
        assert "User Interface" in formatted
        assert "Performance" in formatted
        assert "💭 **Overall Sentiment:**" in formatted
        assert "constructive feedback" in formatted
        assert "💡 **Key Insights:**" in formatted
        assert "Users love the design" in formatted
        assert "🚀 **Recommendations:**" in formatted
        assert "Implement caching" in formatted
        assert "📈 **Analysis Summary:**" in formatted
        assert "5 responses" in formatted

    def test_format_analysis_for_user_test_data_detected(self):
        """Test analysis formatting when test data is detected"""
        analysis = {
            "themes": ["Test Data"],
            "sentiment": "test responses detected",
            "insights": ["Most responses appear to be test data"],
            "recommendations": ["Collect genuine user feedback"],
            "response_count": 10,
            "test_data_detected": True,
        }

        tool = self._setup_tool_with_context()
        formatted = tool._format_analysis_for_user(analysis, "Test Survey")

        assert "⚠️ **Test Data Detected**" in formatted
        assert "appears to contain mostly test" in formatted
        assert "genuine user responses" in formatted

    def test_format_analysis_for_user_error(self):
        """Test analysis formatting with error"""
        analysis = {"error": "LLM analysis failed due to API timeout"}

        tool = self._setup_tool_with_context()
        formatted = tool._format_analysis_for_user(analysis, "Test Survey")

        assert "❌ Analysis failed" in formatted
        assert "LLM analysis failed due to API timeout" in formatted

    @patch("products.surveys.backend.max_tools.MaxChatOpenAI")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_responses(self, mock_chat_openai):
        """Test _arun_impl with no open-ended responses"""
        context = {"survey_id": "test-id", "survey_name": "Test Survey", "formatted_responses": []}
        tool = self._setup_tool_with_context(context)

        user_message, artifact = await tool._arun_impl()

        assert "no open-ended responses" in user_message.lower()
        assert not artifact["success"]
        assert "no_responses" in artifact["error"]
        # LLM should not be called
        mock_chat_openai.return_value.invoke.assert_not_called()

    @patch("products.surveys.backend.max_tools.MaxChatOpenAI")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success_flow(self, mock_chat_openai):
        """Test complete _arun_impl success flow"""
        # Mock LLM response
        mock_analysis = {
            "themes": ["Product Feedback", "Feature Requests"],
            "sentiment": "positive and constructive",
            "insights": ["Users appreciate current features but want more customization"],
            "recommendations": ["Add theme customization", "Improve mobile experience"],
            "response_count": 3,
        }
        mock_chat_openai.return_value.invoke.return_value.content = f"```json\n{mock_analysis}\n```"

        context = {
            "survey_id": "test-id",
            "survey_name": "Product Feedback Survey",
            "formatted_responses": [
                {
                    "questionName": "How can we improve?",
                    "questionId": "q1",
                    "responses": [
                        {
                            "responseText": "Love the app but need dark mode",
                            "userDistinctId": "user1",
                            "email": "user1@test.com",
                            "isOpenEnded": True,
                        },
                        {
                            "responseText": "Mobile version is slow",
                            "userDistinctId": "user2",
                            "email": None,
                            "isOpenEnded": True,
                        },
                        {
                            "responseText": "Great overall experience",
                            "userDistinctId": "user3",
                            "email": "user3@test.com",
                            "isOpenEnded": True,
                        },
                    ],
                }
            ],
        }
        tool = self._setup_tool_with_context(context)

        user_message, artifact = await tool._arun_impl()

        # Verify user message contains formatted analysis
        assert "📊 Survey Response Analysis" in user_message
        assert "Product Feedback" in user_message
        assert "Feature Requests" in user_message
        assert "positive and constructive" in user_message

        # Verify artifact structure
        assert artifact["success"]
        assert artifact["survey_id"] == "test-id"
        assert artifact["survey_name"] == "Product Feedback Survey"
        assert artifact["analysis"] == mock_analysis

        # Verify LLM was called
        mock_chat_openai.return_value.invoke.assert_called_once()

    @patch("products.surveys.backend.max_tools.MaxChatOpenAI")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_handles_llm_failure(self, mock_chat_openai):
        """Test _arun_impl handles LLM failure gracefully"""
        # Mock LLM failure
        mock_chat_openai.return_value.invoke.side_effect = Exception("OpenAI API timeout")

        context = {
            "survey_id": "test-id",
            "survey_name": "Test Survey",
            "formatted_responses": [
                {"questionName": "Feedback?", "responses": [{"responseText": "Good", "userDistinctId": "user1"}]}
            ],
        }
        tool = self._setup_tool_with_context(context)

        user_message, artifact = await tool._arun_impl()

        # Should handle error gracefully
        assert "❌ Analysis failed" in user_message
        assert "OpenAI API timeout" in user_message
        assert not artifact["success"]
        assert artifact["error"] == "analysis_failed"
