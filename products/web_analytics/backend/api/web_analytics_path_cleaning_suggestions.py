from typing import Any

from django.db import transaction

import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.health_issue import HealthIssue
from posthog.models.organization import OrganizationMembership
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle

from products.web_analytics.backend.path_cleaning_suggestions.service import (
    AnnotatedRule,
    apply_suggestions_to_team,
    build_suggestion_payload,
    generate_suggestions_for_team,
    preview_rules_on_team,
)

SUGGESTIONS_KIND = "path_cleaning_suggestions"
FEATURE_FLAG_KEY = "web-analytics-path-cleaning-suggestions"


class SuggestedRuleSerializer(serializers.Serializer):
    regex = serializers.CharField(help_text="re2 pattern matching the dynamic path segment.")
    alias = serializers.CharField(help_text="Replacement with angle-bracket placeholders, e.g. /users/<id>.")
    order = serializers.IntegerField(help_text="Apply order; rules run sequentially, output feeds the next.")
    reason = serializers.CharField(
        required=False, allow_blank=True, help_text="Short rationale for the rule from the model."
    )
    match_count = serializers.IntegerField(
        help_text="How many of the sampled paths this rule rewrites — evidence the rule was validated on real traffic."
    )


class PathCleaningSuggestionIssueSerializer(serializers.Serializer):
    """A path-cleaning suggestion, stored as a `path_cleaning_suggestions` health issue."""

    id = serializers.UUIDField(help_text="Health-issue id; pass it to the apply endpoint or the health-issues API.")
    created_at = serializers.DateTimeField(help_text="When the suggestion was generated (ISO 8601).")
    rules = SuggestedRuleSerializer(
        many=True, help_text="Validated path-cleaning rules proposed for this team, most specific first."
    )
    model = serializers.CharField(help_text="LLM that generated the rules.")
    sampled_path_count = serializers.IntegerField(help_text="How many real paths were sampled for generation.")
    distinct_path_count = serializers.IntegerField(help_text="Distinct pathnames seen in the sampling window.")

    @staticmethod
    def from_issue(issue: HealthIssue) -> dict[str, Any]:
        payload = issue.payload or {}
        return {
            "id": str(issue.id),
            "created_at": issue.created_at,
            "rules": payload.get("rules", []),
            "model": payload.get("model", ""),
            "sampled_path_count": payload.get("sampled_path_count", 0),
            "distinct_path_count": payload.get("distinct_path_count", 0),
        }


class GeneratePathCleaningSuggestionResponseSerializer(serializers.Serializer):
    status = serializers.CharField(
        help_text="generated, skipped_low_cardinality, skipped_no_paths, skipped_configured, or error."
    )
    suggestion = PathCleaningSuggestionIssueSerializer(
        required=False, allow_null=True, help_text="The stored suggestion when status is generated, else null."
    )


class ApplyPathCleaningSuggestionResponseSerializer(serializers.Serializer):
    applied = serializers.IntegerField(help_text="Number of rules merged into the team's path_cleaning_filters.")


class PathCleaningPreviewExampleSerializer(serializers.Serializer):
    before = serializers.CharField(help_text="A real sampled path before the suggested rules are applied.")
    after = serializers.CharField(help_text="The same path after all suggested rules run in order.")
    views = serializers.IntegerField(help_text="Pageviews this path received in the sampling window.")


class PreviewPathCleaningSuggestionResponseSerializer(serializers.Serializer):
    examples = PathCleaningPreviewExampleSerializer(
        many=True, help_text="Up to 20 before/after pairs for sampled paths the suggested rules would rewrite."
    )
    changed_path_count = serializers.IntegerField(
        help_text="How many of the sampled paths the suggested rules rewrite in total."
    )
    sampled_path_count = serializers.IntegerField(help_text="How many top paths were sampled for this preview.")


class WebAnalyticsPathCleaningSuggestionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Path-cleaning suggestions live as `path_cleaning_suggestions` health issues — list and
    dismiss them through the generic health-issues API. This viewset owns only the two
    web-analytics-specific verbs: on-demand generation and applying rules to the team."""

    scope_object = "web_analytics"

    def get_throttles(self):
        if self.action == "generate":
            # generation runs a ClickHouse path sample plus an LLM call — cap it for
            # session-authenticated users the same way token-based AI callers are capped
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        return super().get_throttles()

    @extend_schema(
        operation_id="web_analytics_path_cleaning_suggestions_generate",
        summary="Generate path-cleaning suggestions on demand",
        description="Samples the team's recent paths, asks the LLM for cleaning rules, validates them against the "
        "real paths, and stores the result as a `path_cleaning_suggestions` health issue (replacing any previous "
        "active one). Runs even if the team already has rules. Returns the suggestion (or a skip status when there "
        "aren't enough paths to suggest from).",
        request=None,
        responses={200: GeneratePathCleaningSuggestionResponseSerializer},
    )
    @action(detail=False, methods=["post"], required_scopes=["web_analytics:write"])
    def generate(self, request: Request, **kwargs: Any) -> Response:
        # Dogfooding gate on the one verb that spends money (ClickHouse sampling + an LLM call).
        # preview/apply only operate on already-stored suggestions, so they stay scope/admin-gated.
        distinct_id = getattr(request.user, "distinct_id", None)
        if not distinct_id or not posthoganalytics.feature_enabled(
            FEATURE_FLAG_KEY,
            distinct_id,
            groups={"organization": str(self.organization.id)},
            group_properties={"organization": {"id": str(self.organization.id)}},
        ):
            raise PermissionDenied("This feature is not available.")

        result = generate_suggestions_for_team(self.team, visited_within_days=None, include_configured=True)
        if result.status != "generated" or not result.rules:
            return Response({"status": result.status, "suggestion": None})

        issue, _ = HealthIssue.upsert_issue(
            team_id=self.team.id,
            kind=SUGGESTIONS_KIND,
            severity=HealthIssue.Severity.INFO,
            payload=build_suggestion_payload(result),
            hash_keys=[],
        )
        return Response(
            {"status": result.status, "suggestion": PathCleaningSuggestionIssueSerializer.from_issue(issue)}
        )

    @extend_schema(
        operation_id="web_analytics_path_cleaning_suggestions_preview",
        summary="Preview a path-cleaning suggestion on real paths",
        description="Applies the suggestion's rules (in order) to a fresh sample of the team's top paths and returns "
        "before/after pairs for the paths that would change. Computed on demand; path samples are never stored. "
        "Nothing is modified.",
        request=None,
        responses={200: PreviewPathCleaningSuggestionResponseSerializer},
    )
    @action(detail=True, methods=["get"], required_scopes=["web_analytics:read"])
    def preview(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        issue = HealthIssue.objects.filter(team_id=self.team.id, kind=SUGGESTIONS_KIND, id=pk).first() if pk else None
        if issue is None:
            raise NotFound("No such path-cleaning suggestion.")
        rules = [AnnotatedRule(**rule) for rule in (issue.payload or {}).get("rules", [])]
        return Response(preview_rules_on_team(self.team, rules))

    @extend_schema(
        operation_id="web_analytics_path_cleaning_suggestions_apply",
        summary="Apply a path-cleaning suggestion",
        description="Merges the suggestion's rules into the team's path_cleaning_filters (never overwrites existing "
        "rules) and resolves the underlying health issue. Requires project admin, matching the team API's gate on "
        "path_cleaning_filters.",
        request=None,
        responses={200: ApplyPathCleaningSuggestionResponseSerializer},
    )
    @action(detail=True, methods=["post"], required_scopes=["web_analytics:write"])
    def apply(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        # path_cleaning_filters is a project-admin field on the team API (TEAM_CONFIG_ADMIN_FIELDS_SET);
        # writing it through this endpoint must not be a way around that gate.
        membership_level = self.user_permissions.team(self.team).effective_membership_level
        if membership_level is None or membership_level < OrganizationMembership.Level.ADMIN:
            raise PermissionDenied("Only project admins can apply path cleaning suggestions.")
        if pk is None:
            raise NotFound("No such path-cleaning suggestion.")
        issue = HealthIssue.objects.filter(team_id=self.team.id, kind=SUGGESTIONS_KIND, id=pk).first()
        if issue is None:
            raise NotFound("No such path-cleaning suggestion.")
        rules = [AnnotatedRule(**rule) for rule in (issue.payload or {}).get("rules", [])]
        # Merge the rules and resolve the issue together — if the resolve failed on its own the
        # banner would reappear and offer "Apply all" again for rules already applied.
        with transaction.atomic():
            added = apply_suggestions_to_team(self.team, rules)
            if issue.status == HealthIssue.Status.ACTIVE:
                issue.resolve()
        return Response({"applied": added})
