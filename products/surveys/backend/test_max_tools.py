"""
Tests for the survey creation MaxTool.
"""

from unittest.mock import MagicMock, patch
import os

import pytest
from django.test import override_settings
from django.utils import timezone

from posthog.models import User, OrganizationMembership, Survey
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from .max_tools import SurveyCreatorTool, SurveyCreatorArgs
from .survey_schema import (
    SurveyCreationOutput,
    SurveyQuestionSchema,
    QuestionTypeEnum,
    SurveyTypeEnum,
    SurveyDisplayConditionsSchema,
    SurveyAppearanceSchema,
    RatingDisplayEnum,
)


class TestSurveyCreatorTool(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        # Set mock OpenAI API key for tests
        os.environ["OPENAI_API_KEY"] = "test-api-key"

        # Create a test user for survey creation
        self.test_user = User.objects.create_user(
            email="test@posthog.com", password="testpass", first_name="Test", last_name="User"
        )

        # Add user to the team's organization
        OrganizationMembership.objects.create(
            organization=self.team.organization, user=self.test_user, level=OrganizationMembership.Level.ADMIN
        )

    def tearDown(self):
        super().tearDown()
        # Clean up the mock API key
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]

    def _setup_mocks(self, mock_prompt, mock_openai, mock_output):
        """Helper method to set up mocks consistently"""
        # Mock the chain and all method calls properly
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_model
        mock_model.with_retry.return_value = mock_model
        mock_openai.return_value = mock_model

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_output
        mock_prompt.return_value.__or__ = MagicMock(return_value=mock_chain)

        return mock_chain

    def _create_tool(self, context=None, team_id=None):
        """Helper to create a SurveyCreatorTool instance"""
        tool = SurveyCreatorTool()

        # Mock the internal state required by MaxTool
        tool._team_id = team_id or self.team.id
        tool._context = context or {}
        tool._config = {
            "configurable": {
                "thread_id": "test-thread",
                "trace_id": "test-trace",
                "distinct_id": "test-distinct-id",
                "team_id": team_id or self.team.id,
            }
        }

        # Mock the context property to return our _context
        def mock_context_getter(self):
            return self._context

        tool.__class__.context = property(mock_context_getter)

        return tool

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_basic_survey_creation_success(self, mock_prompt, mock_openai):
        """Test successful creation of a basic survey"""
        # Mock LLM response
        mock_output = SurveyCreationOutput(
            name="Customer Satisfaction Survey",
            description="Quick feedback survey",
            type=SurveyTypeEnum.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=QuestionTypeEnum.RATING,
                    question="How satisfied are you with our product?",
                    description="Rate your satisfaction",
                    optional=False,
                    scale=5,
                    display=RatingDisplayEnum.NUMBER,
                    lowerBoundLabel="Very unsatisfied",
                    upperBoundLabel="Very satisfied",
                )
            ],
            should_launch=False,
            enable_partial_responses=True,
        )

        # Mock the chain and all method calls properly
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_model
        mock_model.with_retry.return_value = mock_model
        mock_openai.return_value = mock_model

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_output
        mock_prompt.return_value.__or__ = MagicMock(return_value=mock_chain)

        tool = self._create_tool(context={"user_id": str(self.test_user.uuid)})

        content, artifact = tool._run_impl("Create a customer satisfaction survey")

        # Verify success response (check for either "created successfully" or "created and launched")
        self.assertIn("✅ Survey", content)
        self.assertIn("created", content)
        self.assertIn("successfully", content)
        self.assertIn("survey_id", artifact)
        self.assertIn("survey_name", artifact)
        self.assertEqual(artifact["launched"], False)
        self.assertEqual(artifact["questions_count"], 1)

        # Verify survey was created in database
        survey = Survey.objects.get(id=artifact["survey_id"])
        self.assertEqual(survey.name, "Customer Satisfaction Survey")
        self.assertEqual(survey.description, "Quick feedback survey")
        self.assertEqual(survey.type, "popover")
        self.assertEqual(len(survey.questions), 1)
        self.assertFalse(survey.archived)

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_survey_creation_with_launch(self, mock_prompt, mock_openai):
        """Test survey creation with immediate launch"""
        mock_output = SurveyCreationOutput(
            name="Quick NPS Survey",
            description="Net Promoter Score survey",
            type=SurveyTypeEnum.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=QuestionTypeEnum.RATING,
                    question="How likely are you to recommend us?",
                    scale=10,
                    display=RatingDisplayEnum.NUMBER,
                )
            ],
            should_launch=True,
            enable_partial_responses=True,
        )

        # Mock the chain and all method calls properly
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_model
        mock_model.with_retry.return_value = mock_model
        mock_openai.return_value = mock_model

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_output
        mock_prompt.return_value.__or__ = MagicMock(return_value=mock_chain)

        tool = self._create_tool(context={"user_id": str(self.test_user.uuid)})

        content, artifact = tool._run_impl("Create and launch an NPS survey")

        # Verify launch message
        self.assertIn("and launched", content)
        self.assertEqual(artifact["launched"], True)

        # Verify survey has start date
        survey = Survey.objects.get(id=artifact["survey_id"])
        self.assertIsNotNone(survey.start_date)

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_complex_multi_question_survey(self, mock_prompt, mock_openai):
        """Test creation of a complex survey with multiple question types"""
        mock_output = SurveyCreationOutput(
            name="Product Feedback Survey",
            description="Comprehensive product feedback",
            type=SurveyTypeEnum.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=QuestionTypeEnum.SINGLE_CHOICE,
                    question="What's your primary use case?",
                    choices=["Analytics", "Product Management", "Engineering", "Other"],
                ),
                SurveyQuestionSchema(
                    type=QuestionTypeEnum.MULTIPLE_CHOICE,
                    question="Which features do you use most?",
                    choices=["Insights", "Dashboards", "Feature Flags", "Session Recordings"],
                ),
                SurveyQuestionSchema(type=QuestionTypeEnum.OPEN, question="What could we improve?", optional=True),
                SurveyQuestionSchema(
                    type=QuestionTypeEnum.RATING,
                    question="Overall satisfaction?",
                    scale=5,
                    display=RatingDisplayEnum.EMOJI,
                ),
            ],
            conditions=SurveyDisplayConditionsSchema(url="app.posthog.com", urlMatchType="contains"),
            should_launch=False,
            enable_partial_responses=True,
        )

        mock_chain = self._setup_mocks(mock_prompt, mock_openai, mock_output)

        tool = self._create_tool(context={"user_id": str(self.test_user.uuid)})

        content, artifact = tool._run_impl("Create a comprehensive product feedback survey")

        # Verify the mock was called
        mock_chain.invoke.assert_called_once()

        # Verify survey creation
        survey = Survey.objects.get(id=artifact["survey_id"])
        self.assertEqual(len(survey.questions), 4)  # Expect 4 questions, not 5

        # Check question types
        questions = survey.questions
        self.assertEqual(questions[0]["type"], "single_choice")
        self.assertEqual(questions[1]["type"], "multiple_choice")
        self.assertEqual(questions[2]["type"], "open")
        self.assertEqual(questions[3]["type"], "rating")

        # Check conditions
        self.assertIn("conditions", survey.__dict__)
        if hasattr(survey, "conditions") and survey.conditions:
            self.assertEqual(survey.conditions["url"], "app.posthog.com")

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_survey_creation_validation_error(self, mock_prompt, mock_openai):
        """Test handling of survey validation errors"""
        # Create invalid output (missing required fields)
        mock_output = SurveyCreationOutput(
            name="",  # Invalid empty name
            description="Test",
            type=SurveyTypeEnum.POPOVER,
            questions=[],  # No questions
            should_launch=False,
        )

        self._setup_mocks(mock_prompt, mock_openai, mock_output)

        tool = self._create_tool(context={"user_id": str(self.test_user.uuid)})

        content, artifact = tool._run_impl("Create an invalid survey")

        # Verify error response
        self.assertIn("❌ Survey validation failed", content)
        self.assertEqual(artifact["error"], "validation_failed")
        self.assertIn("details", artifact)

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_survey_creation_exception_handling(self, mock_prompt, mock_openai):
        """Test handling of unexpected exceptions during survey creation"""
        # Setup mocks first, then override the invoke method to raise exception
        mock_output = SurveyCreationOutput(
            name="Test",
            description="Test",
            type=SurveyTypeEnum.POPOVER,
            questions=[SurveyQuestionSchema(type=QuestionTypeEnum.OPEN, question="Test?")],
            should_launch=False,
        )
        mock_chain = self._setup_mocks(mock_prompt, mock_openai, mock_output)
        # Override to make it raise an exception
        mock_chain.invoke.side_effect = Exception("LLM API Error")

        tool = self._create_tool(context={"user_id": str(self.test_user.uuid)})

        content, artifact = tool._run_impl("Create a survey")

        # Verify error handling
        self.assertIn("❌ Failed to create survey", content)
        self.assertEqual(artifact["error"], "LLM API Error")

    def test_get_existing_surveys_summary(self):
        """Test the existing surveys summary functionality"""
        # Create some existing surveys
        Survey.objects.create(
            team=self.team,
            name="Existing Survey 1",
            type="popover",
            questions=[],
            created_by=self.test_user,
            start_date=timezone.now(),
        )
        Survey.objects.create(
            team=self.team, name="Draft Survey 2", type="button", questions=[], created_by=self.test_user
        )
        Survey.objects.create(
            team=self.team,
            name="Archived Survey",
            type="popover",
            questions=[],
            created_by=self.test_user,
            archived=True,
        )

        tool = self._create_tool()
        summary = tool._get_existing_surveys_summary()

        # Should include non-archived surveys
        self.assertIn("Existing Survey 1", summary)
        self.assertIn("Draft Survey 2", summary)
        self.assertIn("active", summary)
        self.assertIn("draft", summary)

        # Should not include archived surveys
        self.assertNotIn("Archived Survey", summary)

    def test_get_existing_surveys_summary_empty(self):
        """Test existing surveys summary when no surveys exist"""
        tool = self._create_tool()
        summary = tool._get_existing_surveys_summary()

        self.assertEqual(summary, "No existing surveys")

    def test_get_team_survey_config(self):
        """Test team survey configuration retrieval"""
        # Test with team that has no survey config
        tool = self._create_tool()
        config = tool._get_team_survey_config(self.team)

        self.assertIn("appearance", config)
        self.assertIn("default_settings", config)
        self.assertEqual(config["default_settings"]["type"], "popover")

    def test_convert_to_posthog_format_basic(self):
        """Test conversion of LLM output to PostHog survey format"""
        tool = self._create_tool()

        llm_output = SurveyCreationOutput(
            name="Test Survey",
            description="Test Description",
            type=SurveyTypeEnum.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=QuestionTypeEnum.RATING, question="Rate us", scale=5, display=RatingDisplayEnum.NUMBER
                )
            ],
            should_launch=False,
            enable_partial_responses=True,
        )

        survey_data = tool._convert_to_posthog_format(llm_output, self.team)

        # Check basic fields
        self.assertEqual(survey_data["name"], "Test Survey")
        self.assertEqual(survey_data["description"], "Test Description")
        self.assertEqual(survey_data["type"], "popover")
        self.assertTrue(survey_data["enable_partial_responses"])
        self.assertFalse(survey_data["archived"])

        # Check questions
        self.assertEqual(len(survey_data["questions"]), 1)
        question = survey_data["questions"][0]
        self.assertEqual(question["type"], "rating")
        self.assertEqual(question["question"], "Rate us")
        self.assertEqual(question["scale"], 5)
        self.assertEqual(question["display"], "number")

    def test_convert_to_posthog_format_with_conditions(self):
        """Test conversion with survey conditions"""
        tool = self._create_tool()

        llm_output = SurveyCreationOutput(
            name="Conditional Survey",
            description="Survey with conditions",
            type=SurveyTypeEnum.POPOVER,
            questions=[SurveyQuestionSchema(type=QuestionTypeEnum.OPEN, question="Feedback?")],
            conditions=SurveyDisplayConditionsSchema(
                url="dashboard", urlMatchType="contains", selector="#feedback-button"
            ),
            should_launch=False,
        )

        survey_data = tool._convert_to_posthog_format(llm_output, self.team)

        # Check conditions
        self.assertIn("conditions", survey_data)
        conditions = survey_data["conditions"]
        self.assertEqual(conditions["url"], "dashboard")
        self.assertEqual(conditions["urlMatchType"], "contains")
        self.assertEqual(conditions["selector"], "#feedback-button")

    def test_convert_to_posthog_format_with_appearance(self):
        """Test conversion with custom appearance"""
        tool = self._create_tool()

        llm_output = SurveyCreationOutput(
            name="Styled Survey",
            description="Survey with custom appearance",
            type=SurveyTypeEnum.POPOVER,
            questions=[SurveyQuestionSchema(type=QuestionTypeEnum.OPEN, question="Feedback?")],
            appearance=SurveyAppearanceSchema(backgroundColor="#ff0000", borderColor="#000000"),
            should_launch=False,
        )

        survey_data = tool._convert_to_posthog_format(llm_output, self.team)

        # Check appearance - note that there's no textColor in DEFAULT_SURVEY_APPEARANCE
        self.assertIn("appearance", survey_data)
        appearance = survey_data["appearance"]
        self.assertEqual(appearance["backgroundColor"], "#ff0000")
        self.assertEqual(appearance["borderColor"], "#000000")
        # Check that defaults are applied
        self.assertEqual(appearance["submitButtonTextColor"], "white")  # From DEFAULT_SURVEY_APPEARANCE

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_authentication_required(self, mock_prompt, mock_openai):
        """Test that user authentication is required"""
        # Mock LLM response (should not be called)
        mock_output = SurveyCreationOutput(
            name="Test Survey",
            description="Test",
            type=SurveyTypeEnum.POPOVER,
            questions=[SurveyQuestionSchema(type=QuestionTypeEnum.OPEN, question="Test?")],
            should_launch=False,
        )

        self._setup_mocks(mock_prompt, mock_openai, mock_output)

        tool = self._create_tool(context={})  # No user_id provided

        content, artifact = tool._run_impl("Create a survey")

        # Should fail with authentication error
        self.assertIn("❌ Failed to create survey: User authentication required", content)
        self.assertEqual(artifact["error"], "authentication_required")

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_invalid_user_handling(self, mock_prompt, mock_openai):
        """Test handling of invalid user IDs"""
        # Mock LLM response (should not be called)
        mock_output = SurveyCreationOutput(
            name="Test Survey",
            description="Test",
            type=SurveyTypeEnum.POPOVER,
            questions=[SurveyQuestionSchema(type=QuestionTypeEnum.OPEN, question="Test?")],
            should_launch=False,
        )

        self._setup_mocks(mock_prompt, mock_openai, mock_output)

        # Use a non-existent user ID
        tool = self._create_tool(context={"user_id": "00000000-0000-0000-0000-000000000000"})

        content, artifact = tool._run_impl("Create a survey")

        # Should fail with invalid user error
        self.assertIn("❌ Failed to create survey: Invalid user", content)
        self.assertEqual(artifact["error"], "invalid_user")

    @override_settings(IN_UNIT_TESTING=True)
    def test_tool_args_schema(self):
        """Test the tool's argument schema"""
        args = SurveyCreatorArgs(instructions="Create a satisfaction survey")
        self.assertEqual(args.instructions, "Create a satisfaction survey")

    def test_tool_metadata(self):
        """Test the tool's metadata and configuration"""
        tool = SurveyCreatorTool()

        self.assertEqual(tool.name, "create_survey")
        self.assertEqual(
            tool.description, "Create and optionally launch a survey based on natural language instructions"
        )
        self.assertEqual(tool.thinking_message, "Creating your survey")
        self.assertEqual(tool.args_schema, SurveyCreatorArgs)
        self.assertIn("Total surveys", tool.root_system_prompt_template)

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_context_integration(self, mock_prompt, mock_openai):
        """Test that the tool properly uses context from existing surveys"""
        # Create existing surveys
        Survey.objects.create(
            team=self.team, name="Existing NPS Survey", type="popover", questions=[], created_by=self.test_user
        )

        mock_output = SurveyCreationOutput(
            name="New Survey",
            description="Test",
            type=SurveyTypeEnum.POPOVER,
            questions=[SurveyQuestionSchema(type=QuestionTypeEnum.OPEN, question="Test?")],
            should_launch=False,
        )

        mock_chain = self._setup_mocks(mock_prompt, mock_openai, mock_output)

        tool = self._create_tool(context={"user_id": str(self.test_user.uuid)})

        content, artifact = tool._run_impl("Create a different survey")

        # Verify that the LLM was called with context
        mock_chain.invoke.assert_called_once()
        call_args = mock_chain.invoke.call_args[0][0]

        # The context should include existing surveys information
        self.assertIn("existing_surveys", call_args)
        self.assertIn("team_survey_config", call_args)


# Integration tests using eval framework patterns
class TestSurveyCreatorToolEvals(ClickhouseTestMixin, APIBaseTest):
    """
    These tests follow the evaluation patterns used in the MaxAI system
    to test the tool's behavior in more realistic scenarios.
    """

    def setUp(self):
        super().setUp()
        # Set mock OpenAI API key for tests
        os.environ["OPENAI_API_KEY"] = "test-api-key"

        self.test_user = User.objects.create_user(
            email="eval@posthog.com",
            password="testpass",
            first_name="Eval",  # Add required first_name
            last_name="User",  # Add required last_name
        )
        OrganizationMembership.objects.create(
            organization=self.team.organization, user=self.test_user, level=OrganizationMembership.Level.ADMIN
        )

    def tearDown(self):
        super().tearDown()
        # Clean up the mock API key
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]

    def _setup_mocks(self, mock_prompt, mock_openai, mock_output):
        """Helper method to set up mocks consistently"""
        # Mock the chain and all method calls properly
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_model
        mock_model.with_retry.return_value = mock_model
        mock_openai.return_value = mock_model

        mock_chain = MagicMock()
        mock_chain.invoke.return_value = mock_output
        mock_prompt.return_value.__or__ = MagicMock(return_value=mock_chain)

        return mock_chain

    def _create_tool(self, context=None, team_id=None):
        """Helper to create a SurveyCreatorTool instance"""
        tool = SurveyCreatorTool()

        # Mock the internal state required by MaxTool
        tool._team_id = team_id or self.team.id
        tool._context = context or {}
        tool._config = {
            "configurable": {
                "thread_id": "test-thread",
                "trace_id": "test-trace",
                "distinct_id": "test-distinct-id",
                "team_id": team_id or self.team.id,
            }
        }

        # Mock the context property to return our _context
        def mock_context_getter(self):
            return self._context

        tool.__class__.context = property(mock_context_getter)

        return tool

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_eval_basic_survey_creation_scenarios(self, mock_prompt, mock_openai):
        """Test various survey creation scenarios that should work"""
        test_cases = [
            {
                "input": "Create a customer satisfaction survey",
                "expected_name_pattern": "satisfaction",
                "expected_question_type": "rating",
            },
            {
                "input": "Create an NPS survey to measure loyalty",
                "expected_name_pattern": "NPS",
                "expected_question_type": "rating",
            },
            {
                "input": "Create a feedback survey for our new feature",
                "expected_name_pattern": "feedback",
                "expected_question_type": "open",
            },
            {
                "input": "Create a quick yes/no survey about newsletter",
                "expected_name_pattern": "newsletter",
                "expected_question_type": "single_choice",
            },
        ]

        for i, case in enumerate(test_cases):
            with self.subTest(input_text=case["input"]):
                # Mock appropriate LLM response based on input
                if "satisfaction" in case["input"] or "NPS" in case["input"]:
                    questions = [
                        SurveyQuestionSchema(type=QuestionTypeEnum.RATING, question="How would you rate us?", scale=10)
                    ]
                elif "feedback" in case["input"]:
                    questions = [SurveyQuestionSchema(type=QuestionTypeEnum.OPEN, question="What's your feedback?")]
                else:  # yes/no
                    questions = [
                        SurveyQuestionSchema(
                            type=QuestionTypeEnum.SINGLE_CHOICE,
                            question="Would you like to subscribe?",
                            choices=["Yes", "No"],
                        )
                    ]

                mock_output = SurveyCreationOutput(
                    name=f"Test {case['expected_name_pattern']} Survey {i+1}",  # Unique name
                    description="Auto-generated survey",
                    type=SurveyTypeEnum.POPOVER,
                    questions=questions,
                    should_launch=False,
                )

                self._setup_mocks(mock_prompt, mock_openai, mock_output)

                tool = self._create_tool(context={"user_id": str(self.test_user.uuid)})

                content, artifact = tool._run_impl(case["input"])

                # Verify successful creation
                self.assertIn("✅ Survey", content)
                self.assertIn("survey_id", artifact)

                # Verify survey properties
                survey = Survey.objects.get(id=artifact["survey_id"])
                self.assertIn(case["expected_name_pattern"].lower(), survey.name.lower())
                self.assertEqual(survey.questions[0]["type"], case["expected_question_type"])

    @patch("products.surveys.backend.max_tools.ChatOpenAI")
    @patch("langchain_core.prompts.ChatPromptTemplate.from_messages")
    def test_eval_survey_launch_scenarios(self, mock_prompt, mock_openai):
        """Test scenarios where surveys should be launched vs saved as drafts"""
        launch_cases = [
            ("Create and launch a customer feedback survey", True),
            ("Create and activate an NPS survey", True),
            ("Create a draft survey for later", False),
            ("Create a survey but don't launch it yet", False),
        ]

        for i, (input_text, should_launch) in enumerate(launch_cases):
            with self.subTest(input_text=input_text):
                mock_output = SurveyCreationOutput(
                    name=f"Test Survey {i+1}",  # Unique name for each test case
                    description="Test",
                    type=SurveyTypeEnum.POPOVER,
                    questions=[SurveyQuestionSchema(type=QuestionTypeEnum.OPEN, question="Test?")],
                    should_launch=should_launch,
                )

                self._setup_mocks(mock_prompt, mock_openai, mock_output)

                tool = self._create_tool(context={"user_id": str(self.test_user.uuid)})

                content, artifact = tool._run_impl(input_text)

                # Verify launch behavior
                self.assertIn("launched", artifact)  # Key should exist
                self.assertEqual(artifact["launched"], should_launch)
                if should_launch:
                    self.assertIn("and launched", content)
                    survey = Survey.objects.get(id=artifact["survey_id"])
                    self.assertIsNotNone(survey.start_date)
                else:
                    self.assertNotIn("and launched", content)


if __name__ == "__main__":
    pytest.main([__file__])
