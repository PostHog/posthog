import json
from dataclasses import dataclass

import structlog

from posthog.models import Experiment, FeatureFlag, Insight, Team

from products.surveys.backend.llm import generate_structured_output
from products.surveys.backend.models import SurveyRecommendation
from products.surveys.backend.queries import get_survey_recommendation_candidates
from products.surveys.backend.summarization.models import GeminiModel

from .schema import RecommendationsResponse, SurveyRecommendationOutput


@dataclass
class SourceContext:
    insight: Insight | None = None
    experiment: Experiment | None = None
    flag: FeatureFlag | None = None


logger = structlog.get_logger(__name__)

DEFAULT_MODEL = GeminiModel.GEMINI_3_FLASH_PREVIEW

SYSTEM_PROMPT = """You are a product analytics expert helping teams identify where user surveys would provide the most value.

Your goal is to analyze funnels, experiments, and feature flags to recommend targeted surveys that will help the team understand user behavior and improve their product.

Guidelines:
- Focus on actionable recommendations that will generate useful insights
- For funnels: recommend surveys at drop-off points to understand why users don't convert
- For experiments: recommend surveys to understand qualitative feedback on variants
- For feature flags: recommend surveys to gather feedback on recently launched features
- Prioritize by potential impact (high-traffic funnels, important experiments)
- Generate specific, contextual survey questions - not generic ones
- For funnel surveys, specify the exact trigger_event (where to show) and cancel_event (when to hide)
- For multivariate flags and experiments with variants: specify target_variant to target a specific variant, or leave null to target all users
  - Consider recommending separate surveys for different variants to compare qualitative feedback
  - Tailor survey questions to the specific variant experience (e.g., "How do you like the new checkout flow?" for treatment)
- Score recommendations 0-100 based on potential value (consider view count, conversion rates, recency)
- Return at most 5 recommendations, focusing on quality over quantity
- If there are no good candidates, return an empty list
- Do not recommend surveys for items that already have active recommendations"""

RECOMMENDATION_TYPE_MAP = {
    "low_conversion_funnel": SurveyRecommendation.RecommendationType.LOW_CONVERSION_FUNNEL,
    "declining_feature": SurveyRecommendation.RecommendationType.DECLINING_FEATURE,
    "experiment_feedback": SurveyRecommendation.RecommendationType.EXPERIMENT_FEEDBACK,
    "feature_flag_feedback": SurveyRecommendation.RecommendationType.FEATURE_FLAG_FEEDBACK,
}


def _build_user_prompt(context: dict) -> str:
    filtered = {k: v for k, v in context.items() if v}
    return f"""{json.dumps(filtered, indent=2, default=str)}

    Analyze the above and generate survey recommendations. Focus on the highest-impact opportunities."""


def _get_source_info(rec: SurveyRecommendation) -> tuple[str, str]:
    if rec.source_insight:
        return "insight", rec.source_insight.short_id
    if rec.source_feature_flag:
        return "feature_flag", str(rec.source_feature_flag.id)
    if rec.source_experiment:
        return "experiment", str(rec.source_experiment.id)
    return "unknown", ""


def _get_existing_recommendations(team: Team) -> list[dict]:
    recommendations = SurveyRecommendation.objects.filter(
        team=team,
        status=SurveyRecommendation.Status.ACTIVE,
    ).select_related("source_insight", "source_feature_flag", "source_experiment")

    return [
        {
            "source_type": source_type,
            "source_id": source_id,
            "recommendation_type": rec.recommendation_type,
        }
        for rec in recommendations
        for source_type, source_id in [_get_source_info(rec)]
    ]


def _build_low_conversion_funnel_survey(rec: SurveyRecommendationOutput, defaults: dict, ctx: SourceContext) -> None:
    if ctx.insight:
        defaults["linked_insight_id"] = ctx.insight.id

    if not rec.trigger_event:
        return

    conditions: dict = {"events": {"values": [{"name": rec.trigger_event}]}}
    if rec.cancel_event:
        conditions["cancelEvents"] = {"values": [{"name": rec.cancel_event}]}
    defaults["conditions"] = conditions
    defaults["appearance"]["surveyPopupDelaySeconds"] = 15


def _build_feature_flag_feedback_survey(rec: SurveyRecommendationOutput, defaults: dict, ctx: SourceContext) -> None:
    if ctx.flag:
        defaults["linked_flag_id"] = ctx.flag.id

    if rec.target_variant:
        conditions = defaults.get("conditions") or {}
        conditions["linkedFlagVariant"] = rec.target_variant
        defaults["conditions"] = conditions


def _build_experiment_feedback_survey(rec: SurveyRecommendationOutput, defaults: dict, ctx: SourceContext) -> None:
    if ctx.experiment and ctx.experiment.feature_flag_id:
        defaults["linked_flag_id"] = ctx.experiment.feature_flag_id

    if rec.target_variant:
        conditions = defaults.get("conditions") or {}
        conditions["linkedFlagVariant"] = rec.target_variant
        defaults["conditions"] = conditions

    defaults["questions"] = [
        {
            "type": "rating",
            "question": rec.suggested_question or "How do you like this update?",
            "display": "emoji",
            "scale": 5,
            "lowerBoundLabel": "Not great",
            "upperBoundLabel": "Love it",
        }
    ]


def _build_declining_feature_survey(rec: SurveyRecommendationOutput, defaults: dict, ctx: SourceContext) -> None:
    if ctx.insight:
        defaults["linked_insight_id"] = ctx.insight.id
    defaults["questions"] = [
        {
            "type": "rating",
            "question": rec.suggested_question or "How useful do you find this feature?",
            "display": "emoji",
            "scale": 5,
            "lowerBoundLabel": "Not useful",
            "upperBoundLabel": "Very useful",
        },
        {"type": "open", "question": "What would make this feature more useful for you?", "optional": True},
    ]


SURVEY_BUILDERS = {
    "low_conversion_funnel": _build_low_conversion_funnel_survey,
    "feature_flag_feedback": _build_feature_flag_feedback_survey,
    "experiment_feedback": _build_experiment_feedback_survey,
    "declining_feature": _build_declining_feature_survey,
}


def _build_survey_defaults(rec: SurveyRecommendationOutput, ctx: SourceContext) -> dict:
    base_question = rec.suggested_question or "What's your experience with this feature?"

    defaults: dict = {
        "name": f"Feedback: {rec.title}",
        "type": "popover",
        "questions": [{"type": "open", "question": base_question}],
        "conditions": None,
        "appearance": {"surveyPopupDelaySeconds": 5},
    }

    builder = SURVEY_BUILDERS.get(rec.recommendation_type)
    if builder:
        builder(rec, defaults, ctx)

    return defaults


def _lookup_source_object(team: Team, rec: SurveyRecommendationOutput) -> SourceContext | None:
    if rec.source_type == "insight":
        source = Insight.objects.filter(team=team, short_id=rec.source_id, deleted=False).first()
        if not source:
            logger.warning("Source object not found", source_type=rec.source_type, source_id=rec.source_id)
            return None
        return SourceContext(insight=source)

    if rec.source_type == "experiment":
        source = Experiment.objects.filter(team=team, id=int(rec.source_id)).first()
        if not source:
            logger.warning("Source object not found", source_type=rec.source_type, source_id=rec.source_id)
            return None
        return SourceContext(experiment=source)

    if rec.source_type == "feature_flag":
        source = FeatureFlag.objects.filter(team=team, id=int(rec.source_id), deleted=False).first()
        if not source:
            logger.warning("Source object not found", source_type=rec.source_type, source_id=rec.source_id)
            return None
        return SourceContext(flag=source)

    logger.warning("Unknown source type", source_type=rec.source_type, source_id=rec.source_id)
    return None


def _save_recommendation(team: Team, rec: SurveyRecommendationOutput) -> bool:
    ctx = _lookup_source_object(team, rec)
    if not ctx:
        return False

    rec_type = RECOMMENDATION_TYPE_MAP.get(rec.recommendation_type)
    if not rec_type:
        logger.warning("Unknown recommendation type", recommendation_type=rec.recommendation_type)
        return False

    display_context = {
        "title": rec.title,
        "description": rec.reason,
        "source_type": rec.source_type,
        "source_id": rec.source_id,
    }

    survey_defaults = _build_survey_defaults(rec, ctx)

    filter_kwargs: dict = {"team": team, "status": SurveyRecommendation.Status.ACTIVE}
    source_mapping = {
        "source_insight": ctx.insight,
        "source_experiment": ctx.experiment,
        "source_feature_flag": ctx.flag,
    }
    filter_kwargs.update({k: v for k, v in source_mapping.items() if v is not None})

    SurveyRecommendation.objects.update_or_create(
        **filter_kwargs,
        defaults={
            "recommendation_type": rec_type,
            "survey_defaults": survey_defaults,
            "display_context": display_context,
            "score": rec.score,
        },
    )

    return True


def generate_recommendations(team: Team, model: GeminiModel = DEFAULT_MODEL) -> int:
    candidates = get_survey_recommendation_candidates(team)
    existing = _get_existing_recommendations(team)

    context = {**candidates, "existing_recommendations": existing}

    response, trace_id = generate_structured_output(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=_build_user_prompt(context),
        response_schema=RecommendationsResponse,
        posthog_properties={
            "ai_product": "survey_recommendations",
            "funnel_count": len(candidates.get("most_viewed_funnels", [])),
            "experiment_count": len(candidates.get("concluded_experiments", []))
            + len(candidates.get("running_experiments", [])),
            "flag_count": len(candidates.get("rolled_out_flags", [])),
            "existing_count": len(existing),
        },
        team_id=team.id,
    )

    logger.info(
        "Generated survey recommendations",
        team_id=team.id,
        trace_id=trace_id,
        recommendation_count=len(response.recommendations),
    )

    return sum(1 for rec in response.recommendations if _save_recommendation(team, rec))
