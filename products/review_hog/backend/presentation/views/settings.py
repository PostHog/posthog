from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.review_hog.backend.facade.api import get_review_user_preferences, update_review_user_preferences
from products.review_hog.backend.facade.contracts import ReviewUserPreferences
from products.review_hog.backend.facade.enums import DefaultReviewMode, PreferenceSource, UrgencyThreshold


def _source_field(key: str) -> serializers.ChoiceField:
    return serializers.ChoiceField(
        choices=PreferenceSource.choices,
        help_text=f"Where the effective {key} comes from: 'user' (the user set it), 'project' (the project "
        "default), or 'default' (the built-in default).",
    )


class ReviewPreferenceSourcesSerializer(serializers.Serializer):
    default_review_mode = _source_field("default_review_mode")
    review_drafts = _source_field("review_drafts")
    resolve_comments = _source_field("resolve_comments")
    urgency_threshold = _source_field("urgency_threshold")
    celebrate_clean_reviews = _source_field("celebrate_clean_reviews")
    review_inbox_prs = _source_field("review_inbox_prs")
    stamphog_review_inbox_prs = _source_field("stamphog_review_inbox_prs")


class ReviewProjectDefaultsSerializer(serializers.Serializer):
    urgency_threshold = serializers.ChoiceField(
        choices=UrgencyThreshold.choices,
        help_text="The project's default for the minimum priority a Deep review publishes.",
    )
    celebrate_clean_reviews = serializers.BooleanField(
        help_text="The project's default for the image in a Deep review that finds nothing to raise.",
    )


class ReviewUserSettingsSerializer(serializers.Serializer):
    default_review_mode = serializers.ChoiceField(
        required=False,
        choices=DefaultReviewMode.choices,
        help_text="Automatic reviews of the user's own pull requests in every repository this project reviews: "
        "'follow' (default) uses each repository's rule, 'flash' gives automatic Standard reviews everywhere, and 'off' "
        "turns automatic reviews off everywhere. A choice for one repository wins over this default.",
    )
    review_drafts = serializers.BooleanField(
        required=False,
        help_text="Give the user's draft pull requests automatic reviews. On by default. When off, a draft gets "
        "its first automatic review when it is marked ready for review. Applies to automatic reviews only: an "
        "@posthog review comment and the Review button still review drafts.",
    )
    resolve_comments = serializers.BooleanField(
        required=False,
        help_text="After a Deep review of the user's pull requests is published, run the resolution stage: "
        "triage the unresolved review threads, implement the worth-and-safe fixes on the PR branch, and "
        "reply on every thread. Off by default. Personal only: no project default applies.",
    )
    urgency_threshold = serializers.ChoiceField(
        required=False,
        choices=UrgencyThreshold.choices,
        help_text="Minimum priority a validated Deep review finding needs to be published: 'consider' "
        "publishes everything, 'should_fix' drops consider-level findings, 'must_fix' publishes only "
        "blocking issues. Without the user's own value the project default applies.",
    )
    celebrate_clean_reviews = serializers.BooleanField(
        required=False,
        help_text="Show a fun image in the review comment when a Deep review of the user's pull requests "
        "finds nothing to raise. Without the user's own value the project default applies.",
    )
    review_inbox_prs = serializers.BooleanField(
        required=False,
        help_text="Review the pull requests the agent opens for Inbox reports assigned to the user: "
        "PostHog Review reviews each one and posts its findings to the pull request. Off by default.",
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
        help_text="The project defaults the Deep review preferences fall back to.",
    )
    stamphog_connected = serializers.BooleanField(
        read_only=True,
        help_text="Whether this project has at least one synced, enabled Stamphog repository. When "
        "false, the stamphog_review_inbox_prs toggle has nothing to act on and the UI renders it "
        "disabled with a pointer to connect the Stamphog GitHub App.",
    )


class ReviewUserSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The requesting user's PostHog Review preferences for a project.

    Sibling of the perspective/validator/blind-spots config viewsets: skills control *how* a review
    runs, these preferences control *what gets reviewed* and *how strict publishing is*. Only the
    values the user changed are stored; the response gives the effective values and their source.
    Every row is self-scoped, and the review-hog feature flag controls project access.
    """

    scope_object = "INTERNAL"
    permission_classes = [PostHogFeatureFlagPermission]
    posthog_feature_flag = "review-hog"
    serializer_class = ReviewUserSettingsSerializer

    def _user_id(self) -> int:
        return cast(User, self.request.user).id

    def _response(self, preferences: ReviewUserPreferences) -> Response:
        return Response(ReviewUserSettingsSerializer(preferences).data)

    @extend_schema(
        methods=["GET"],
        responses={
            200: OpenApiResponse(
                response=ReviewUserSettingsSerializer, description="The requesting user's code review preferences."
            ),
        },
        summary="Get the user's code review settings",
        description="Fetch the requesting user's effective code review preferences for this project, and where "
        "each value comes from.",
    )
    @extend_schema(
        methods=["PATCH"],
        request=ReviewUserSettingsSerializer,
        responses={
            200: OpenApiResponse(response=ReviewUserSettingsSerializer, description="The updated settings."),
            400: OpenApiResponse(description="Invalid field value (e.g. unknown urgency threshold)."),
        },
        summary="Update the user's code review settings",
        description="Partially update the requesting user's code review preferences for this project. Only the "
        "provided fields change. A value equal to the inherited one clears the user's own value.",
    )
    # Not named `settings` — that would shadow DRF's `APIView.settings` (its APISettings object).
    @action(detail=False, methods=["GET", "PATCH"], url_path="settings", url_name="settings")
    def user_settings(self, request: Request, **kwargs) -> Response:
        if request.method == "PATCH":
            serializer = ReviewUserSettingsSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            return self._response(
                update_review_user_preferences(self.team_id, self._user_id(), serializer.validated_data)
            )
        return self._response(get_review_user_preferences(self.team_id, self._user_id()))
