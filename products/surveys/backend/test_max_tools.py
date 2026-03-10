"""
Simple async test for the survey creation MaxTool.
"""

import os

import pytest
from posthog.test.base import BaseTest

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.models import FeatureFlag, Insight, Survey

from .max_tools import CreateSurveyTool, EditSurveyTool, SimpleSurveyQuestion, SurveyAnalysisTool


class TestSurveyCreatorTool(BaseTest):
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
        return CreateSurveyTool(team=self.team, user=self.user, config=self._config)

    def test_get_team_survey_config(self):
        from products.surveys.backend.max_tools import get_team_survey_config

        config = get_team_survey_config(self.team)

        assert "appearance" in config
        assert "default_settings" in config
        assert config["default_settings"]["type"] == "popover"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="Test Survey",
            description="A simple test survey",
            questions=[
                SimpleSurveyQuestion(
                    type="open", question="How do you feel about our product?", description="Please share your thoughts"
                ),
            ],
        )

        assert "Survey" in content
        assert "created" in content
        assert "successfully" in content
        assert "survey_id" in artifact
        assert "survey_name" in artifact

        survey = await sync_to_async(Survey.objects.get)(id=artifact["survey_id"])
        assert survey.name == "Test Survey"
        assert survey.description == "A simple test survey"
        assert survey.type == "popover"
        assert survey.questions is not None
        assert len(survey.questions) == 1
        assert not survey.archived

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_questions_validation(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(name="Test Survey", questions=[])

        assert "Survey must have at least one question" in content
        assert artifact["error"] == "validation_failed"
        assert "No questions provided" in artifact["error_message"]

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_with_launch(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="Launch Survey",
            description="A survey to launch",
            questions=[SimpleSurveyQuestion(type="open", question="Test question?")],
            should_launch=True,
        )

        assert "Survey" in content
        assert "successfully" in content

        survey = await sync_to_async(Survey.objects.get)(id=artifact["survey_id"])
        assert survey.start_date is not None

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag(self):
        tool = self._setup_tool()

        flag = await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="test-feature",
            name="Test Feature",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        content, artifact = await tool._arun_impl(
            name="Feature Flag Survey",
            description="Survey for users with test feature",
            questions=[SimpleSurveyQuestion(type="csat", question="How satisfied are you with the new feature?")],
            linked_flag_id=flag.id,
        )

        assert "Survey" in content
        assert "successfully" in content

        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        assert survey.name == "Feature Flag Survey"
        assert survey.linked_flag_id == flag.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag_variant(self):
        tool = self._setup_tool()

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

        content, artifact = await tool._arun_impl(
            name="A/B Test Control Survey",
            description="Survey for users in control variant",
            questions=[
                SimpleSurveyQuestion(
                    type="single_choice",
                    question="Which version do you prefer?",
                    choices=["Version A", "Version B", "No preference"],
                )
            ],
            linked_flag_id=flag.id,
            linked_flag_variant="control",
        )

        assert "Survey" in content
        assert "successfully" in content

        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        assert survey.name == "A/B Test Control Survey"
        assert survey.linked_flag_id == flag.id
        assert survey.conditions is not None
        assert survey.conditions["linkedFlagVariant"] == "control"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag_variant_any(self):
        tool = self._setup_tool()

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

        content, artifact = await tool._arun_impl(
            name="All Variants Survey",
            description="Survey for all users with the feature enabled",
            questions=[SimpleSurveyQuestion(type="open", question="How is the new feature working for you?")],
            linked_flag_id=flag.id,
            linked_flag_variant="any",
        )

        assert "Survey" in content
        assert "successfully" in content

        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        assert survey.name == "All Variants Survey"
        assert survey.linked_flag_id == flag.id
        assert survey.conditions is not None
        assert survey.conditions["linkedFlagVariant"] == "any"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_with_launch(self):
        tool = self._setup_tool()
        is_dangerous = await tool.is_dangerous_operation(should_launch=True)
        assert is_dangerous is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_without_launch(self):
        tool = self._setup_tool()
        is_dangerous = await tool.is_dangerous_operation(should_launch=False)
        assert is_dangerous is False

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_format_dangerous_operation_preview(self):
        tool = self._setup_tool()

        preview = await tool.format_dangerous_operation_preview(
            name="NPS Survey",
            questions=[
                SimpleSurveyQuestion(type="nps", question="How likely are you to recommend us?"),
                SimpleSurveyQuestion(type="open", question="Why?", optional=True),
            ],
            should_launch=True,
        )

        assert "Create and launch" in preview
        assert "NPS Survey" in preview
        assert "2 question(s)" in preview
        assert "start collecting responses" in preview

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_linked_insight(self):
        insight = await sync_to_async(Insight.objects.create)(
            team=self.team,
            name="Test Funnel",
            created_by=self.user,
        )

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

        content, artifact = await tool._arun_impl(
            name="Funnel Survey",
            description="Survey for funnel conversion",
            questions=[SimpleSurveyQuestion(type="open", question="Why didn't you complete the checkout?")],
        )

        assert "Survey" in content
        assert "successfully" in content

        survey = await sync_to_async(Survey.objects.select_related("linked_insight").get)(id=artifact["survey_id"])
        assert survey.name == "Funnel Survey"
        assert survey.linked_insight_id == insight.id

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_nps_survey_builds_correct_question(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="NPS Survey",
            questions=[
                SimpleSurveyQuestion(
                    type="nps",
                    question="How likely are you to recommend us?",
                    lower_bound_label="Not likely at all",
                    upper_bound_label="Extremely likely",
                )
            ],
        )

        assert "successfully" in content
        survey = await sync_to_async(Survey.objects.get)(id=artifact["survey_id"])
        assert survey.questions is not None
        assert len(survey.questions) > 0

        q = survey.questions[0]
        assert q["type"] == "rating"
        assert q["scale"] == 10
        assert q["display"] == "number"
        assert q["lowerBoundLabel"] == "Not likely at all"
        assert q["upperBoundLabel"] == "Extremely likely"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_url_targeting(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(
            name="Pricing Feedback",
            questions=[SimpleSurveyQuestion(type="open", question="Is our pricing clear?")],
            target_url="/pricing",
            target_url_match="contains",
        )

        assert "successfully" in content
        survey = await sync_to_async(Survey.objects.get)(id=artifact["survey_id"])

        assert survey.conditions is not None
        assert survey.conditions["url"] == "/pricing"
        assert survey.conditions["urlMatchType"] == "icontains"


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
        return SurveyAnalysisTool(
            team=self.team,
            user=self.user,
            config=self._config,
        )

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_survey_id(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl()

        assert "no survey id provided" in content.lower()
        assert artifact["error"] == "no_survey_id"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_survey_not_found(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(survey_id="00000000-0000-0000-0000-000000000000")

        assert "not found" in content.lower()
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_responses(self):
        from unittest.mock import patch

        with patch("products.surveys.backend.max_tools.fetch_responses", return_value=[]):
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
    async def test_arun_impl_returns_formatted_responses(self):
        from unittest.mock import patch

        mock_responses = [
            "Love the app but need dark mode",
            "Mobile version is slow",
            "Great overall experience",
        ]

        with patch("products.surveys.backend.max_tools.fetch_responses", return_value=mock_responses):
            survey = await sync_to_async(Survey.objects.create)(
                team=self.team,
                name="Product Feedback Survey",
                type="popover",
                questions=[{"type": "open", "question": "How can we improve?", "id": "q1"}],
                created_by=self.user,
            )
            tool = self._setup_tool()

            content, artifact = await tool._arun_impl(survey_id=str(survey.id))

            assert "Product Feedback Survey" in content
            assert "3" in content
            assert "How can we improve?" in content
            assert "Love the app but need dark mode" in content
            assert "Mobile version is slow" in content
            assert "Great overall experience" in content
            assert "themes" in content.lower()
            assert "sentiment" in content.lower()

            assert artifact["survey_id"] == str(survey.id)
            assert artifact["survey_name"] == "Product Feedback Survey"
            assert artifact["response_count"] == 3

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_multiple_questions(self):
        from unittest.mock import patch

        with patch(
            "products.surveys.backend.max_tools.fetch_responses",
            side_effect=[
                ["Great UI", "Fast performance"],
                ["Add dark mode"],
            ],
        ):
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

            assert "What do you like?" in content
            assert "What could be better?" in content
            assert "Great UI" in content
            assert "Fast performance" in content
            assert "Add dark mode" in content
            assert artifact["response_count"] == 3

    def test_format_responses_for_analysis(self):
        from posthog.schema import SurveyAnalysisQuestionGroup, SurveyAnalysisResponseItem

        tool = self._setup_tool()

        question_groups = [
            SurveyAnalysisQuestionGroup(
                questionName="What do you think?",
                questionId="q1",
                responses=[
                    SurveyAnalysisResponseItem(responseText="Great product", isOpenEnded=True),
                    SurveyAnalysisResponseItem(responseText="Could be better", isOpenEnded=True),
                ],
            ),
        ]

        formatted = tool._format_responses_for_analysis(question_groups)

        assert 'Question: "What do you think?"' in formatted
        assert '- "Great product"' in formatted
        assert '- "Could be better"' in formatted

    def test_format_responses_for_analysis_empty_responses(self):
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
        return EditSurveyTool(team=self.team, user=self.user, config=self._config)

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

        content, artifact = await tool._arun_impl(
            survey_id=str(survey.id), name="Updated Name", description="Updated description"
        )

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

        content, artifact = await tool._arun_impl(
            survey_id=str(survey.id),
            questions=[
                SimpleSurveyQuestion(type="csat", question="New rating question?"),
                SimpleSurveyQuestion(type="open", question="Follow-up?", optional=True),
            ],
        )

        assert "updated successfully" in content
        assert "questions" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.questions is not None
        assert len(updated_survey.questions) == 2
        assert updated_survey.questions[0]["type"] == "rating"
        assert updated_survey.questions[0]["scale"] == 5

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_url_targeting(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        content, artifact = await tool._arun_impl(
            survey_id=str(survey.id), target_url="/dashboard", target_url_match="contains"
        )

        assert "updated successfully" in content
        assert "conditions" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.conditions is not None
        assert updated_survey.conditions["url"] == "/dashboard"
        assert updated_survey.conditions["urlMatchType"] == "icontains"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_targeting_clears_stale_keys(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey(
            conditions={"url": "/old-page", "urlMatchType": "icontains", "seenSurveyWaitPeriodInDays": 7}
        )

        content, artifact = await tool._arun_impl(survey_id=str(survey.id), linked_flag_variant="control")

        assert "updated successfully" in content
        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.conditions is not None
        assert "url" not in updated_survey.conditions
        assert "urlMatchType" not in updated_survey.conditions
        assert "seenSurveyWaitPeriodInDays" not in updated_survey.conditions
        assert updated_survey.conditions["linkedFlagVariant"] == "control"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_launch(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        content, artifact = await tool._arun_impl(survey_id=str(survey.id), launch=True)

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

        content, artifact = await tool._arun_impl(survey_id=str(survey.id), stop=True)

        assert "stopped" in content
        assert "end_date" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.end_date is not None

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_archive(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        content, artifact = await tool._arun_impl(survey_id=str(survey.id), archive=True)

        assert "archived" in content
        assert "archived" in artifact["updated_fields"]

        updated_survey = await sync_to_async(Survey.objects.get)(id=survey.id)
        assert updated_survey.archived is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_not_found(self):
        tool = self._setup_tool()

        content, artifact = await tool._arun_impl(survey_id="00000000-0000-0000-0000-000000000000", name="New Name")

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
        content, artifact = await tool._arun_impl(survey_id=str(other_survey.id), name="Hacked Name")

        assert "not found" in content.lower()
        assert artifact["error"] == "not_found"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_no_updates(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        content, artifact = await tool._arun_impl(survey_id=str(survey.id))

        assert "no updates" in content.lower()
        assert artifact["error"] == "no_updates"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_edit_survey_stop_and_archive(self):
        import django.utils.timezone

        tool = self._setup_tool()
        survey = await self._create_test_survey(start_date=django.utils.timezone.now())

        content, artifact = await tool._arun_impl(survey_id=str(survey.id), stop=True, archive=True)

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
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        is_dangerous = await tool.is_dangerous_operation(survey_id=str(survey.id), launch=True)
        assert is_dangerous is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_stop(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        is_dangerous = await tool.is_dangerous_operation(survey_id=str(survey.id), stop=True)
        assert is_dangerous is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_archive(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        is_dangerous = await tool.is_dangerous_operation(survey_id=str(survey.id), archive=True)
        assert is_dangerous is True

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_is_dangerous_operation_regular_update(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey()

        is_dangerous = await tool.is_dangerous_operation(
            survey_id=str(survey.id), name="New Name", description="New description"
        )
        assert is_dangerous is False

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_format_dangerous_operation_preview_launch(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey(name="My NPS Survey")

        preview = await tool.format_dangerous_operation_preview(survey_id=str(survey.id), launch=True)

        assert "Launch" in preview
        assert "My NPS Survey" in preview
        assert "start collecting responses" in preview

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_format_dangerous_operation_preview_multiple_actions(self):
        tool = self._setup_tool()
        survey = await self._create_test_survey(name="Survey to Archive")

        preview = await tool.format_dangerous_operation_preview(survey_id=str(survey.id), stop=True, archive=True)

        assert "Stop" in preview
        assert "Archive" in preview
        assert "Survey to Archive" in preview
