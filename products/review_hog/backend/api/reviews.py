import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.scoping.manager import resolve_effective_team_id

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import effective_priority
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.persistence import load_valid_findings

logger = logging.getLogger(__name__)

RECENT_REVIEWS_LIMIT = 10


class ReviewRecentReviewSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="The reviewed repository, as `owner/repo`.")
    pr_number = serializers.IntegerField(help_text="The reviewed pull request's number.")
    head_branch = serializers.CharField(help_text="The pull request's head branch.")
    github_url = serializers.CharField(
        help_text="Where to see the review on GitHub: the pull request when its URL is known, "
        "otherwise the head branch."
    )
    run_count = serializers.IntegerField(help_text="How many review turns have completed on this report.")
    last_run_at = serializers.DateTimeField(help_text="When the latest review turn completed.")
    published = serializers.BooleanField(help_text="Whether a review has been published back to GitHub.")
    must_fix_count = serializers.IntegerField(
        help_text="The latest turn's valid findings at must_fix effective priority."
    )
    should_fix_count = serializers.IntegerField(
        help_text="The latest turn's valid findings at should_fix effective priority."
    )
    consider_count = serializers.IntegerField(
        help_text="The latest turn's valid findings at consider effective priority."
    )


class ReviewRecentReviewsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """The requesting user's most recent ReviewHog reviews (reports where they are the acting user).

    Read-only meta for the Code review tab's "recent reviews" block: what was reviewed, how many
    valid findings at each effective priority, and where to see it on GitHub.
    """

    scope_object = "INTERNAL"
    # Unscoped only to satisfy the router/introspection; every real query goes through `for_team`.
    queryset = ReviewReport.objects.unscoped()
    serializer_class = ReviewRecentReviewSerializer
    pagination_class = None

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ReviewRecentReviewSerializer(many=True),
                description="The user's recent completed reviews, newest first.",
            ),
        },
        summary="List the user's recent reviews",
        description="The most recent completed ReviewHog reviews of the requesting user's pull requests "
        "on this project, newest first (at most 10).",
    )
    def list(self, request: Request, **kwargs) -> Response:
        team_id = resolve_effective_team_id(self.team_id)
        reports = list(
            ReviewReport.objects.for_team(team_id, canonical=True)
            .filter(acting_user_id=request.user.id, last_run_at__isnull=False)
            .order_by("-last_run_at")[:RECENT_REVIEWS_LIMIT]
        )
        items = []
        for report in reports:
            counts = dict.fromkeys(IssuePriority, 0)
            pairs = load_valid_findings(team_id=team_id, report_id=str(report.id), run_index=report.run_count)
            for finding, verdict in pairs:
                counts[effective_priority(finding.priority, verdict.adjusted_priority)] += 1
            items.append(
                {
                    "repository": report.repository,
                    "pr_number": report.pr_number,
                    "head_branch": report.head_branch,
                    "github_url": report.pr_url or f"https://github.com/{report.repository}/tree/{report.head_branch}",
                    "run_count": report.run_count,
                    "last_run_at": report.last_run_at,
                    "published": report.published_head_sha is not None,
                    "must_fix_count": counts[IssuePriority.MUST_FIX],
                    "should_fix_count": counts[IssuePriority.SHOULD_FIX],
                    "consider_count": counts[IssuePriority.CONSIDER],
                }
            )
        return Response(ReviewRecentReviewSerializer(items, many=True).data)
