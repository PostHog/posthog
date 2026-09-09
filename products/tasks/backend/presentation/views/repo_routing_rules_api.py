import re

from django.db.models import Max, QuerySet

from rest_framework import serializers, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.repo_routing_rule import RepoRoutingRule
from posthog.permissions import APIScopePermission

_AUTH_CLASSES = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]

# The repo selection prompt truncates each rendered rule at this length, so a longer rule
# would silently lose its distinguishing terms. The Slack `rules add` path enforces the
# same limit.
MAX_RULE_TEXT_LENGTH = 300

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class RepoRoutingRuleSerializer(serializers.ModelSerializer):
    rule_text = serializers.CharField(
        max_length=MAX_RULE_TEXT_LENGTH,
        help_text=(
            "Plain-text description of the requests that should route to the repository, "
            f"e.g. 'anything about the internal dashboard'. At most {MAX_RULE_TEXT_LENGTH} characters."
        ),
    )
    repository = serializers.CharField(
        max_length=255,
        help_text="Target repository as owner/repo, e.g. 'posthog/posthog.com'.",
    )

    class Meta:
        model = RepoRoutingRule
        fields = ["id", "rule_text", "repository", "priority", "created_at", "updated_at"]
        read_only_fields = ["id", "priority", "created_at", "updated_at"]

    def validate_repository(self, value: str) -> str:
        if not _REPOSITORY_RE.match(value):
            raise serializers.ValidationError("Enter the repository as owner/repo.")
        return value


class RepoRoutingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Team routing rules that steer agent repo selection (`RepoRoutingRule`).

    The same rows the Slack `@PostHog rules` commands manage; the repo selection agent
    reads them ordered by priority when picking a repository for a task. Rules whose
    repository is not connected to the project are ignored at selection time, so a
    stale rule is inert rather than harmful — which is why writes here don't check the
    connected-repository list (the UI constrains the picker to connected repos anyway).
    """

    scope_object = "task"
    authentication_classes = _AUTH_CLASSES
    permission_classes = [IsAuthenticated, APIScopePermission]
    serializer_class = RepoRoutingRuleSerializer
    queryset = RepoRoutingRule.objects.all()
    # A team holds a handful of rules and the settings UI renders them all, so `list`
    # returns a raw array.
    pagination_class = None

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.order_by("priority", "id")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        # Append at the end, matching the Slack `rules add` path: earlier rules win ties.
        max_priority = RepoRoutingRule.objects.filter(team_id=self.team_id).aggregate(m=Max("priority"))["m"]
        serializer.save(
            team_id=self.team_id,
            created_by=self.request.user,
            priority=0 if max_priority is None else max_priority + 1,
        )
