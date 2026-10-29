import uuid
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils.timezone import now

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.rate_limit import ReplayVisionClustersBurstRateThrottle, ReplayVisionClustersSustainedRateThrottle

from products.replay_vision.backend.api.filters import split_csv
from products.replay_vision.backend.api.observations import _validate_date_bound
from products.replay_vision.backend.cluster_lifecycle import ClusterStatus
from products.replay_vision.backend.experiment_variants import UNATTRIBUTED_VARIANT
from products.replay_vision.backend.models.replay_scanner_semantics import (
    ClusterReview,
    ReplayScannerFeedGroup,
    ReplayScannerSearchTheme,
)
from products.replay_vision.backend.scanner_access import (
    readable_scanner_ids_in_scope,
    scanner_for_reading_observations,
)
from products.replay_vision.backend.search import parse_date_bound
from products.replay_vision.backend.semantic_clusters import (
    EXAMPLES_PER_CLUSTER,
    UNREVIEWED,
    ClusterKind,
    ClusterOrder,
    ClusterPage,
    ClusterScope,
    ClusterWindow,
    cluster_scanner_id,
    summarize_clusters,
)

DEFAULT_CLUSTER_WINDOW = timedelta(days=7)
# Clusters with no member for this long are pruned unless reviewed, so a longer window would undercount.
MAX_CLUSTER_WINDOW = timedelta(days=90)
MAX_CLUSTER_LIMIT = 100


def _check_date_bound(value: str) -> None:
    _validate_date_bound(value)


class ClusterQuerySerializer(serializers.Serializer):
    scanner_id = serializers.UUIDField(
        required=False,
        help_text="Only this scanner's clusters. Defaults to every scanner you can read.",
    )
    date_from = serializers.CharField(
        required=False,
        validators=[_check_date_bound],
        help_text=(
            "Count members from the UTC day of this time: ISO 8601 or relative like `-7d`. Defaults to `-7d`. "
            "The window spans at most 90 days."
        ),
    )
    date_to = serializers.CharField(
        required=False,
        validators=[_check_date_bound],
        help_text="Count members up to the UTC day of this time: ISO 8601, relative, or `now`. Defaults to now.",
    )


class GroupQuerySerializer(ClusterQuerySerializer):
    include_routine = serializers.BooleanField(
        default=False,
        help_text=(
            "Also count routine observations, so groups describe ordinary behavior and not only issues. "
            "Use it for experiment scanners, where the question is how each variant's users behave."
        ),
    )
    variant = serializers.CharField(
        required=False,
        help_text=(
            "Experiment scanners only: count only members attributed to these variant keys (comma-separated). "
            f"`{UNATTRIBUTED_VARIANT}` matches members with no attributed variant."
        ),
    )
    by_variant = serializers.BooleanField(
        default=False,
        help_text="Split each group's window counts by experiment variant in `variants`. Use it on experiment scanners.",
    )


class _PageQueryFields(serializers.Serializer):
    review_state = serializers.CharField(
        required=False,
        help_text=(
            "Only clusters with these reviews (comma-separated): `known`, `resolved`, `not_an_issue`, or "
            f"`{UNREVIEWED}` for clusters nobody reviewed. Pass `{UNREVIEWED}` to leave out what the team already "
            "handled."
        ),
    )
    order = serializers.ChoiceField(
        choices=ClusterOrder.choices,
        default=ClusterOrder.PEOPLE.value,
        help_text=(
            "`people` (distinct people affected), `observations` (member count), `growth` (members gained over "
            "the same-length window before `date_from`), or `recent` (newest member first)."
        ),
    )
    limit = serializers.IntegerField(default=20, min_value=1, max_value=MAX_CLUSTER_LIMIT, help_text="Page size.")
    offset = serializers.IntegerField(default=0, min_value=0, help_text="Rows to skip, for the next page.")


class ClusterListQuerySerializer(ClusterQuerySerializer, _PageQueryFields):
    pass


class GroupListQuerySerializer(GroupQuerySerializer, _PageQueryFields):
    pass


class VariantCountSerializer(serializers.Serializer):
    key = serializers.CharField(help_text=f"The variant key, or `{UNATTRIBUTED_VARIANT}` for members with none.")
    observation_count = serializers.IntegerField(help_text="The group's members in this variant in the window.")
    people_count = serializers.IntegerField(help_text="Distinct people among them.")


class ClusterReviewSerializer(serializers.Serializer):
    review_state = serializers.ChoiceField(
        choices=ClusterReview.choices,
        allow_blank=True,
        help_text=(
            "`known` (the team is aware), `resolved` (fixed; new members reopen it as `regressed`), `not_an_issue`, "
            "or an empty string to clear the review."
        ),
    )


class ClusterSerializer(serializers.Serializer):
    id = serializers.CharField(
        help_text="The cluster id. Pass it as `theme` or `group` to `vision-scanners-observations-list` to read members."
    )
    scanner_id = serializers.UUIDField(help_text="The scanner whose observations the cluster groups.")
    scanner_name = serializers.CharField(help_text="The scanner's name.")
    name = serializers.CharField(
        allow_null=True,
        help_text=(
            "A short model-written label: a search phrase for a theme, a headline for a group. Null until the "
            "cluster is large enough to be named; `example_summary` stands in."
        ),
    )
    status = serializers.ChoiceField(
        choices=ClusterStatus.choices,
        help_text=(
            "Where the cluster stands. From its activity: `emerging` (first member this week), `active`, `fading` "
            "(last week under half of the week before) or `dormant` (no member for two weeks). From a review: "
            "`known`, `resolved`, `regressed` (new members after it was resolved) or `not_an_issue`."
        ),
    )
    review_state = serializers.CharField(help_text="The team's review, or an empty string when nobody reviewed it.")
    reviewed_at = serializers.DateTimeField(allow_null=True, help_text="When the review was set.")
    observation_count = serializers.IntegerField(
        help_text="Readable observations in the window: issue observations, plus routine ones with `include_routine`."
    )
    people_count = serializers.IntegerField(
        help_text="Distinct people among them; a session without an identified person counts as one."
    )
    previous_observation_count = serializers.IntegerField(
        help_text="Members in the same-length window just before `date_from`, to compare the trend against."
    )
    first_seen = serializers.DateField(help_text="UTC day of the window's oldest member.")
    last_seen = serializers.DateField(help_text="UTC day of the window's newest member.")
    example_observation_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text=f"Up to {EXAMPLES_PER_CLUSTER} of the window's highest-ranked members, best first.",
    )
    example_summary = serializers.CharField(
        help_text="One-line summary of the best example; the readable label for a group, which has no name."
    )
    variants = VariantCountSerializer(
        many=True,
        help_text=(
            "The window's members split by experiment variant, largest first. Empty unless `by_variant` is set. "
            "Compare each variant's share of the group with its share of the scanner's sessions, since variants "
            "are sampled at different rates."
        ),
    )


class ClusterListSerializer(serializers.Serializer):
    results = ClusterSerializer(many=True, help_text="Clusters with at least one member in the window.")
    has_more = serializers.BooleanField(help_text="Whether another page follows at `offset + limit`.")


class _ClusterViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read-only summaries of one kind of cluster over the scanners the caller may read."""

    kind: ClusterKind
    query_serializer: type[ClusterQuerySerializer] = ClusterQuerySerializer
    list_query_serializer: type[ClusterQuerySerializer] = ClusterListQuerySerializer
    scope_object = "replay_scanner"
    required_scopes = ["replay_scanner:read", "session_recording:read"]
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["review"]
    throttle_classes = [ReplayVisionClustersBurstRateThrottle, ReplayVisionClustersSustainedRateThrottle]

    def _window(self, params: dict[str, Any]) -> ClusterWindow:
        timezone_info = self.team.timezone_info
        current = now()
        date_to = parse_date_bound(params.get("date_to") or "now", timezone_info, end_of_range=True, now=current)
        date_from = (
            parse_date_bound(params["date_from"], timezone_info, end_of_range=False, now=current)
            if params.get("date_from")
            else date_to - DEFAULT_CLUSTER_WINDOW
        )
        if date_from >= date_to:
            raise ValidationError({"date_from": "Must be before `date_to`."})
        # Three calendar months can run to 92 days, so the cap leaves room for `-3m`.
        if date_to - date_from > MAX_CLUSTER_WINDOW + timedelta(days=3):
            raise ValidationError({"date_from": f"The window can span at most {MAX_CLUSTER_WINDOW.days} days."})
        return ClusterWindow(date_from=date_from, date_to=date_to)

    def _summarize(
        self, params: dict[str, Any], scanner_id: uuid.UUID | None, cluster_id: uuid.UUID | None = None
    ) -> ClusterPage:
        return summarize_clusters(
            kind=self.kind,
            team_id=self.team_id,
            access=self.user_access_control,
            scanner_ids=readable_scanner_ids_in_scope(self.user_access_control, self.team_id, scanner_id),
            window=self._window(params),
            order=ClusterOrder(params.get("order", ClusterOrder.PEOPLE)),
            limit=params.get("limit", 1),
            offset=params.get("offset", 0),
            cluster_id=cluster_id,
            scope=ClusterScope(
                include_routine=params.get("include_routine", False),
                variants=tuple(split_csv(params.get("variant") or "")),
                review_states=tuple(split_csv(params.get("review_state") or "")),
            ),
            by_variant=params.get("by_variant", False),
            now=now(),
        )

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        params = self.list_query_serializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        page = self._summarize(params.validated_data, params.validated_data.get("scanner_id"))
        return Response(ClusterListSerializer({"results": page.results, "has_more": page.has_more}).data)

    def retrieve(self, request: Request, *args: Any, pk: str, **kwargs: Any) -> Response:
        params = self.query_serializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        try:
            cluster_id = uuid.UUID(pk)
        except ValueError:
            raise NotFound()
        # A cluster lives on one scanner, so reading only that scanner keeps the 90-day window cheap.
        scanner_id = cluster_scanner_id(self.kind, self.team_id, cluster_id)
        asked = params.validated_data.get("scanner_id")
        if scanner_id is None or (asked is not None and asked != scanner_id):
            raise NotFound()
        page = self._summarize(params.validated_data, scanner_id, cluster_id=cluster_id)
        # Not-found also covers a cluster with no readable member in the window.
        if not page.results:
            raise NotFound()
        return Response(ClusterSerializer(page.results[0]).data)

    @action(detail=True, methods=["post"], required_scopes=["replay_scanner:write", "session_recording:read"])
    def review(self, request: Request, *args: Any, pk: str, **kwargs: Any) -> Response:
        body = ClusterReviewSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            cluster_id = uuid.UUID(pk)
        except ValueError:
            raise NotFound()
        scanner_id = cluster_scanner_id(self.kind, self.team_id, cluster_id)
        scanner = scanner_for_reading_observations(self.team_id, scanner_id) if scanner_id else None
        readable = readable_scanner_ids_in_scope(self.user_access_control, self.team_id, None)
        if scanner is None or str(scanner.id) not in readable:
            raise NotFound()
        # A review changes what the whole team sees for the scanner, so it needs editor access to the scanner.
        if not self.user_access_control.check_access_level_for_object(scanner, "editor"):
            raise PermissionDenied("Reviewing a cluster requires editor access to its scanner.")
        state = body.validated_data["review_state"]
        reviewed = state != ""
        with transaction.atomic():
            model = ReplayScannerSearchTheme if self.kind == ClusterKind.THEME else ReplayScannerFeedGroup
            model.objects.for_team(self.team_id).filter(id=cluster_id).update(
                review_state=state,
                reviewed_at=now() if reviewed else None,
                reviewed_by=request.user if reviewed else None,
            )
        return Response(status=204)


@extend_schema_view(
    review=extend_schema(
        description="Record the team's decision about a theme, or clear it. Needs editor access to its scanner.",
        request=ClusterReviewSerializer,
        responses={204: None},
    ),
    list=extend_schema(
        description=(
            "Recurring kinds of issue in replay observations, each a broad cluster of one scanner's issue "
            "observations with a short model-written name. Use it to see what comes up often and what is growing."
        ),
        parameters=[ClusterListQuerySerializer],
        responses={200: ClusterListSerializer},
    ),
    retrieve=extend_schema(
        description="One search theme's counts and examples over the window.",
        parameters=[ClusterQuerySerializer],
        responses={200: ClusterSerializer},
    ),
)
class VisionThemeViewSet(_ClusterViewSet):
    kind = ClusterKind.THEME


@extend_schema_view(
    review=extend_schema(
        description="Record the team's decision about a group, or clear it. Needs editor access to its scanner.",
        request=ClusterReviewSerializer,
        responses={204: None},
    ),
    list=extend_schema(
        description=(
            "Groups of near-duplicate issue observations, each one scanner's sessions that tell the same story, "
            "such as one bug many people hit. Narrower than themes. Use it to find the issues that reach the most "
            "people."
        ),
        parameters=[GroupListQuerySerializer],
        responses={200: ClusterListSerializer},
    ),
    retrieve=extend_schema(
        description="One group's counts and examples over the window.",
        parameters=[GroupQuerySerializer],
        responses={200: ClusterSerializer},
    ),
)
class VisionGroupViewSet(_ClusterViewSet):
    kind = ClusterKind.GROUP
    query_serializer = GroupQuerySerializer
    list_query_serializer = GroupListQuerySerializer
