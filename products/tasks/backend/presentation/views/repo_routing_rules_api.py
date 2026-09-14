import re

from django.db import connection, transaction
from django.db.models import Max, QuerySet

from rest_framework import serializers, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.repo_routing_rule import RepoRoutingRule
from posthog.permissions import APIScopePermission

from products.tasks.backend.facade.client_provenance import is_sandbox_oauth_request

_AUTH_CLASSES = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]

# The repo selection prompt truncates each rendered rule at this length, so a longer rule
# would silently lose its distinguishing terms. The Slack `rules add` path enforces the
# same limit.
MAX_RULE_TEXT_LENGTH = 300

# Every rule rides in the repo selection prompt, so an unbounded set would bloat it. The cap
# is a guardrail well above realistic use, not a product limit.
MAX_RULES_PER_TEAM = 50

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class NotSandboxForWrites(BasePermission):
    """Sandbox OAuth tokens carry `task:write`, but a coding agent must not steer where the
    team's future tasks land — a prompt-injected run could redirect teammates' work to a
    repository of the attacker's choosing. Reads stay open: runs receive the rules in their
    prompt anyway."""

    message = "Task agents cannot modify routing rules."

    def has_permission(self, request: Request, view) -> bool:
        return request.method in SAFE_METHODS or not is_sandbox_oauth_request(request)


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
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="Who created the rule, from the UI or the Slack commands. Null when that user was deleted.",
    )

    class Meta:
        model = RepoRoutingRule
        fields = ["id", "rule_text", "repository", "priority", "created_by", "created_at", "updated_at"]
        read_only_fields = ["id", "priority", "created_by", "created_at", "updated_at"]

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
    permission_classes = [IsAuthenticated, APIScopePermission, NotSandboxForWrites]
    serializer_class = RepoRoutingRuleSerializer
    queryset = RepoRoutingRule.objects.all()
    # A team holds a handful of rules and the settings UI renders them all, so `list`
    # returns a raw array.
    pagination_class = None

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.order_by("priority", "id")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        with transaction.atomic():
            # Serialize creates per team: without the lock, concurrent requests can both pass
            # the cap check and take the same priority, breaking "earlier rules win" ordering.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [self.team_id, "repo_routing_rules"])
            if RepoRoutingRule.objects.filter(team_id=self.team_id).count() >= MAX_RULES_PER_TEAM:
                raise serializers.ValidationError(
                    f"A project can have at most {MAX_RULES_PER_TEAM} routing rules. Remove one to add another."
                )
            # Append at the end, matching the Slack `rules add` path: earlier rules win ties.
            max_priority = RepoRoutingRule.objects.filter(team_id=self.team_id).aggregate(m=Max("priority"))["m"]
            serializer.save(
                team_id=self.team_id,
                created_by=self.request.user,
                priority=0 if max_priority is None else max_priority + 1,
            )
