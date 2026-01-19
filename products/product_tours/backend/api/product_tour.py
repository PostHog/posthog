import logging
from typing import Any, cast

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

from langchain_core.messages import HumanMessage, SystemMessage
from loginas.utils import is_impersonated_session
from nanoid import generate
from pydantic import BaseModel, Field
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.feature_flag import FeatureFlagSerializer, MinimalFeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_token
from posthog.auth import TemporaryTokenAuthentication
from posthog.constants import PRODUCT_TOUR_TARGETING_FLAG_PREFIX
from posthog.exceptions import generate_exception_response
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.surveys.survey import Survey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.utils_cors import cors_response

from products.product_tours.backend.models import ProductTour
from products.product_tours.backend.prompts import TOUR_GENERATION_SYSTEM_PROMPT, TOUR_GENERATION_USER_PROMPT

from ee.hogai.llm import MaxChatAnthropic

logger = logging.getLogger(__name__)

TOUR_GENERATION_MODEL = "claude-haiku-4-5"


class TourStepContent(BaseModel):
    """A single step in the generated tour."""

    selector: str = Field(description="The CSS selector for this step's target element")
    title: str = Field(description="Short, catchy title for this step (2-5 words)")
    description: str = Field(description="Helpful description explaining what to do and why (1-2 sentences)")


class TourGenerationResponse(BaseModel):
    """Structured response from the tour generation LLM."""

    name: str = Field(description="A short, descriptive name for this tour (3-6 words)")
    steps: list[TourStepContent] = Field(description="List of tour steps with content for each element")


class SuggestedElement(BaseModel):
    """An element suggested for highlighting in the tour."""

    selector: str = Field(description="The CSS selector for this element")
    reason: str = Field(description="Why this element is important for the tour (1 sentence)")


class TourSuggestionResponse(BaseModel):
    """Structured response from the tour suggestion LLM."""

    name: str = Field(description="Suggested tour name (3-6 words)")
    goal: str = Field(description="What users will learn from this tour (1 sentence)")
    elements: list[SuggestedElement] = Field(description="3-5 elements to highlight, in order")


class ProductTourSerializer(serializers.ModelSerializer):
    """Read-only serializer for ProductTour."""

    internal_targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    feature_flag_key = serializers.SerializerMethodField()
    targeting_flag_filters = serializers.SerializerMethodField()

    class Meta:
        model = ProductTour
        fields = [
            "id",
            "name",
            "description",
            "internal_targeting_flag",
            "feature_flag_key",
            "targeting_flag_filters",
            "content",
            "auto_launch",
            "start_date",
            "end_date",
            "created_at",
            "created_by",
            "updated_at",
            "archived",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]

    def get_feature_flag_key(self, tour: ProductTour) -> str | None:
        if tour.internal_targeting_flag:
            return tour.internal_targeting_flag.key
        return None

    def get_targeting_flag_filters(self, tour: ProductTour) -> dict | None:
        """Return the targeting flag filters, excluding the base exclusion properties."""
        if not tour.internal_targeting_flag:
            return None

        filters = tour.internal_targeting_flag.filters
        if not filters or "groups" not in filters:
            return None

        # Filter out the base exclusion properties to return only user-defined targeting
        tour_key = str(tour.id)
        base_property_keys = {
            f"$product_tour_shown/{tour_key}",
            f"$product_tour_completed/{tour_key}",
            f"$product_tour_dismissed/{tour_key}",
        }

        cleaned_groups = []
        for group in filters.get("groups", []):
            properties = group.get("properties", [])
            user_properties = [p for p in properties if p.get("key") not in base_property_keys]
            if user_properties:
                cleaned_groups.append({**group, "properties": user_properties})

        if not cleaned_groups:
            return None

        return {"groups": cleaned_groups}


class ProductTourSerializerCreateUpdateOnly(serializers.ModelSerializer):
    """Serializer for creating and updating ProductTour."""

    internal_targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    targeting_flag_filters = serializers.JSONField(required=False, write_only=True, allow_null=True)

    class Meta:
        model = ProductTour
        fields = [
            "id",
            "name",
            "description",
            "internal_targeting_flag",
            "targeting_flag_filters",
            "content",
            "auto_launch",
            "start_date",
            "end_date",
            "created_at",
            "created_by",
            "updated_at",
            "archived",
        ]
        read_only_fields = ["id", "internal_targeting_flag", "created_at", "created_by", "updated_at"]

    def validate_content(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Content must be an object")

        if value.get("type") == "announcement":
            steps = value.get("steps") or []
            if len(steps) != 1:
                raise serializers.ValidationError("Announcements must have exactly 1 step.")

        return value

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        team = self.context["get_team"]()

        validated_data["team"] = team
        validated_data["created_by"] = request.user

        instance = super().create(validated_data)

        # Only create internal targeting flag if auto_launch is enabled
        if instance.auto_launch:
            self._create_internal_targeting_flag(instance)

        # Create linked surveys for any survey steps
        self._sync_survey_steps(instance)

        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        # Extract targeting_flag_filters before parent update
        # Use sentinel to distinguish "not provided" from "explicitly null"
        _NOT_PROVIDED = object()
        targeting_flag_filters = validated_data.pop("targeting_flag_filters", _NOT_PROVIDED)

        # Track what changed
        start_date_changed = "start_date" in validated_data and validated_data["start_date"] != instance.start_date
        end_date_changed = "end_date" in validated_data and validated_data["end_date"] != instance.end_date
        archived_changed = "archived" in validated_data and validated_data["archived"] != instance.archived
        auto_launch_changed = "auto_launch" in validated_data and validated_data["auto_launch"] != instance.auto_launch
        auto_launch_enabled = validated_data.get("auto_launch", instance.auto_launch)

        # Track displayFrequency before update for flag refresh
        old_display_frequency = instance.content.get("displayFrequency") if instance.content else None

        # Store previous content for survey step cleanup
        previous_content = instance.content.copy() if instance.content else None

        instance = super().update(instance, validated_data)

        # Detect displayFrequency change
        new_display_frequency = instance.content.get("displayFrequency") if instance.content else None
        display_frequency_changed = old_display_frequency != new_display_frequency

        # Handle auto_launch changes
        if auto_launch_changed:
            if auto_launch_enabled:
                if not instance.internal_targeting_flag:
                    # auto_launch turned ON and no flag exists - create one
                    self._create_internal_targeting_flag(instance)
                else:
                    # auto_launch turned ON and flag exists - update its state
                    self._update_internal_targeting_flag_state(instance)
            elif instance.internal_targeting_flag:
                # auto_launch turned OFF - deactivate the flag
                instance.internal_targeting_flag.active = False
                instance.internal_targeting_flag.save(update_fields=["active"])
        elif start_date_changed or end_date_changed or archived_changed:
            # Only update flag state if auto_launch is enabled
            if instance.auto_launch:
                self._update_internal_targeting_flag_state(instance)

        # Update targeting flag filters if explicitly provided (including null to reset)
        if targeting_flag_filters is not _NOT_PROVIDED and instance.internal_targeting_flag:
            self._update_targeting_flag_filters(instance, targeting_flag_filters)
        elif display_frequency_changed and instance.internal_targeting_flag:
            # displayFrequency changed but targeting_flag_filters wasn't provided - refresh base properties
            self._refresh_targeting_flag_base_properties(instance)

        # Sync linked surveys for any survey steps (create/update/end as needed)
        self._sync_survey_steps(instance, previous_content)

        return instance

    def _get_base_exclusion_properties(self, instance: ProductTour) -> list:
        """Get the base exclusion properties for the internal targeting flag based on display frequency."""
        tour_key = str(instance.id)
        display_frequency = instance.content.get("displayFrequency") if instance.content else None

        # "always" - no exclusions, always show
        if display_frequency == "always":
            return []

        # "show_once" - exclude if shown
        if display_frequency == "show_once":
            return [
                {
                    "key": f"$product_tour_shown/{tour_key}",
                    "type": "person",
                    "value": "is_not_set",
                    "operator": "is_not_set",
                },
            ]

        # "until_interacted" or default - exclude if completed or dismissed
        return [
            {
                "key": f"$product_tour_completed/{tour_key}",
                "type": "person",
                "value": "is_not_set",
                "operator": "is_not_set",
            },
            {
                "key": f"$product_tour_dismissed/{tour_key}",
                "type": "person",
                "value": "is_not_set",
                "operator": "is_not_set",
            },
        ]

    def _create_internal_targeting_flag(self, instance: ProductTour) -> None:
        """Create the internal targeting flag for a product tour."""
        random_id = generate("0123456789abcdef", 8)
        flag_key = f"{PRODUCT_TOUR_TARGETING_FLAG_PREFIX}{slugify(instance.name)}-{random_id}"

        base_properties = self._get_base_exclusion_properties(instance)
        filters = {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": base_properties,
                }
            ]
        }

        flag_data = {
            "key": flag_key,
            "name": f"Product Tour: {instance.name}",
            "filters": filters,
            "active": bool(instance.start_date) and not instance.end_date and not instance.archived,
            "creation_context": "product_tours",
        }

        # Use self.context to pass through project_id and other context
        flag_serializer = FeatureFlagSerializer(
            data=flag_data,
            context=self.context,
        )
        flag_serializer.is_valid(raise_exception=True)
        flag = flag_serializer.save()

        instance.internal_targeting_flag = flag
        instance.save(update_fields=["internal_targeting_flag"])

    def _update_internal_targeting_flag_state(self, instance: ProductTour) -> None:
        """Update the internal targeting flag active state based on tour state."""
        flag = instance.internal_targeting_flag
        if not flag:
            return

        should_be_active = bool(instance.start_date) and not instance.end_date and not instance.archived
        if flag.active != should_be_active:
            flag.active = should_be_active
            flag.save(update_fields=["active"])

    def _update_targeting_flag_filters(self, instance: ProductTour, new_filters: dict | None) -> None:
        """Update the internal targeting flag's filters with additional user targeting conditions.

        If new_filters is None, resets to base filters only (no additional user targeting).
        """
        flag = instance.internal_targeting_flag
        if not flag:
            return

        # Get base exclusion properties based on display frequency
        base_properties = self._get_base_exclusion_properties(instance)

        # If new_filters is None, reset to base filters only
        if new_filters is None:
            flag.filters = {
                "groups": [
                    {
                        "variant": "",
                        "rollout_percentage": 100,
                        "properties": base_properties,
                    }
                ]
            }
            flag.save(update_fields=["filters"])
            return

        # Merge new filters with base properties
        new_groups = new_filters.get("groups", [])
        merged_groups = []

        for group in new_groups:
            existing_properties = group.get("properties", [])
            # Add base properties to each group
            merged_group = {
                **group,
                "properties": base_properties + existing_properties,
            }
            merged_groups.append(merged_group)

        # If no groups provided, use a default group with just the base properties
        if not merged_groups:
            merged_groups = [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": base_properties,
                }
            ]

        # Update the flag's filters
        flag.filters = {"groups": merged_groups}
        flag.save(update_fields=["filters"])

    def _refresh_targeting_flag_base_properties(self, instance: ProductTour) -> None:
        """Refresh base exclusion properties on targeting flag, preserving user targeting filters."""
        flag = instance.internal_targeting_flag
        if not flag:
            return

        tour_key = str(instance.id)
        base_exclusion_keys = {
            f"$product_tour_shown/{tour_key}",
            f"$product_tour_completed/{tour_key}",
            f"$product_tour_dismissed/{tour_key}",
        }

        current_groups = flag.filters.get("groups", [])
        user_groups = [
            {**g, "properties": [p for p in g.get("properties", []) if p.get("key") not in base_exclusion_keys]}
            for g in current_groups
        ]

        has_user_properties = any(g.get("properties") for g in user_groups)
        self._update_targeting_flag_filters(instance, {"groups": user_groups} if has_user_properties else None)

    def _sync_survey_steps(self, instance: ProductTour, previous_content: dict | None = None) -> bool:
        """Create or update linked surveys for any survey steps in the tour.

        Also ends (sets end_date) any surveys that are no longer referenced by steps.

        Returns True if any changes were made to the tour content.
        """
        from django.utils import timezone

        request = self.context["request"]
        content = instance.content or {}
        steps = content.get("steps", [])
        content_changed = False

        # Track which survey IDs are still in use
        active_survey_ids: set[str] = set()

        for i, step in enumerate(steps):
            survey_config = step.get("survey")
            if not survey_config:
                continue

            linked_survey_id = step.get("linkedSurveyId")
            question_text = survey_config.get("questionText", "")
            question_type = survey_config.get("type", "open")

            # Build the survey question
            survey_question: dict[str, Any] = {
                "type": question_type,
                "question": question_text,
            }

            # Add rating-specific fields
            if question_type == "rating":
                survey_question["scale"] = survey_config.get("scale", 5)
                survey_question["display"] = survey_config.get("display", "emoji")
                survey_question["skipSubmitButton"] = True  # Auto-submit on selection
                if survey_config.get("lowerBoundLabel"):
                    survey_question["lowerBoundLabel"] = survey_config["lowerBoundLabel"]
                if survey_config.get("upperBoundLabel"):
                    survey_question["upperBoundLabel"] = survey_config["upperBoundLabel"]

            survey_name = f"{instance.name} - Step {i + 1} Survey"

            if linked_survey_id:
                # Update existing survey
                try:
                    survey = Survey.objects.get(id=linked_survey_id, team=instance.team)
                    survey.name = survey_name
                    survey.questions = [survey_question]
                    # Ensure appearance has hideCancelButton set
                    survey.appearance = survey.appearance or {}
                    survey.appearance["hideCancelButton"] = True
                    survey.appearance["displayThankYouMessage"] = False
                    survey.appearance["position"] = "middle_center"
                    # Sync start_date and end_date from the tour
                    # If tour is archived, end the survey now
                    survey.start_date = instance.start_date
                    survey.end_date = (
                        instance.end_date if not instance.archived else (instance.end_date or timezone.now())
                    )
                    survey.enable_partial_responses = False  # Single question, no partial responses
                    survey.save(
                        update_fields=[
                            "name",
                            "questions",
                            "appearance",
                            "start_date",
                            "end_date",
                            "enable_partial_responses",
                            "updated_at",
                        ]
                    )
                    active_survey_ids.add(linked_survey_id)
                    # Ensure question ID is stored on step (for backwards compatibility)
                    if not step.get("linkedSurveyQuestionId") and survey.questions:
                        step["linkedSurveyQuestionId"] = survey.questions[0].get("id")
                        content_changed = True
                except Survey.DoesNotExist:
                    # Survey was deleted, create a new one
                    linked_survey_id = None

            if not linked_survey_id:
                # Create new survey
                # Use appearance with hideCancelButton since tour surveys shouldn't be dismissible
                survey_appearance = {
                    "position": "middle_center",
                    "displayThankYouMessage": False,
                    "hideCancelButton": True,
                }
                survey = Survey.objects.create(
                    team=instance.team,
                    name=survey_name,
                    type="api",  # API type since we'll trigger it programmatically
                    questions=[survey_question],
                    appearance=survey_appearance,
                    start_date=instance.start_date,  # Launch with the tour
                    end_date=instance.end_date,
                    created_by=request.user if hasattr(request, "user") else None,
                    enable_partial_responses=False,  # Single question, no partial responses
                )
                step["linkedSurveyId"] = str(survey.id)
                # Store the question ID for SDK event tracking
                step["linkedSurveyQuestionId"] = survey.questions[0].get("id") if survey.questions else None
                active_survey_ids.add(str(survey.id))
                content_changed = True

        # End any surveys that were previously linked but are no longer in use
        if previous_content:
            previous_steps = previous_content.get("steps", [])
            for prev_step in previous_steps:
                prev_survey_id = prev_step.get("linkedSurveyId")
                if prev_survey_id and prev_survey_id not in active_survey_ids:
                    # This survey is no longer referenced - end it
                    try:
                        survey = Survey.objects.get(id=prev_survey_id, team=instance.team)
                        if not survey.end_date:
                            survey.end_date = timezone.now()
                            survey.save(update_fields=["end_date", "updated_at"])
                    except Survey.DoesNotExist:
                        pass

        if content_changed:
            instance.content = content
            instance.save(update_fields=["content", "updated_at"])

        return content_changed


class ProductTourViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "product_tour"
    queryset = ProductTour.objects.select_related("internal_targeting_flag", "created_by").all()
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "description"]
    authentication_classes = [TemporaryTokenAuthentication]

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.request.method in ("POST", "PATCH"):
            return ProductTourSerializerCreateUpdateOnly
        return ProductTourSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id)

    def perform_destroy(self, instance: ProductTour) -> None:
        """Soft delete: archive the tour instead of deleting."""
        from django.utils import timezone

        # Delete the internal targeting flag
        if instance.internal_targeting_flag:
            instance.internal_targeting_flag.delete()
            instance.internal_targeting_flag = None

        # End any linked surveys
        content = instance.content or {}
        for step in content.get("steps", []):
            linked_survey_id = step.get("linkedSurveyId")
            if linked_survey_id:
                try:
                    survey = Survey.objects.get(id=linked_survey_id, team=instance.team)
                    if not survey.end_date:
                        survey.end_date = timezone.now()
                        survey.save(update_fields=["end_date", "updated_at"])
                except Survey.DoesNotExist:
                    pass

        instance.archived = True
        instance.save(update_fields=["archived", "internal_targeting_flag", "updated_at"])

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, self.request.user),
            was_impersonated=is_impersonated_session(self.request),
            item_id=str(instance.id),
            scope="ProductTour",
            activity="deleted",
            detail=Detail(name=instance.name),
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=204)

    @action(detail=False, methods=["POST"])
    def generate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Generate tour step content using AI."""
        screenshot = request.data.get("screenshot")
        elements = request.data.get("elements", [])
        goal = request.data.get("goal", "")

        if not elements:
            return Response(
                {"error": "No elements provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Goal is optional - AI will infer from context if not provided

        if not getattr(settings, "ANTHROPIC_API_KEY", None):
            return Response(
                {"error": "ANTHROPIC_API_KEY not configured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Format elements for the prompt
        elements_text = "\n".join(
            f"{i + 1}. Selector: `{el.get('selector', 'unknown')}`\n"
            f"   Tag: {el.get('tag', 'unknown')}\n"
            f"   Text: {el.get('text', '')[:100] if el.get('text') else 'N/A'}\n"
            f"   Attributes: {el.get('attributes', {})}"
            for i, el in enumerate(elements)
        )

        user_prompt = TOUR_GENERATION_USER_PROMPT.format(
            goal=goal,
            elements=elements_text,
            element_count=len(elements),
        )

        try:
            llm = MaxChatAnthropic(
                model=TOUR_GENERATION_MODEL,
                user=cast(User, request.user),
                team=self.team,
                inject_context=False,
                billable=False,
                # TODO: add the API manually here in case it doesn't work
                # api_key="add-api-key-here",
            )

            # Use structured output for reliable JSON parsing
            structured_llm = llm.with_structured_output(TourGenerationResponse)

            # Build message content
            message_content: list[str | dict[str, Any]] = [{"type": "text", "text": user_prompt}]

            if screenshot:
                message_content.insert(
                    0,
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{screenshot}"},
                    },
                )

            messages = [
                SystemMessage(content=TOUR_GENERATION_SYSTEM_PROMPT),
                HumanMessage(content=message_content),
            ]

            result = cast(TourGenerationResponse, structured_llm.invoke(messages))

            # Convert to TipTap format
            steps = []
            for step in result.steps:
                tiptap_content = {
                    "type": "doc",
                    "content": [
                        {
                            "type": "heading",
                            "attrs": {"level": 1},
                            "content": [{"type": "text", "text": step.title}],
                        },
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": step.description}],
                        },
                    ],
                }
                steps.append({"selector": step.selector, "content": tiptap_content})

            return Response({"name": result.name, "steps": steps})

        except Exception:
            logger.exception("Error generating tour content")
            return Response(
                {"error": "An internal error occurred while generating tour content."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProductTourAPISerializer(serializers.ModelSerializer):
    """
    Serializer for the exposed /api/product_tours endpoint, to be used in posthog-js.
    Only exposes fields needed by the SDK, no sensitive data.
    """

    internal_targeting_flag_key = serializers.CharField(source="internal_targeting_flag.key", read_only=True)
    steps = serializers.SerializerMethodField()
    conditions = serializers.SerializerMethodField()
    appearance = serializers.SerializerMethodField()
    display_frequency = serializers.SerializerMethodField()

    class Meta:
        model = ProductTour
        fields = [
            "id",
            "name",
            "internal_targeting_flag_key",
            "steps",
            "conditions",
            "appearance",
            "display_frequency",
            "auto_launch",
            "start_date",
            "end_date",
        ]
        read_only_fields = fields

    def get_steps(self, tour: ProductTour) -> list:
        return tour.content.get("steps", []) if tour.content else []

    def get_conditions(self, tour: ProductTour) -> dict | None:
        return tour.content.get("conditions") if tour.content else None

    def get_appearance(self, tour: ProductTour) -> dict | None:
        return tour.content.get("appearance") if tour.content else None

    def get_display_frequency(self, tour: ProductTour) -> str | None:
        return tour.content.get("displayFrequency") if tour.content else None


def get_product_tours_response(team: Team) -> dict:
    """Get active product tours for a team."""
    tours = ProductTourAPISerializer(
        ProductTour.objects.filter(
            team__project_id=team.project_id,
            archived=False,
            start_date__isnull=False,
        ).select_related("internal_targeting_flag"),
        many=True,
    ).data

    return {"product_tours": tours}


@csrf_exempt
def product_tours(request):
    token = get_token(None, request)

    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))

    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "product_tours",
                "API key not provided. You can find your project API key in your PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    team = Team.objects.get_team_from_cache_or_token(token)
    if team is None:
        return cors_response(
            request,
            generate_exception_response(
                "product_tours",
                "Project API key invalid. You can find your project API key in your PostHog project settings.",
                type="authentication_error",
                code="invalid_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    return cors_response(request, JsonResponse(get_product_tours_response(team)))
