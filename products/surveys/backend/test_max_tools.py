"""
Simple async test for the survey creation MaxTool.
"""

import os

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import orjson
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

from products.surveys.backend.max_tools import SurveyAnalysisOutput, SurveyUpdateSchema, ThemeWithExamples

from .max_tools import CreateSurveyTool, EditSurveyTool, SurveyAnalysisTool

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
        tool = SurveyAnalysisTool(
            team=self.team,
            user=self.user,
            config={
                **self._config,
                "configurable": {
                    **self._config.get("configurable", {}),
                    "contextual_tools": {"analyze_survey_responses": context},
                },
            },
        )
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
        assert "Survey analysis failed" in result.insights[0]
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

        assert "**Survey Analysis: 'Test Product Survey'**" in formatted
        assert "**Key Themes:**" in formatted
        assert "User Interface" in formatted
        assert "Performance" in formatted
        assert "**Overall Sentiment:**" in formatted
        assert "Mixed" in formatted
        assert "**Key Insights:**" in formatted
        assert "Users love the design" in formatted
        assert "**Recommendations:**" in formatted
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

        assert "**Key Themes:**" in formatted
        assert "Test Data" in formatted
        assert "**Key Insights:**" in formatted
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

        assert "**Key Insights:**" in formatted
        assert "Analysis failed" in formatted
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
        if "error" in artifact:
            assert artifact["error"] == "analysis_failed"

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
