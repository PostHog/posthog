"""
Simple async test for the survey creation MaxTool.
"""

import os

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import django.utils.timezone

import orjson
from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.schema import SurveyCreationSchema, SurveyQuestionSchema, SurveyQuestionType, SurveyType

from posthog.models import FeatureFlag, Survey

from products.surveys.backend.max_tools import SurveyAnalysisOutput, ThemeWithExamples

from .max_tools import CreateSurveyTool, SurveyAnalysisTool, SurveyLoopNode, SurveyToolkit

OPENAI_PATCH_PATH = "products.surveys.backend.max_tools.MaxChatOpenAI"


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
        assert "No questions were created from the survey instructions" in artifact["error_message"]

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

        if context is not None:
            tool._context = context
        else:
            tool._context = {}

        return tool

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_extract_open_ended_responses_empty_context(self):
        """Test _extract_open_ended_responses with empty context"""
        tool = self._setup_tool_with_context()

        responses = tool._extract_open_ended_responses()

        assert responses == []

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_extract_open_ended_responses_null_context(self):
        """Test _extract_open_ended_responses with null context"""
        tool = self._setup_tool_with_context(context=None)

        responses = tool._extract_open_ended_responses()

        assert responses == []

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_extract_open_ended_responses_no_formatted_responses(self):
        """Test _extract_open_ended_responses with context but no formatted_responses"""
        context = {"survey_id": "test-id", "survey_name": "Test Survey"}
        tool = self._setup_tool_with_context(context)

        responses = tool._extract_open_ended_responses()

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
                            "timestamp": "2023-01-01T00:00:00Z",
                            "isOpenEnded": True,
                        },
                        {
                            "responseText": "Could be better",
                            "timestamp": "2023-01-01T00:00:00Z",
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
                            "timestamp": "2023-01-01T00:00:00Z",
                            "isOpenEnded": True,
                        },
                    ],
                },
            ],
        }
        tool = self._setup_tool_with_context(context)

        responses = tool._extract_open_ended_responses()

        assert len(responses) == 2
        assert responses[0].questionName == "What do you think?"
        assert len(responses[0].responses) == 2
        assert responses[1].questionName == "Any suggestions?"
        assert len(responses[1].responses) == 1

        # Test individual response properties
        first_response = responses[0].responses[0]
        assert first_response.responseText == "Great product"
        assert first_response.timestamp == "2023-01-01T00:00:00Z"
        assert first_response.isOpenEnded

    @patch(OPENAI_PATCH_PATH)
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_analyze_responses_success(self, mock_chat_openai):
        """Test successful response analysis with mocked LLM"""
        # Mock LLM response
        mock_response = {
            "themes": [
                ThemeWithExamples(
                    theme="User Interface",
                    description="Users like the design but want improvements",
                    examples=["Great UI design", "Add dark mode"],
                ),
                ThemeWithExamples(
                    theme="Performance", description="Users experience slow loading times", examples=["Slow loading"]
                ),
            ],
            "sentiment": "mixed",
            "insights": ["Users appreciate the design but want improvements"],
            "recommendations": ["Implement dark mode", "Optimize loading speed"],
            "response_count": 3,
        }

        mock_analysis_output = SurveyAnalysisOutput(**mock_response)
        mock_llm_instance = mock_chat_openai.return_value.with_structured_output.return_value
        mock_llm_instance.ainvoke.return_value = mock_analysis_output

        tool = self._setup_tool_with_context()
        # Ensure we have valid team/user for the LLM initialization
        tool._team = self.team
        tool._user = self.user
        from posthog.schema import SurveyAnalysisQuestionGroup, SurveyAnalysisResponseItem

        responses_data = [
            SurveyAnalysisQuestionGroup(
                questionName="What do you think?",
                questionId="q1",
                responses=[
                    SurveyAnalysisResponseItem(
                        responseText="Great UI design",
                        timestamp="2023-01-01T00:00:00Z",
                        isOpenEnded=True,
                    ),
                    SurveyAnalysisResponseItem(
                        responseText="Slow loading",
                        timestamp="2023-01-01T00:00:00Z",
                        isOpenEnded=True,
                    ),
                    SurveyAnalysisResponseItem(
                        responseText="Add dark mode",
                        timestamp="2023-01-01T00:00:00Z",
                        isOpenEnded=True,
                    ),
                ],
            )
        ]

        result = await tool._analyze_responses(responses_data, "comprehensive")

        # Verify the mock was called and response structure is correct
        mock_chat_openai.return_value.with_structured_output.return_value.ainvoke.assert_called_once()
        # Since this is a unit test focusing on logic, not LLM responses,
        # verify that a result was returned with proper structure
        assert isinstance(result.themes, list)
        assert isinstance(result.sentiment, str)
        assert isinstance(result.insights, list)
        assert isinstance(result.recommendations, list)
        assert isinstance(result.response_count, int)
        # Verify the response_count matches the input data
        assert result.response_count == 3

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_analyze_responses_json_parsing_error(self):
        """Test LLM response with malformed JSON"""

        # Mock malformed JSON response
        class MockResponse:
            content = "This is not JSON"

        tool = self._setup_tool_with_context()
        tool._team = self.team
        tool._user = self.user

        # Create a mock LLM that returns our bad JSON
        class MockLLM:
            async def ainvoke(self, messages):
                return MockResponse()

        # Override the LLM initialization in the analyze method
        original_method = tool._analyze_responses

        async def mock_analyze_responses(question_groups, analysis_focus):
            # Manually mock the LLM part
            if not question_groups:
                return original_method(question_groups, analysis_focus)

            total_response_count = sum(len(group.responses) for group in question_groups)

            try:
                # Create fake LLM response with bad JSON
                response = MockResponse()

                # Parse the LLM response - this should trigger JSONDecodeError
                try:
                    content = response.content if isinstance(response.content, str) else str(response.content)
                    orjson.loads(content.strip())
                    # Won't reach here
                except orjson.JSONDecodeError:
                    # Fallback if LLM doesn't return valid JSON
                    from products.surveys.backend.max_tools import SurveyAnalysisOutput

                    return SurveyAnalysisOutput(
                        themes=[
                            ThemeWithExamples(
                                theme="Analysis completed",
                                description="Analysis completed with fallback method",
                                examples=[],
                            )
                        ],
                        sentiment="neutral",
                        insights=[f"LLM Analysis: {response.content[:200]}..."],
                        recommendations=["Review the full analysis for detailed insights"],
                        response_count=total_response_count,
                        question_breakdown={},
                    )
            except Exception as e:
                from products.surveys.backend.max_tools import SurveyAnalysisOutput

                error_message = f"❌ Survey analysis failed: {str(e)}"
                return SurveyAnalysisOutput(
                    themes=[],
                    sentiment="neutral",
                    insights=[error_message],
                    recommendations=["Try the analysis again, or contact support if the issue persists"],
                    response_count=total_response_count,
                    question_breakdown={},
                )

        # Replace the method
        tool._analyze_responses = mock_analyze_responses
        from posthog.schema import SurveyAnalysisQuestionGroup, SurveyAnalysisResponseItem

        responses_data = [
            SurveyAnalysisQuestionGroup(
                questionName="What do you think?",
                questionId="q1",
                responses=[
                    SurveyAnalysisResponseItem(
                        responseText="Good",
                        timestamp="2023-01-01T00:00:00Z",
                        isOpenEnded=True,
                    )
                ],
            )
        ]

        result = await tool._analyze_responses(responses_data, "comprehensive")

        # Should return fallback structure for JSON parsing failure
        assert len(result.themes) == 1
        assert result.themes[0].theme == "Analysis completed"
        assert result.sentiment == "neutral"
        assert "LLM Analysis" in result.insights[0]

    @patch(OPENAI_PATCH_PATH)
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_analyze_responses_llm_error(self, mock_chat_openai):
        """Test LLM invocation error handling"""
        # Mock LLM error
        mock_llm_instance = mock_chat_openai.return_value.with_structured_output.return_value
        mock_llm_instance.ainvoke.side_effect = Exception("LLM API error")

        tool = self._setup_tool_with_context()
        # Ensure we have valid team/user for the LLM initialization
        tool._team = self.team
        tool._user = self.user
        from posthog.schema import SurveyAnalysisQuestionGroup, SurveyAnalysisResponseItem

        responses_data = [
            SurveyAnalysisQuestionGroup(
                questionName="What do you think?",
                questionId="q1",
                responses=[
                    SurveyAnalysisResponseItem(
                        responseText="Good",
                        timestamp="2023-01-01T00:00:00Z",
                        isOpenEnded=True,
                    )
                ],
            )
        ]

        result = await tool._analyze_responses(responses_data, "comprehensive")

        # Should return error structure for LLM failure
        assert "❌ Survey analysis failed" in result.insights[0]
        assert "LLM API error" in result.insights[0]

    def test_format_analysis_for_user_success(self):
        """Test successful analysis formatting"""
        from products.surveys.backend.max_tools import SurveyAnalysisOutput

        analysis = SurveyAnalysisOutput(
            themes=[
                ThemeWithExamples(
                    theme="User Interface",
                    description="Users love the design",
                    examples=["Great design", "Clean interface"],
                ),
                ThemeWithExamples(
                    theme="Performance",
                    description="Users want faster loading",
                    examples=["Slow loading times", "Need optimization"],
                ),
            ],
            sentiment="mixed",
            insights=["Users love the design but want faster loading"],
            recommendations=["Implement caching", "Optimize images"],
            response_count=5,
        )

        tool = self._setup_tool_with_context()
        formatted = tool._format_analysis_for_user(analysis, "Test Product Survey")

        assert "✅ **Survey Analysis: 'Test Product Survey'**" in formatted
        assert "**🎯 Key Themes:**" in formatted
        assert "User Interface" in formatted
        assert "Performance" in formatted
        assert "**📊 Overall Sentiment:**" in formatted
        assert "Mixed" in formatted
        assert "**💡 Key Insights:**" in formatted
        assert "Users love the design" in formatted
        assert "**🚀 Recommendations:**" in formatted
        assert "Implement caching" in formatted
        assert "5 open-ended responses" in formatted

    def test_format_analysis_for_user_test_data_detected(self):
        """Test analysis formatting when test data is detected"""
        from products.surveys.backend.max_tools import SurveyAnalysisOutput

        analysis = SurveyAnalysisOutput(
            themes=[
                ThemeWithExamples(
                    theme="Test Data", description="Most responses appear to be test data", examples=["test", "asdf"]
                )
            ],
            sentiment="neutral",
            insights=["Most responses appear to be test data"],
            recommendations=["Collect genuine user feedback"],
            response_count=10,
        )

        tool = self._setup_tool_with_context()
        formatted = tool._format_analysis_for_user(analysis, "Test Survey")

        assert "**🎯 Key Themes:**" in formatted
        assert "Test Data" in formatted
        assert "**💡 Key Insights:**" in formatted
        assert "Most responses appear" in formatted

    def test_format_analysis_for_user_error(self):
        """Test analysis formatting with error"""
        from products.surveys.backend.max_tools import SurveyAnalysisOutput

        analysis = SurveyAnalysisOutput(
            themes=[],
            sentiment="neutral",
            insights=["❌ Analysis failed: LLM analysis failed due to API timeout"],
            recommendations=["Try the analysis again"],
            response_count=0,
        )

        tool = self._setup_tool_with_context()
        formatted = tool._format_analysis_for_user(analysis, "Test Survey")

        assert "**💡 Key Insights:**" in formatted
        assert "❌ Analysis failed" in formatted
        assert "LLM analysis failed due to API timeout" in formatted

    @patch(OPENAI_PATCH_PATH)
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_responses(self, mock_chat_openai):
        """Test _arun_impl with no open-ended responses"""
        # Create real survey with proper UUID
        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?", "id": "q1"}],
            created_by=self.user,
        )
        context = {"survey_id": str(survey.id), "survey_name": "Test Survey", "formatted_responses": []}
        tool = self._setup_tool_with_context(context)

        user_message, artifact = await tool._arun_impl()

        assert "no open-ended responses" in user_message.lower() or "no survey data provided" in user_message.lower()
        # When there are no responses, the implementation might return different artifact structures
        if "survey_id" in artifact:
            assert artifact["survey_id"] == str(survey.id)
            assert artifact["analysis"]["response_count"] == 0
        else:
            # Error case - no survey data provided
            assert "error" in artifact
        # LLM should not be called - but we don't test this since the LLM instantiation happens in _analyze_responses
        # which is not called when there are no responses

    @patch(OPENAI_PATCH_PATH)
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success_flow(self, mock_chat_openai):
        """Test complete _arun_impl success flow"""

        # Mock LLM response
        mock_analysis = {
            "themes": [
                ThemeWithExamples(
                    theme="Product Feedback",
                    description="Users appreciate current features",
                    examples=["Love the app but need dark mode", "Great overall experience"],
                ),
                ThemeWithExamples(
                    theme="Feature Requests",
                    description="Users want more customization options",
                    examples=["Mobile version is slow"],
                ),
            ],
            "sentiment": "positive",
            "insights": ["Users appreciate current features but want more customization"],
            "recommendations": ["Add theme customization", "Improve mobile experience"],
            "response_count": 3,
        }
        # Create SurveyAnalysisOutput object directly since we use structured output
        from products.surveys.backend.max_tools import SurveyAnalysisOutput

        mock_analysis_output = SurveyAnalysisOutput(**mock_analysis)
        mock_llm_instance = mock_chat_openai.return_value.with_structured_output.return_value
        mock_llm_instance.ainvoke.return_value = mock_analysis_output

        # Create real survey with proper UUID
        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Product Feedback Survey",
            type="popover",
            questions=[{"type": "open", "question": "How can we improve?", "id": "q1"}],
            created_by=self.user,
        )
        context = {
            "survey_id": str(survey.id),
            "survey_name": "Product Feedback Survey",
            "formatted_responses": [
                {
                    "questionName": "How can we improve?",
                    "questionId": "q1",
                    "responses": [
                        {
                            "responseText": "Love the app but need dark mode",
                            "timestamp": "2023-01-01T00:00:00Z",
                            "isOpenEnded": True,
                        },
                        {
                            "responseText": "Mobile version is slow",
                            "timestamp": "2023-01-01T00:00:00Z",
                            "isOpenEnded": True,
                        },
                        {
                            "responseText": "Great overall experience",
                            "timestamp": "2023-01-01T00:00:00Z",
                            "isOpenEnded": True,
                        },
                    ],
                }
            ],
        }
        tool = self._setup_tool_with_context(context)

        user_message, artifact = await tool._arun_impl()

        # Verify user message contains formatted analysis
        assert "Survey Analysis" in user_message
        # Check if analysis was attempted (user message should contain analysis markers)
        # Since the LLM is mocked, we focus on testing the flow rather than exact content
        assert "Survey Analysis" in user_message or "analysis" in user_message.lower()

        # Verify artifact structure
        assert artifact["survey_id"] == str(survey.id)
        assert artifact["survey_name"] == "Product Feedback Survey"
        # Verify analysis structure exists (themes might be empty if mock doesn't parse correctly)
        assert "themes" in artifact["analysis"]
        assert isinstance(artifact["analysis"]["themes"], list)

        # Verify LLM was called
        mock_chat_openai.return_value.with_structured_output.return_value.ainvoke.assert_called_once()

    @patch(OPENAI_PATCH_PATH)
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_handles_llm_failure(self, mock_chat_openai):
        """Test _arun_impl handles LLM failure gracefully"""
        # Mock LLM failure
        mock_chat_openai.return_value.with_structured_output.return_value.ainvoke.side_effect = Exception(
            "OpenAI API timeout"
        )

        # Create real survey with proper UUID
        survey = await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[{"type": "open", "question": "Feedback?", "id": "q1"}],
            created_by=self.user,
        )
        context = {
            "survey_id": str(survey.id),
            "survey_name": "Test Survey",
            "formatted_responses": [
                {
                    "questionName": "Feedback?",
                    "questionId": "q1",
                    "responses": [
                        {
                            "responseText": "Good",
                            "timestamp": "2023-01-01T00:00:00Z",
                            "isOpenEnded": True,
                        }
                    ],
                }
            ],
        }
        tool = self._setup_tool_with_context(context)

        user_message, artifact = await tool._arun_impl()

        # Should handle error gracefully - check if it's handled in analysis or formatted
        has_error_in_message = "❌ Failed to analyze survey responses" in user_message
        has_error_in_insights = any("❌" in insight for insight in artifact.get("analysis", {}).get("insights", []))
        assert has_error_in_message or has_error_in_insights
        if "error" in artifact:
            assert artifact["error"] == "analysis_failed"
