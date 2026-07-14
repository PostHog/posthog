import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.scoping.manager import resolve_effective_team_id

from products.review_hog.backend.models import ReviewUserSettings
from products.review_hog.backend.reviewer.lazy_seed import seed_canonicals_tolerantly, sync_canonical_authoring

logger = logging.getLogger(__name__)


class ReviewUserSettingsSerializer(serializers.ModelSerializer):
    review_inbox_prs = serializers.BooleanField(
        required=False,
        help_text="Automatically review pull requests opened by PostHog agents from the user's Inbox. "
        "Stored but not consumed yet — the Inbox auto-review trigger is not built.",
    )
    review_labeled_prs = serializers.BooleanField(
        required=False,
        help_text="Review the user's pull requests when the trigger label is added on GitHub. "
        "On by default; turning it off makes the label trigger skip PRs this user authored.",
    )
    urgency_threshold = serializers.ChoiceField(
        required=False,
        choices=ReviewUserSettings.UrgencyThreshold.choices,
        help_text="Minimum priority a validated finding needs to be published: 'consider' publishes "
        "everything, 'should_fix' (default) drops consider-level findings, 'must_fix' publishes only "
        "blocking issues.",
    )

    class Meta:
        model = ReviewUserSettings
        fields = ["review_inbox_prs", "review_labeled_prs", "urgency_threshold"]


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
