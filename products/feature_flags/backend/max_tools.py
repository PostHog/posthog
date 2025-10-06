"""
MaxTool for AI-powered feature flag creation.
"""

from typing import Any

from django.utils.text import slugify

from asgiref.sync import sync_to_async
from nanoid import generate
from pydantic import BaseModel, Field

from posthog.schema import FeatureFlagCreationSchema

from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.exceptions_capture import capture_exception
from posthog.models import FeatureFlag, Team, User

from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .prompts import FEATURE_FLAG_CREATION_SYSTEM_PROMPT


class FeatureFlagCreatorArgs(BaseModel):
    instructions: str = Field(description="Natural language description of the feature flag to create")


def get_team_feature_flag_config(team: Team) -> dict[str, Any]:
    """Get team feature flag configuration for context."""
    # Get team-specific feature flag config if it exists, similar to survey_config pattern
    feature_flag_config = getattr(team, "feature_flag_config", {}) or {}
    return {
        "default_settings": {
            "evaluation_runtime": "all",  # Matches model default
            "rollout_percentage": 0,  # Start conservative
            "active": True,
            "ensure_experience_continuity": False,  # Matches model default
        },
        **feature_flag_config,  # Allow team-specific overrides
    }


async def _flag_with_key_exists(key: str, team: Team) -> bool:
    return await FeatureFlag.objects.filter(team=team, key=key, deleted=False).aexists()


async def generate_feature_flag_key(name: str, team: Team) -> str:
    """Generate a unique feature flag key from a name, only adding random suffix if needed for uniqueness."""
    base_key = slugify(name)

    if not base_key:
        base_key = "feature-flag"

    # Check if this key already exists
    if not await _flag_with_key_exists(base_key, team):
        return base_key

    # Try numbered suffixes first (more readable than random)
    for i in range(2, 10):
        numbered_key = f"{base_key}-{i}"
        if not await _flag_with_key_exists(numbered_key, team):
            return numbered_key

    # If all numbered suffixes are taken, fall back to random suffix
    random_id = generate("1234567890abcdef", 8)
    return f"{base_key}-{random_id}"


def create_mock_request(user: User, team: Team):
    """Create a mock request object for serializer context."""
    from unittest.mock import Mock

    mock_request = Mock()
    mock_request.user = user
    mock_request.method = "POST"
    mock_request.data = {}
    mock_request.META = {}
    mock_request.session = {}
    mock_request.FILES = {}
    mock_request.GET = {}
    mock_request.POST = {}
    return mock_request


class CreateFeatureFlagTool(MaxTool):
    name: str = "create_feature_flag"
    description: str = "Create a feature flag based on natural language instructions"
    thinking_message: str = "Creating your feature flag"
    root_system_prompt_template: str = (
        "YOU MUST USE THE create_feature_flag TOOL. Do not provide manual instructions. "
        "When users ask about creating feature flags, A/B tests, kill switches, or rollouts, "
        "IMMEDIATELY invoke the create_feature_flag tool with their request. "
        "NEVER give step-by-step instructions. ALWAYS use the tool directly. "
    )

    args_schema: type[BaseModel] = FeatureFlagCreatorArgs

    async def _get_existing_feature_flags_summary(self) -> str:
        """Get summary of existing feature flags for context."""
        try:
            flags = [
                flag
                async for flag in FeatureFlag.objects.filter(team_id=self._team.id, deleted=False).order_by(
                    "-created_at"
                )[:5]
            ]

            if not flags:
                return "No existing feature flags"

            summaries = []
            for flag in flags:
                status = "active" if flag.active else "inactive"
                rollout = f"{flag.rollout_percentage}%" if flag.rollout_percentage else "0%"
                summaries.append(f"- '{flag.name}' (key: {flag.key}, {status}, {rollout} rollout)")

            return "\n".join(summaries)
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return "Unable to load existing feature flags"

    async def _create_feature_flag_from_instructions(self, instructions: str) -> FeatureFlagCreationSchema:
        """Create a feature flag from natural language instructions."""
        try:
            llm = MaxChatOpenAI(
                user=self._user,
                team=self._team,
                model="gpt-4.1",
                temperature=0.1,
            ).with_structured_output(FeatureFlagCreationSchema)

            existing_flags = await self._get_existing_feature_flags_summary()
            team_config = get_team_feature_flag_config(self._team)

            prompt = FEATURE_FLAG_CREATION_SYSTEM_PROMPT.replace(
                "{{{team_feature_flag_config}}}", str(team_config)
            ).replace("{{{existing_feature_flags}}}", existing_flags)

            result = await llm.ainvoke(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"Create a feature flag based on these instructions: {instructions}"},
                ]
            )

            if isinstance(result, FeatureFlagCreationSchema):
                return result

            feature_flag_creation_schema = FeatureFlagCreationSchema(
                key="", name="", active=False, filters={"groups": []}
            )
            capture_exception(
                ValueError(f"Feature flag creation returned unexpected output type: {type(result)}"),
                {"team_id": self._team.id, "user_id": self._user.id, "result": str(result)},
            )
            return feature_flag_creation_schema

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return FeatureFlagCreationSchema(key="", name="", active=False, filters={"groups": []})

    async def _arun_impl(self, instructions: str) -> tuple[str, dict[str, Any]]:
        """
        Generate feature flag configuration from natural language instructions.
        """

        try:
            user = self._user
            team = self._team

            result = await self._create_feature_flag_from_instructions(instructions)

            try:
                # Generate key if not provided or if it's empty
                # Priority: use name/description if available, otherwise use instructions
                if not result.key:
                    key_source = result.name or instructions[:50]
                    result.key = await generate_feature_flag_key(key_source, team)

                if not result.key:
                    return "Feature flag must have a key", {
                        "error": "validation_failed",
                        "error_message": "No key could be generated from the feature flag instructions.",
                    }

                flag_data = self._prepare_feature_flag_data(result, team)

                # The mock request is needed so we can re-use the DRF serializer for flag operations.
                # There are some subtleties with creating flags when there's a deleted flag with the same key
                # that we don't want to have to repeat everywhere.
                mock_request = create_mock_request(user, team)
                serializer = FeatureFlagSerializer(
                    data=flag_data,
                    context={
                        "request": mock_request,
                        "team_id": team.id,
                        "project_id": team.project_id,
                    },
                )

                # Validate and create using the serializer (handles deleted flag cleanup)
                await sync_to_async(serializer.is_valid)(raise_exception=True)
                feature_flag = await sync_to_async(serializer.save)()

                return f"Feature flag '{feature_flag.name}' created successfully!", {
                    "flag_id": feature_flag.id,
                    "flag_key": feature_flag.key,
                    "flag_name": feature_flag.name,
                }

            except Exception as validation_error:
                return f"Feature flag validation failed: {str(validation_error)}", {
                    "error": "validation_failed",
                    "error_message": str(validation_error),
                }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return "Failed to create feature flag", {"error": "creation_failed", "details": str(e)}

    def _prepare_feature_flag_data(self, flag_schema: FeatureFlagCreationSchema, team: Team) -> dict[str, Any]:
        """Prepare feature flag data with defaults applied."""
        # Convert schema to dict
        flag_data = flag_schema.model_dump(exclude_unset=True)

        # Note: schema 'name' field maps directly to model 'name' field (contains description)
        # No special handling needed since description field has been removed from schema

        # Get team configuration for defaults
        team_config = get_team_feature_flag_config(team)
        default_settings = team_config.get("default_settings", {})

        # Ensure required fields have defaults, using team config where available
        flag_data.setdefault("active", default_settings.get("active", True))
        flag_data.setdefault("name", "")  # Model field that contains description
        flag_data.setdefault("rollout_percentage", default_settings.get("rollout_percentage", None))
        flag_data.setdefault(
            "ensure_experience_continuity", default_settings.get("ensure_experience_continuity", False)
        )
        flag_data.setdefault("evaluation_runtime", default_settings.get("evaluation_runtime", "all"))

        # Ensure filters field is present (required by FeatureFlag model)
        flag_data.setdefault("filters", {"groups": []})

        # Handle variants: move from top-level to filters.multivariate.variants
        variants = flag_data.pop("variants", None)
        if variants:
            # Ensure filters.multivariate exists
            if "multivariate" not in flag_data["filters"]:
                flag_data["filters"]["multivariate"] = {}

            # Convert variants to the expected format and add to filters.multivariate
            flag_data["filters"]["multivariate"]["variants"] = [
                {
                    "key": variant.get("key", ""),
                    "name": variant.get("name", ""),
                    "rollout_percentage": variant.get("rollout_percentage", 0),
                }
                for variant in variants
            ]

        # Validate rollout percentage is within bounds (0-100)
        if flag_data.get("rollout_percentage") is not None:
            rollout = flag_data["rollout_percentage"]
            if not isinstance(rollout, int | float) or rollout < 0 or rollout > 100:
                flag_data["rollout_percentage"] = 0  # Default to safe value

        return flag_data
