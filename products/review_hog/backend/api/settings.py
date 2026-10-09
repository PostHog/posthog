import logging
from typing import cast

from django.conf import settings
from django.db import transaction

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.review_hog.backend.models import ReviewProjectSettings, ReviewUserSettings
from products.review_hog.backend.preferences import (
    PREFERENCE_KEYS,
    DefaultReviewMode,
    PreferenceSource,
    ReviewPreferences,
    UrgencyThreshold,
)
from products.review_hog.backend.reviewer.lazy_seed import seed_canonicals_tolerantly, sync_canonical_authoring
from products.stamphog.backend.facade.api import has_reviewable_repo_config

logger = logging.getLogger(__name__)


def has_internal_features(team_id: int) -> bool:
    """Whether a project gets Flash and the automation settings: only the first configured ReviewHog team."""
    return bool(settings.REVIEWHOG_TEAM_IDS and team_id == settings.REVIEWHOG_TEAM_IDS[0])


def _source_field(key: str) -> serializers.ChoiceField:
    return serializers.ChoiceField(
        choices=PreferenceSource.choices,
        help_text=f"Where the effective {key} comes from: 'user' (the user set it), 'project' (the project "
        "default), or 'default' (the built-in default).",
    )


class ReviewPreferenceSourcesSerializer(serializers.Serializer):
    default_review_mode = _source_field("default_review_mode")
    resolve_comments = _source_field("resolve_comments")
    urgency_threshold = _source_field("urgency_threshold")
    celebrate_clean_reviews = _source_field("celebrate_clean_reviews")
    review_inbox_prs = _source_field("review_inbox_prs")
    stamphog_review_inbox_prs = _source_field("stamphog_review_inbox_prs")


class ReviewProjectDefaultsSerializer(serializers.Serializer):
    urgency_threshold = serializers.ChoiceField(
        choices=UrgencyThreshold.choices,
        help_text="The project's default for the minimum priority a Full review publishes.",
    )
    celebrate_clean_reviews = serializers.BooleanField(
        help_text="The project's default for the image in a Full review that finds nothing to raise.",
    )


class ReviewUserSettingsSerializer(serializers.Serializer):
    default_review_mode = serializers.ChoiceField(
        required=False,
        choices=DefaultReviewMode.choices,
        help_text="Automatic reviews of the user's own pull requests in every repository this project reviews: "
        "'follow' (default) uses each repository's rule, 'flash' gives automatic Flash everywhere, and 'off' "
        "turns automatic Flash off everywhere. A choice for one repository wins over this default.",
    )
    resolve_comments = serializers.BooleanField(
        required=False,
        help_text="After a Full review of the user's pull requests is published, run the resolution stage: "
        "triage the unresolved review threads, implement the worth-and-safe fixes on the PR branch, and "
        "reply on every thread. Off by default. Personal only: no project default applies.",
    )
    urgency_threshold = serializers.ChoiceField(
        required=False,
        choices=UrgencyThreshold.choices,
        help_text="Minimum priority a validated Full review finding needs to be published: 'consider' "
        "publishes everything, 'should_fix' drops consider-level findings, 'must_fix' publishes only "
        "blocking issues. Without the user's own value the project default applies.",
    )
    celebrate_clean_reviews = serializers.BooleanField(
        required=False,
        help_text="Show a fun image in the review comment when a Full review of the user's pull requests "
        "finds nothing to raise. Without the user's own value the project default applies.",
    )
    review_inbox_prs = serializers.BooleanField(
        required=False,
        help_text="Review the pull requests the agent opens for Inbox reports assigned to the user: "
        "ReviewHog reviews each one and posts its findings to the pull request. Off by default.",
    )
    stamphog_review_inbox_prs = serializers.BooleanField(
        required=False,
        help_text="Also have hosted Stamphog review those same Inbox pull requests: an approve-first "
        "review that posts a real GitHub approval when the change passes, and a comment when it "
        "doesn't. Only takes effect when the project has a synced, enabled Stamphog repository "
        "(see stamphog_connected).",
    )
    sources = ReviewPreferenceSourcesSerializer(
        read_only=True,
        help_text="Where each effective value comes from. A value equal to the inherited one is never "
        "stored, so writing the project default or the built-in default makes the source follow it again.",
    )
    project_defaults = ReviewProjectDefaultsSerializer(
        read_only=True,
        source="project",
        help_text="The project defaults the Full review preferences fall back to.",
    )
    show_internal_features = serializers.SerializerMethodField(
        help_text="Whether to show Flash mode and settings for automatic, label-triggered, and Inbox reviews.",
    )
    stamphog_connected = serializers.SerializerMethodField(
        help_text="Whether this project has at least one synced, enabled Stamphog repository. When "
        "false, the stamphog_review_inbox_prs toggle has nothing to act on and the UI renders it "
        "disabled with a pointer to connect the Stamphog GitHub App.",
    )

    def _team_id(self) -> int:
        return self.context["team_id"]

    @extend_schema_field(serializers.BooleanField())
    def get_show_internal_features(self, instance: ReviewPreferences) -> bool:
        return has_internal_features(self._team_id())

    @extend_schema_field(serializers.BooleanField())
    def get_stamphog_connected(self, instance: ReviewPreferences) -> bool:
        if not has_internal_features(self._team_id()):
            return False
        # This reads the stamphog product DB, which can fail fast on its own circuit breaker. An
        # informational UI flag must not fail the settings endpoint, so fall back to False.
        try:
            return has_reviewable_repo_config(self._team_id())
        except Exception:
            logger.exception("review_hog_stamphog_connected_check_failed")
            return False


class ReviewUserSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The requesting user's ReviewHog preferences for a project.

    Sibling of the perspective/validator/blind-spots config viewsets: skills control *how* a review
    runs, these preferences control *what gets reviewed* and *how strict publishing is*. Only the
    values the user changed are stored; the response gives the effective values and their source.
    Every row is self-scoped, and the review-hog feature flag controls project access.
    """

    scope_object = "INTERNAL"
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = "review-hog"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewUserSettings.objects.unscoped()
    serializer_class = ReviewUserSettingsSerializer

    def _user_id(self) -> int:
        return cast(User, self.request.user).id

    def _save_changes(self, team_id: int, changes: dict) -> ReviewPreferences:
        # Resolve a raw environment URL id to its root team once: `for_team` canonicalizes its filter
        # but not the create kwargs, and mismatched ids mean a never-matching get plus 500s on re-read.
        rows = ReviewUserSettings.objects.for_team(team_id, canonical=True)
        with transaction.atomic():
            row, _created = rows.get_or_create(team_id=team_id, user_id=self._user_id())
            # The lock keeps two concurrent edits of different keys from losing one of them.
            row = rows.select_for_update().get(id=row.id)
            current = ReviewPreferences.resolve(row.preferences, ReviewProjectSettings.load(team_id).defaults)
            row.preferences = current.with_changes(changes)
            row.save(update_fields=["preferences", "updated_at"])
        return ReviewUserSettings.load_preferences(team_id, self._user_id())

    def _response(self, team_id: int, preferences: ReviewPreferences) -> Response:
        return Response(ReviewUserSettingsSerializer(preferences, context={"team_id": team_id}).data)

    @extend_schema(
        methods=["GET"],
        responses={
            200: OpenApiResponse(
                response=ReviewUserSettingsSerializer, description="The requesting user's ReviewHog preferences."
            ),
        },
        summary="Get the user's ReviewHog settings",
        description="Fetch the requesting user's effective ReviewHog preferences for this project, and where "
        "each value comes from.",
    )
    @extend_schema(
        methods=["PATCH"],
        request=ReviewUserSettingsSerializer,
        responses={
            200: OpenApiResponse(response=ReviewUserSettingsSerializer, description="The updated settings."),
            400: OpenApiResponse(description="Invalid field value (e.g. unknown urgency threshold)."),
        },
        summary="Update the user's ReviewHog settings",
        description="Partially update the requesting user's ReviewHog preferences for this project. Only the "
        "provided fields change. A value equal to the inherited one clears the user's own value.",
    )
    # Not named `settings` — that would shadow DRF's `APIView.settings` (its APISettings object).
    @action(detail=False, methods=["GET", "PATCH"], url_path="settings", url_name="settings")
    def user_settings(self, request: Request, **kwargs) -> Response:
        team_id = resolve_effective_team_id(self.team_id)
        if request.method == "PATCH":
            serializer = ReviewUserSettingsSerializer(data=request.data, partial=True, context={"team_id": team_id})
            serializer.is_valid(raise_exception=True)
            changes = {
                key: serializer.validated_data[key] for key in PREFERENCE_KEYS if key in serializer.validated_data
            }
            return self._response(team_id, self._save_changes(team_id, changes))
        # Seed the authoring companion before any review has run: the "Create your own …" tasks
        # `skill-get` it over MCP, and this settings GET is the Code review tab's always-called
        # endpoint. `team_id` is already the effective (root) team, the same team the review runs
        # under, so the skill lands where the sandbox agent's `skill-get` will look.
        seed_canonicals_tolerantly(team_id, sync_canonical_authoring)
        return self._response(team_id, ReviewUserSettings.load_preferences(team_id, self._user_id()))
