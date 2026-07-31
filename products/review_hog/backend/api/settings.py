import logging

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.scoping.manager import resolve_effective_team_id

from products.review_hog.backend.models import ReviewUserSettings
from products.review_hog.backend.reviewer.lazy_seed import seed_canonicals_tolerantly, sync_canonical_authoring
from products.stamphog.backend.facade.api import has_reviewable_repo_config

logger = logging.getLogger(__name__)


class ReviewUserSettingsSerializer(serializers.ModelSerializer):
    review_inbox_prs = serializers.BooleanField(
        required=False,
        help_text="Automatically review pull requests opened by self-driving implementations from the "
        "user's Inbox: ReviewHog reviews each one and posts its findings to the pull request.",
    )
    stamphog_review_inbox_prs = serializers.BooleanField(
        required=False,
        help_text="Also have hosted Stamphog review those same Inbox pull requests: an approve-first "
        "review that posts a real GitHub approval when the change passes, and a comment when it "
        "doesn't. Only takes effect when the project has a synced, enabled Stamphog repository "
        "(see stamphog_connected).",
    )
    review_labeled_prs = serializers.BooleanField(
        required=False,
        help_text="Review the user's pull requests when the trigger label is added on GitHub. "
        "On by default; turning it off makes the label trigger skip PRs this user authored.",
    )
    urgency_threshold = serializers.ChoiceField(
        required=False,
        choices=ReviewUserSettings.UrgencyThreshold.choices,
        help_text="Minimum priority a validated finding needs to be published: 'consider' (default) "
        "publishes everything, 'should_fix' drops consider-level findings, 'must_fix' publishes only "
        "blocking issues.",
    )
    can_trigger_reviews = serializers.SerializerMethodField(
        help_text="Whether reviews can be started from this project's Code review page (the UI trigger "
        "is limited to the designated ReviewHog team while the product is in alpha).",
    )
    stamphog_connected = serializers.SerializerMethodField(
        help_text="Whether this project has at least one synced, enabled Stamphog repository. When "
        "false, the stamphog_review_inbox_prs toggle has nothing to act on and the UI renders it "
        "disabled with a pointer to connect the Stamphog GitHub App.",
    )

    class Meta:
        model = ReviewUserSettings
        fields = [
            "review_inbox_prs",
            "stamphog_review_inbox_prs",
            "review_labeled_prs",
            "urgency_threshold",
            "can_trigger_reviews",
            "stamphog_connected",
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_can_trigger_reviews(self, instance: ReviewUserSettings) -> bool:
        return bool(settings.REVIEWHOG_TEAM_ID) and instance.team_id == settings.REVIEWHOG_TEAM_ID

    @extend_schema_field(serializers.BooleanField())
    def get_stamphog_connected(self, instance: ReviewUserSettings) -> bool:
        # Fail soft: this is an informational UI flag read from the stamphog product DB (a separate
        # database behind a fail-fast circuit breaker), and it must not be able to take the whole
        # settings endpoint down with it. False is the safe degradation — the toggle renders
        # disabled until the read recovers.
        try:
            return has_reviewable_repo_config(instance.team_id)
        except Exception:
            logger.exception("review_hog_stamphog_connected_check_failed")
            return False


class ReviewUserSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The requesting user's ReviewHog settings for a project (one row, created on first read).

    Sibling of the perspective/validator/blind-spots config viewsets: skills control *how* a review
    runs, this controls *what gets reviewed* (trigger opt-outs) and *how strict publishing is*
    (urgency threshold). Per-user like the skill configs — the workflow reads the PR author's row.
    Deliberately not staff-gated (the alpha gate is UI visibility only): every row is self-scoped.
    """

    scope_object = "INTERNAL"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewUserSettings.objects.unscoped()
    serializer_class = ReviewUserSettingsSerializer

    def _get_or_create(self, request: Request) -> ReviewUserSettings:
        # Resolve a raw environment URL id to its root team once: `for_team` canonicalizes its filter
        # but not the create kwargs, and mismatched ids mean a never-matching get plus 500s on re-read.
        team_id = resolve_effective_team_id(self.team_id)
        instance, _created = ReviewUserSettings.objects.for_team(team_id, canonical=True).get_or_create(
            team_id=team_id, user_id=request.user.id
        )
        return instance

    @extend_schema(
        methods=["GET"],
        responses={
            200: OpenApiResponse(
                response=ReviewUserSettingsSerializer, description="The requesting user's ReviewHog settings."
            ),
        },
        summary="Get the user's ReviewHog settings",
        description="Fetch the requesting user's ReviewHog settings for this project, creating the row "
        "with defaults on first read.",
    )
    @extend_schema(
        methods=["PATCH"],
        request=ReviewUserSettingsSerializer,
        responses={
            200: OpenApiResponse(response=ReviewUserSettingsSerializer, description="The updated settings."),
            400: OpenApiResponse(description="Invalid field value (e.g. unknown urgency threshold)."),
        },
        summary="Update the user's ReviewHog settings",
        description="Partially update the requesting user's ReviewHog settings for this project. Only the "
        "provided fields change.",
    )
    # Not named `settings` — that would shadow DRF's `APIView.settings` (its APISettings object).
    @action(detail=False, methods=["GET", "PATCH"], url_path="settings", url_name="settings")
    def user_settings(self, request: Request, **kwargs) -> Response:
        instance = self._get_or_create(request)
        if request.method == "PATCH":
            serializer = ReviewUserSettingsSerializer(instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        # Seed the authoring companion before any review has run: the "Create your own …" tasks
        # `skill-get` it over MCP, and this settings GET is the Code review tab's always-called
        # endpoint. `instance.team_id` is already the effective (root) team — the same team the
        # review runs under, so the skill lands where the sandbox agent's `skill-get` will look.
        seed_canonicals_tolerantly(instance.team_id, sync_canonical_authoring)
        return Response(ReviewUserSettingsSerializer(instance).data)
