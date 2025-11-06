import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase, Score
from braintrust_core.score import Scorer

from posthog.schema import SurveyCreationSchema

from posthog.models import FeatureFlag

from products.enterprise.backend.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from products.enterprise.backend.models.assistant import Conversation
from products.surveys.backend.max_tools import FeatureFlagLookupGraph

from ..base import MaxPublicEval


def validate_survey_output(output, scorer_name):
    """Common validation logic for survey scorers."""
    if not output.get("success", False):
        return Score(
            name=scorer_name,
            score=0,
            metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
        )

    survey_output = output.get("survey_creation_output")
    if not survey_output:
        return Score(name=scorer_name, score=0, metadata={"reason": "No survey output returned"})

    return survey_output


async def create_test_feature_flags(team, user):
    """Create test feature flags for evaluation scenarios."""

    test_flags = [
        {
            "key": "new-checkout-flow",
            "name": "New Checkout Flow",
            "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
        },
        {
            "key": "ab-test-experiment",
            "name": "A/B Test Experiment",
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "treatment", "rollout_percentage": 50},
                    ]
                },
            },
        },
        {
            "key": "homepage-redesign",
            "name": "Homepage Redesign",
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "variant-a", "rollout_percentage": 33},
                        {"key": "variant-b", "rollout_percentage": 33},
                        {"key": "variant-c", "rollout_percentage": 34},
                    ]
                },
            },
        },
        {
            "key": "pricing-page-test",
            "name": "Pricing Page Test",
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "treatment", "rollout_percentage": 50},
                    ]
                },
            },
        },
    ]

    created_flags = []
    for flag_data in test_flags:
        flag, created = await FeatureFlag.objects.aget_or_create(
            team=team,
            key=flag_data["key"],
            defaults={
                "name": flag_data["name"],
                "filters": flag_data["filters"],
                "created_by": user,
            },
        )
        created_flags.append(flag)

    return created_flags


@pytest.fixture
async def create_feature_flags(demo_org_team_user):
    """Create test feature flags for the test."""
    _, team, user = demo_org_team_user
    return await create_test_feature_flags(team, user)


@pytest.fixture
def call_surveys_max_tool(demo_org_team_user, create_feature_flags):
    """
    This fixture creates a properly configured SurveyCreatorTool for evaluation.
    """
    # Extract team and user from the demo fixture
    _, team, user = demo_org_team_user

    async def call_max_tool(instructions: str) -> dict:
        """
        Call the survey creation tool and return structured output.
        """

        try:
            conversation = await Conversation.objects.acreate(team=team, user=user)

            graph_context = {
                "change": f"Create a survey based on these instructions: {instructions}",
                "output": None,
            }
            graph = FeatureFlagLookupGraph(team=team, user=user).compile_full_graph(checkpointer=DjangoCheckpointer())
            result = await graph.ainvoke(
                graph_context,
                config={
                    "configurable": {
                        "thread_id": conversation.id,
                        "contextual_tools": {"create_survey": {"user_id": str(user.uuid)}},
                    }
                },
            )

            if "output" not in result or not isinstance(result["output"], SurveyCreationSchema):
                message = "Survey creation failed"
                if "intermediate_steps" in result and len(result["intermediate_steps"]) > 0:
                    return {
                        "success": False,
                        "survey_creation_output": None,
                        "message": result["intermediate_steps"][-1][0].tool_input or message,
                        "error": result["intermediate_steps"][-1][0].tool_input or message,
                    }
                else:
                    return {"success": False, "survey_creation_output": None, "message": message, "error": message}

            # Return structured output that Braintrust can understand
            return {
                "success": True,
                "survey_creation_output": result["output"] if result else None,
                "message": "Survey created successfully",
            }
        except Exception as e:
            return {"success": False, "survey_creation_output": None, "message": str(e), "error": str(e)}

    return call_max_tool


class SurveyRelevanceScorer(LLMClassifier):
    """
    Evaluate if the generated survey is relevant to the given instructions using LLM as a judge.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="survey_relevance",
            prompt_template="""
Evaluate if the generated survey is relevant and appropriate for the given user instructions.

User Instructions: {{input}}

Generated Survey:
Name: {{output.survey_creation_output.name}}
Description: {{output.survey_creation_output.description}}
Type: {{output.survey_creation_output.type}}
Questions:
{{#output.survey_creation_output.questions}}
- {{type}}: {{question}}
{{#choices}}  Choices: {{.}}{{/choices}}
{{#scale}}  Scale: {{.}}{{/scale}}
{{/output.survey_creation_output.questions}}

Evaluation Criteria:
1. Does the survey name and description match the user's intent?
2. Are the question types appropriate for the user's request? (e.g., NPS should use rating, feedback should use open text)
3. Do the questions address what the user asked for?
4. Is the survey type (popover/widget/api) appropriate for the context?
5. Are the questions logically connected to the user's goals?

How would you rate the relevance of this survey to the user's instructions? Choose one:
- perfect: The survey perfectly matches the user's intent and requirements
- good: The survey is relevant but could be slightly better aligned
- partial: The survey is somewhat relevant but misses some key aspects
- irrelevant: The survey does not address the user's request at all
""".strip(),
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "irrelevant": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        return super()._run_eval_sync(output, expected, **kwargs)


class SurveyQuestionQualityScorer(LLMClassifier):
    """
    Evaluate the quality of survey questions using LLM as a judge.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="survey_question_quality",
            prompt_template="""
Evaluate the quality of the survey questions based on best practices for IN-APP survey design.

IMPORTANT CONTEXT: These are in-app surveys that appear as overlays while users are actively using the product.
Users are trying to accomplish tasks, not fill out long surveys.

User Instructions: {{input}}

Generated Survey Questions:
{{#output.survey_creation_output.questions}}
- {{type}}: {{question}}
{{#description}}   Description: {{.}}{{/description}}
{{#choices}}   Choices: {{.}}{{/choices}}
{{#scale}}   Scale: {{.}}{{/scale}}
{{/output.survey_creation_output.questions}}

Evaluation Criteria for IN-APP Surveys:
1. **Appropriate Length**: 1-3 questions maximum. More than 3 questions is unacceptable for in-app surveys.
2. **Focused Purpose**: Does the survey focus on ONE key insight rather than trying to gather everything?
3. **User Respect**: Are the questions respectful of user time and context (they're in the middle of using the product)?
4. **No Duplicates**: Are all questions distinct and non-repetitive?
5. **Clarity**: Are the questions clear, unambiguous, and easy to understand?
6. **Logical Flow**: Do the questions follow a logical sequence?
7. **Question Types**: Are the question types (rating, open, choice) well-suited to what they're asking?
8. **Completion-Friendly**: Are the questions designed for high completion rates in an in-app context?

CRITICAL: Surveys with more than 3 questions should be rated as "unacceptable" regardless of other quality factors.

How would you rate the overall quality of these survey questions for IN-APP use? Choose one:
- perfect: 1-2 focused, clear questions that respect user time and context
- good: 1-3 good quality questions with minor issues but appropriate for in-app use
- partial: Questions are adequate but may be slightly long or unfocused for in-app context
- irrelevant: More than 3 questions, severely unfocused, or inappropriate for in-app context
""".strip(),
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "irrelevant": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        if not survey_output.questions:
            return Score(name=self._name(), score=0, metadata={"reason": "Survey has no questions"})

        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        if not survey_output.questions:
            return Score(name=self._name(), score=0, metadata={"reason": "Survey has no questions"})

        return super()._run_eval_sync(output, expected, **kwargs)


class SurveyFirstQuestionTypeScorer(Scorer):
    """
    Evaluate if the first question type matches what we expect for the given instructions.
    """

    def _name(self):
        return "first_question_type_correct"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        # Skip if no expected criteria provided
        if not expected:
            return None

        # Check if the survey was created successfully
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        # Check if survey has questions
        if not survey_output.questions:
            return Score(name=self._name(), score=0, metadata={"reason": "Survey has no questions"})

        # Check if first question type matches expected
        first_question = survey_output.questions[0]
        actual_type = first_question.type
        expected_type = expected.get("first_question_type")

        if actual_type == expected_type:
            return Score(
                name=self._name(),
                score=1,
                metadata={
                    "reason": "First question type matches expected",
                    "expected_type": expected_type,
                    "actual_type": actual_type,
                    "survey_name": survey_output.name,
                    "total_questions": len(survey_output.questions),
                },
            )
        else:
            return Score(
                name=self._name(),
                score=0,
                metadata={
                    "reason": "First question type mismatch",
                    "expected_type": expected_type,
                    "actual_type": actual_type,
                    "survey_name": survey_output.name,
                    "total_questions": len(survey_output.questions),
                },
            )


class SurveyCreationBasicsScorer(Scorer):
    """
    Evaluate basic survey creation requirements (has name, description, questions).
    """

    def _name(self):
        return "survey_creation_basics"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        # Check if the survey was created successfully
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        # Check basic requirements and track successes/failures
        checks = []
        successes = []

        # Check 1: Has name
        checks.append("name")
        if survey_output.name:
            successes.append("name")

        # Check 2: Has description
        checks.append("description")
        if survey_output.description:
            successes.append("description")

        # Check 3: Has questions
        checks.append("questions")
        if survey_output.questions:
            successes.append("questions")

        # Check 4: Meets minimum questions requirement
        min_questions = expected.get("min_questions", 1) if expected else 1
        checks.append("min_questions")
        if len(survey_output.questions) >= min_questions:
            successes.append("min_questions")

        # Calculate proportional score
        total_checks = len(checks)
        successful_checks = len(successes)
        score = successful_checks / total_checks if total_checks > 0 else 0

        # Create list of failed checks for metadata
        failed_checks = [check for check in checks if check not in successes]

        return Score(
            name=self._name(),
            score=score,
            metadata={
                "reason": f"Survey passed {successful_checks}/{total_checks} basic requirements",
                "successful_checks": successes,
                "failed_checks": failed_checks,
                "survey_name": survey_output.name,
                "total_questions": len(survey_output.questions),
                "min_questions_required": min_questions,
            },
        )


class SurveyFeatureFlagIntegrationScorer(Scorer):
    """
    Evaluate feature flag integration in survey creation.
    """

    def _name(self):
        return "feature_flag_integration"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._run_eval_sync(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        # Skip if no expected criteria provided
        if not expected:
            return None

        # Use common validation logic
        survey_output = validate_survey_output(output, self._name())
        if isinstance(survey_output, Score):  # Validation failed, return the error score
            return survey_output

        # Check feature flag integration expectations
        expected_flag_id = expected.get("expected_flag_id")
        expected_variant = expected.get("expected_variant")
        should_have_flag = expected.get("should_have_flag", False)
        should_have_variant = expected.get("should_have_variant", False)

        checks = []
        successes = []

        # Check 1: Feature flag should be linked if expected
        if should_have_flag:
            checks.append("has_flag")
            if hasattr(survey_output, "linked_flag_id") and survey_output.linked_flag_id:
                successes.append("has_flag")
                # Check 2: Feature flag ID should match if specified
                if expected_flag_id:
                    checks.append("correct_flag_id")
                    if survey_output.linked_flag_id == expected_flag_id:
                        successes.append("correct_flag_id")

        # Check 3: Variant should be set if expected
        if should_have_variant:
            checks.append("has_variant")
            conditions = getattr(survey_output, "conditions", None)
            if conditions and hasattr(conditions, "linkedFlagVariant") and conditions.linkedFlagVariant:
                successes.append("has_variant")
                # Check 4: Variant should match if specified
                if expected_variant:
                    checks.append("correct_variant")
                    # Handle special case of "any" variant - should pass if any variant is set
                    if expected_variant == "any" or conditions.linkedFlagVariant == expected_variant:
                        successes.append("correct_variant")

        # If no checks were added, it means no feature flag criteria were specified
        if not checks:
            return None

        # Calculate proportional score
        total_checks = len(checks)
        successful_checks = len(successes)
        score = successful_checks / total_checks if total_checks > 0 else 0

        # Create list of failed checks for metadata
        failed_checks = [check for check in checks if check not in successes]

        return Score(
            name=self._name(),
            score=score,
            metadata={
                "reason": f"Feature flag integration passed {successful_checks}/{total_checks} checks",
                "successful_checks": successes,
                "failed_checks": failed_checks,
                "survey_name": getattr(survey_output, "name", "Unknown"),
                "linked_flag_id": getattr(survey_output, "linked_flag_id", None),
                "variant_condition": getattr(getattr(survey_output, "conditions", None), "linkedFlagVariant", None),
                "expected_flag_id": expected_flag_id,
                "expected_variant": expected_variant,
            },
        )


class SurveyFeatureFlagUnderstandingScorer(LLMClassifier):
    """
    Evaluate if the AI correctly understood feature flag targeting requirements using LLM as a judge.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="feature_flag_understanding",
            prompt_template="""
Evaluate if the AI correctly understood and implemented feature flag targeting in the survey creation.

User Instructions: {{input}}

Generated Survey:
Name: {{output.survey_creation_output.name}}
Description: {{output.survey_creation_output.description}}
Linked Feature Flag ID: {{output.survey_creation_output.linked_flag_id}}
{{#output.survey_creation_output.conditions}}
Conditions: {{.}}
{{/output.survey_creation_output.conditions}}
Questions:
{{#output.survey_creation_output.questions}}
- {{type}}: {{question}}
{{/output.survey_creation_output.questions}}

Evaluation Criteria:
1. **Intent Recognition**: Did the AI correctly identify when the user wanted to target users based on feature flags?
2. **Flag Targeting**: If the user mentioned specific feature flag names, did the AI attempt to link to those flags?
3. **Variant Handling**: If the user mentioned specific variants (like "treatment", "control", "any"), did the AI set appropriate conditions?
4. **Context Appropriateness**: Is the survey content relevant to the feature flag context mentioned?
5. **No False Positives**: If the user mentioned feature flags conceptually but didn't want targeting, did the AI avoid linking flags?

IMPORTANT: Rate based on whether the AI understood the targeting intent, not whether specific flag IDs match (since test flags may not exist).

How would you rate the AI's understanding and implementation of feature flag targeting? Choose one:
- perfect: Correctly identified targeting intent and implemented all aspects appropriately
- good: Understood most aspects correctly with minor issues
- partial: Understood some aspects but missed important targeting details
- irrelevant: Completely misunderstood the feature flag targeting requirements
""".strip(),
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "irrelevant": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        # Only run this scorer for test cases that involve feature flags
        if not kwargs.get("metadata", {}).get("test_type", "").startswith("feature_flag") and not kwargs.get(
            "metadata", {}
        ).get("test_type", "").startswith("ab_test"):
            return None

        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        # Only run this scorer for test cases that involve feature flags
        if not kwargs.get("metadata", {}).get("test_type", "").startswith("feature_flag") and not kwargs.get(
            "metadata", {}
        ).get("test_type", "").startswith("ab_test"):
            return None

        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Survey creation failed", "error": output.get("error", "Unknown error")},
            )

        survey_output = output.get("survey_creation_output")
        if not survey_output:
            return Score(name=self._name(), score=0, metadata={"reason": "No survey output returned"})

        return super()._run_eval_sync(output, expected, **kwargs)


@pytest.mark.django_db
async def eval_surveys(call_surveys_max_tool, pytestconfig):
    """
    Evaluation for survey creation functionality.
    """
    await MaxPublicEval(
        experiment_name="surveys",
        task=call_surveys_max_tool,
        scores=[
            SurveyFirstQuestionTypeScorer(),
            SurveyCreationBasicsScorer(),
            SurveyRelevanceScorer(),
            SurveyQuestionQualityScorer(),
            SurveyFeatureFlagIntegrationScorer(),
            SurveyFeatureFlagUnderstandingScorer(),
        ],
        data=[
            # Test case 1: NPS survey should have rating question first
            EvalCase(
                input="Create a satisfaction survey (NPS) to measure customer loyalty, following the standard Net Promoter Score methodology and including follow-up questions for deeper insights.",
                expected={"first_question_type": "rating", "min_questions": 1},
                metadata={"test_type": "nps_survey"},
            ),
            # Test case 2: PMF survey should have single choice question first
            EvalCase(
                input="Make a product-market fit (PMF) survey that follows established best practices (e.g. asking how disappointed users would be if they could no longer use the product), and include additional questions to understand product value and improvement areas",
                expected={"first_question_type": "single_choice", "min_questions": 1},
                metadata={"test_type": "pmf_survey"},
            ),
            # Test case 3: Open feedback survey should have open text question first
            EvalCase(
                input="Make a general customer insights survey.",
                expected={"first_question_type": "open", "min_questions": 1},
                metadata={"test_type": "open_feedback_survey"},
            ),
            # Test case 4: Comprehensive survey should still be kept short for in-app use
            EvalCase(
                input="Make a survey on demographics, usage, satisfaction, features, and suggestions. First question = single choice.",
                expected={"min_questions": 1, "first_question_type": "single_choice"},
                metadata={"test_type": "comprehensive_survey_length_constraint"},
            ),
            # Test case 5: Survey with feature flag targeting - should detect and link feature flag
            EvalCase(
                input="Create a survey for users who have the 'new-checkout-flow' feature flag enabled to get feedback on the checkout experience",
                expected={
                    "min_questions": 1,
                    "should_have_flag": True,
                    "should_have_variant": False,  # General flag reference, not specific variant
                },
                metadata={"test_type": "feature_flag_targeting"},
            ),
            # Test case 6: Survey with specific feature flag variant targeting
            EvalCase(
                input="Create a satisfaction survey for users in the 'treatment' variant of the 'ab-test-experiment' feature flag to measure the impact of the new design",
                expected={
                    "min_questions": 1,
                    "should_have_flag": True,
                    "should_have_variant": True,
                    "expected_variant": "treatment",
                },
                metadata={"test_type": "feature_flag_variant_targeting"},
            ),
            # Test case 7: Survey targeting users with any variant of a multivariate flag
            EvalCase(
                input="Create a feedback survey for all users who have 'any' variant of the 'homepage-redesign' feature flag enabled",
                expected={
                    "min_questions": 1,
                    "should_have_flag": True,
                    "should_have_variant": True,
                    "expected_variant": "any",
                },
                metadata={"test_type": "feature_flag_any_variant_targeting"},
            ),
            # Test case 8: Survey that mentions feature flag but isn't necessarily targeting by it
            EvalCase(
                input="Create an open text survey asking users about their experience with feature flags in general and how they affect their workflow",
                expected={
                    "min_questions": 1,
                    "should_have_flag": False,  # This is about feature flags as a concept, not targeting
                },
                metadata={"test_type": "feature_flag_concept_not_targeting"},
            ),
            # Test case 9: A/B test control group survey
            EvalCase(
                input="Create an NPS survey specifically for users in the control group of our pricing-page-test feature flag to measure baseline satisfaction",
                expected={
                    "min_questions": 1,
                    "should_have_flag": True,
                    "should_have_variant": True,
                    "expected_variant": "control",
                },
                metadata={"test_type": "ab_test_control_group"},
            ),
            # Test case 10: Edge case - Invalid feature flag reference
            EvalCase(
                input="Create a survey for users with the 'non-existent-flag' feature flag to get their feedback",
                expected={
                    "min_questions": 1,
                    "should_have_flag": False,  # Should not link to non-existent flag
                },
                metadata={"test_type": "feature_flag_invalid_reference"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
