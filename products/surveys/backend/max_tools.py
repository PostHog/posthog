"""
MaxTool for AI-powered survey creation.
"""

from typing import Any, cast
import logging

import django.utils.timezone
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ee.hogai.tool import MaxTool
from posthog.constants import DEFAULT_SURVEY_APPEARANCE
from posthog.exceptions_capture import capture_exception
from posthog.models import Survey, Team, FeatureFlag
from posthog.schema import SurveyCreationSchema

from .prompts import SURVEY_CREATION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class SurveyCreatorArgs(BaseModel):
    instructions: str = Field(description="Natural language description of the survey to create")


class FeatureFlagLookupArgs(BaseModel):
    flag_key: str = Field(description="The key of the feature flag to look up")


class FeatureFlagLookupResult(BaseModel):
    flag_id: int = Field(description="The internal ID of the feature flag")
    flag_key: str = Field(description="The key of the feature flag")
    variants: list[str] = Field(description="List of available variant keys for this feature flag")
    exists: bool = Field(description="Whether the feature flag exists")


class CreateSurveyTool(MaxTool):
    name: str = "create_survey"
    description: str = "Create and optionally launch a survey based on natural language instructions"
    thinking_message: str = "Creating your survey"

    args_schema: type[BaseModel] = SurveyCreatorArgs

    async def _create_survey_from_instructions(self, instructions: str) -> SurveyCreationSchema:
        """
        Create a survey from natural language instructions using PostHog-native pattern.
        """
        logger.info(f"Starting survey creation with instructions: '{instructions}'")

        # Extract and lookup feature flags inline (following PostHog pattern)
        feature_flag_context = await self._extract_feature_flags_inline(instructions)

        # Build enhanced system prompt with feature flag information
        enhanced_system_prompt = SURVEY_CREATION_SYSTEM_PROMPT
        if feature_flag_context:
            enhanced_system_prompt += f"\n\n## Available Feature Flags\n{feature_flag_context}"

        # Single LLM call with all context (cost-effective, fast)
        prompt = ChatPromptTemplate.from_messages([
            ("system", enhanced_system_prompt),
            ("human", "Create a survey based on these instructions: {{{instructions}}}")
        ], template_format="mustache")

        model = (
            ChatOpenAI(model="gpt-5-mini")
            .with_structured_output(SurveyCreationSchema, include_raw=False)
            .with_retry()
        )

        chain = prompt | model
        result = await chain.ainvoke({
            "instructions": instructions,
            "existing_surveys": await self._get_existing_surveys_summary(),
            "team_survey_config": self._get_team_survey_config(self._team),
        })

        logger.info(f"Survey created with linked_flag_id: {getattr(result, 'linked_flag_id', None)}")
        return cast(SurveyCreationSchema, result)

    async def _arun_impl(self, instructions: str) -> tuple[str, dict[str, Any]]:
        """
        Generate survey configuration from natural language instructions.
        """
        try:
            user = self._user
            team = self._team

            result = await self._create_survey_from_instructions(instructions)
            try:
                if not result.questions:
                    return "❌ Survey must have at least one question", {
                        "error": "validation_failed",
                        "details": "No questions provided",
                    }

                # Apply appearance defaults and prepare survey data
                survey_data = self._prepare_survey_data(result, team)

                # Set launch date if requested
                if result.should_launch:
                    survey_data["start_date"] = django.utils.timezone.now()

                # Create the survey directly using Django ORM
                survey = await Survey.objects.acreate(team=team, created_by=user, **survey_data)

                launch_msg = " and launched" if result.should_launch else ""
                return f"✅ Survey '{survey.name}' created{launch_msg} successfully!", {
                    "survey_id": str(survey.id),
                    "survey_name": survey.name,
                    "error": None,
                }

            except Exception as validation_error:
                return f"❌ Survey validation failed: {str(validation_error)}", {
                    "error": "validation_failed",
                    "details": str(validation_error),
                }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Failed to create survey: {str(e)}", {"error": str(e)}

    def _get_team_survey_config(self, team: Team) -> dict[str, Any]:
        """Get team survey configuration for context."""
        survey_config = getattr(team, "survey_config", {}) or {}
        return {
            "appearance": survey_config.get("appearance", {}),
            "default_settings": {"type": "popover", "enable_partial_responses": True},
        }

    async def _get_existing_surveys_summary(self) -> str:
        """Get summary of existing surveys for context."""
        try:
            surveys = [survey async for survey in Survey.objects.filter(team_id=self._team.id, archived=False)[:5]]

            if not surveys:
                return "No existing surveys"

            summaries = []
            for survey in surveys:
                status = "active" if survey.start_date and not survey.end_date else "draft"
                summaries.append(f"- '{survey.name}' ({survey.type}, {status})")

            return "\n".join(summaries)
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id})
            return "Unable to load existing surveys"

    def _prepare_survey_data(self, survey_schema: SurveyCreationSchema, team: Team) -> dict[str, Any]:
        """Prepare survey data with appearance defaults applied."""
        # Convert schema to dict, removing should_launch field
        if hasattr(survey_schema, "model_dump"):
            survey_data = survey_schema.model_dump(exclude_unset=True, exclude={"should_launch"})
        else:
            survey_data = survey_schema.__dict__.copy()
            survey_data.pop("should_launch", None)

        # Ensure required fields have defaults
        survey_data.setdefault("archived", False)
        survey_data.setdefault("description", "")
        survey_data.setdefault("enable_partial_responses", True)

        # Apply appearance defaults
        appearance = DEFAULT_SURVEY_APPEARANCE.copy()

        # Override with team-specific defaults if they exist
        team_appearance = self._get_team_survey_config(team).get("appearance", {})
        if team_appearance:
            appearance.update(team_appearance)

        # Finally, override with survey-specified appearance settings
        if survey_data.get("appearance"):
            survey_appearance = survey_data["appearance"]
            # Convert to dict if needed
            if hasattr(survey_appearance, "model_dump"):
                survey_appearance = survey_appearance.model_dump(exclude_unset=True)
            elif hasattr(survey_appearance, "__dict__"):
                survey_appearance = survey_appearance.__dict__
            # Only update fields that are actually set (not None)
            appearance.update({k: v for k, v in survey_appearance.items() if v is not None})

        # Always set appearance to ensure surveys have consistent defaults
        survey_data["appearance"] = appearance

        return survey_data

    async def _extract_feature_flags_inline(self, instructions: str) -> str:
        """
        Extract and lookup feature flags inline using PostHog-native pattern.
        Similar to how insights nodes handle pagination inline.
        """
        import re

        # Step 1: Extract potential feature flag names using comprehensive patterns
        flag_patterns = [
            # Handle "feature flag key name" patterns (with/without quotes)
            r"feature flag[s]?\s+key\s+['\"]([a-zA-Z0-9_-]+)['\"]",    # "feature flag key 'name'"
            r"feature flag[s]?\s+key\s+([a-zA-Z0-9_-]+)",              # "feature flag key name"
            r"flag[s]?\s+key\s+['\"]([a-zA-Z0-9_-]+)['\"]",            # "flag key 'name'"
            r"flag[s]?\s+key\s+([a-zA-Z0-9_-]+)",                      # "flag key name"

            # Handle direct "feature flag name" patterns
            r"feature flag[s]?\s+['\"]([a-zA-Z0-9_-]+)['\"]",          # "feature flag 'name'"
            r"feature flag[s]?\s+([a-zA-Z0-9_-]+)",                    # "feature flag name"
            r"flag[s]?\s+['\"]([a-zA-Z0-9_-]+)['\"]",                  # "flag 'name'"
            r"flag[s]?\s+([a-zA-Z0-9_-]+)",                            # "flag name"

            # Handle contextual patterns
            r"with\s+(?:the\s+)?['\"]?([a-zA-Z0-9_-]+)['\"]?\s+(?:feature\s+)?flag",  # "with name flag"
            r"have\s+(?:the\s+)?['\"]?([a-zA-Z0-9_-]+)['\"]?\s+(?:feature\s+)?flag",  # "have name flag"
            r"(?:tied|linked)\s+(?:to|with)\s+(?:the\s+)?(?:feature\s+)?flag\s+['\"]?([a-zA-Z0-9_-]+)['\"]?",  # "tied to flag name"

            # Handle quoted names anywhere near flag context
            r"['\"]([a-zA-Z0-9_-]+)['\"].*(?:feature\s+flag|flag)",    # "'name' ... flag"
            r"(?:feature\s+flag|flag).*['\"]([a-zA-Z0-9_-]+)['\"]",    # "flag ... 'name'"
        ]

        potential_flags = set()
        instructions_lower = instructions.lower()

        # Also extract any hyphenated words that might be flag names in context of "flag"
        context_words = re.findall(r'\b([a-zA-Z0-9_-]{3,})\b', instructions_lower)
        flag_context_found = any(word in instructions_lower for word in ['flag', 'feature'])

        for pattern in flag_patterns:
            matches = re.finditer(pattern, instructions_lower, re.IGNORECASE)
            for match in matches:
                flag_name = match.group(1).strip()
                if len(flag_name) > 2:
                    potential_flags.add(flag_name)

        # If we're in a flag context, also consider hyphenated words as potential flags
        if flag_context_found:
            for word in context_words:
                if '-' in word and len(word) > 5:  # likely flag names have hyphens and are longer
                    potential_flags.add(word)

        # Filter out obvious false positives
        false_positives = {
            'the', 'and', 'for', 'with', 'have', 'that', 'this', 'flag', 'flags',
            'feature', 'key', 'enabled', 'disabled', 'survey', 'create', 'tied', 'linked'
        }
        potential_flags = {flag for flag in potential_flags if flag not in false_positives}

        if not potential_flags:
            logger.debug(f"No feature flags detected in instructions")
            return ""

        logger.info(f"Detected potential feature flags: {list(potential_flags)}")

        # Step 2: Lookup each flag in database and only include found ones
        flag_info_parts = []
        found_flags = []
        not_found_flags = []

        for flag_key in potential_flags:
            try:
                # Direct database lookup (like PostHog insights nodes do)
                feature_flag = await FeatureFlag.objects.select_related("team").aget(
                    key=flag_key, team_id=self._team.id
                )

                variants = [variant["key"] for variant in (feature_flag.variants or [])]
                variant_info = f" (variants: {', '.join(variants)})" if variants else " (no variants)"

                flag_info_parts.append(f"- **{flag_key}**: ID = {feature_flag.id}{variant_info}")
                found_flags.append(flag_key)
                logger.info(f"Found feature flag '{flag_key}' with ID: {feature_flag.id}")

            except FeatureFlag.DoesNotExist:
                not_found_flags.append(flag_key)
                logger.debug(f"Feature flag '{flag_key}' not found for team {self._team.id}")
            except Exception as e:
                logger.error(f"Error looking up feature flag '{flag_key}': {e}")

        # Log summary for debugging
        if found_flags:
            logger.info(f"Successfully found feature flags: {found_flags}")
        if not_found_flags:
            logger.debug(f"Feature flags not found: {not_found_flags}")

        return "\n".join(flag_info_parts) if flag_info_parts else ""


class FeatureFlagLookupTool(MaxTool):
    name: str = "lookup_feature_flag"
    description: str = "Look up a feature flag by its key to get the ID and available variants"
    thinking_message: str = "Looking up feature flag information"

    args_schema: type[BaseModel] = FeatureFlagLookupArgs

    async def _arun_impl(self, flag_key: str) -> tuple[str, dict[str, Any]]:
        """
        Look up feature flag information by key.
        """
        logger.info(f"🚨 DEBUG: FeatureFlagLookupTool called with flag_key='{flag_key}' for team {self._team.id}")
        try:
            # Look up the feature flag by key for the current team
            feature_flag = await FeatureFlag.objects.select_related("team").aget(key=flag_key, team_id=self._team.id)

            # Get available variants
            variants = [variant["key"] for variant in feature_flag.variants]

            message = f"✅ Found feature flag '{flag_key}' (ID: {feature_flag.id})"
            if variants:
                message += f" with variants: {', '.join(variants)}"
            else:
                message += " (no variants)"

            logger.info(f"✅ FeatureFlagLookupTool found flag '{flag_key}' with ID: {feature_flag.id}")
            return message, {
                "flag_id": feature_flag.id,
                "flag_key": feature_flag.key,
                "variants": variants,
                "exists": True,
            }

        except FeatureFlag.DoesNotExist:
            logger.warning(f"❌ FeatureFlagLookupTool: Feature flag '{flag_key}' not found for team {self._team.id}")
            return f"❌ Feature flag '{flag_key}' not found", {
                "flag_id": None,
                "flag_key": flag_key,
                "variants": [],
                "exists": False,
            }
        except Exception as e:
            logger.error(f"❌ FeatureFlagLookupTool error for flag '{flag_key}': {str(e)}")
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Error looking up feature flag: {str(e)}", {"error": str(e), "exists": False}
