from dataclasses import asdict
from typing import Any

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.fields import JSONTolerantListField
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    is_mcp_request,
)
from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.permissions import APIScopePermission, is_service_auth

from products.signals.backend.activity_summary.prompt import ActivitySummaryMode
from products.signals.backend.activity_summary.read import DEFAULT_VERSIONS_LIMIT, ActivitySummaryStatus
from products.signals.backend.activity_summary.render import Product
from products.signals.backend.activity_summary.search import (
    DEFAULT_LIMIT as SEARCH_DEFAULT_LIMIT,
    MAX_LIMIT as SEARCH_MAX_LIMIT,
    MatchKind,
    SearchMode,
    SemanticSearchUnavailable,
)
from products.signals.backend.facade import api as signals_facade
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission

READ_EVENT = "activity summary read"


# Built from `Product`, so the API enum cannot drift from the keys that `computed.py` writes.
ActivitySummaryProduct = models.TextChoices(  # type: ignore[call-overload]  # the stubs lack the functional API
    "ActivitySummaryProduct", [(product.name, product.value) for product in Product]
)


class ActivitySummaryThemeSerializer(serializers.Serializer):
    label = serializers.CharField(  # type: ignore[assignment]  # DRF Field.label collides with a field named label
        help_text="A main thread of the user's work, in at most 60 characters."
    )
    mode = serializers.ChoiceField(
        choices=ActivitySummaryMode.choices,
        allow_null=True,
        help_text="How the user works on this thread. Null on summaries from before themes had a mode.",
    )
    strength = serializers.CharField(
        allow_null=True, help_text="How much of the recent activity is about this thread: high, medium or low."
    )
    refs = serializers.ListField(
        child=serializers.CharField(),
        help_text="Refs into `computed.owned`, `computed.watched`, `computed.pages`, `computed.tasks` and "
        "`computed.mcp_sessions` of the same version, such as `o1`, `p2`, `t3` or `m1`, that show this thread. "
        "A ref is valid only inside one version.",
    )
    last_seen = serializers.CharField(
        allow_null=True, help_text="The last day of activity on the refs of this thread, as YYYY-MM-DD."
    )


class ActivitySummaryOwnedObjectSerializer(serializers.Serializer):
    ref = serializers.CharField(help_text="The ref that themes cite, such as `o1`.")
    type = serializers.CharField(help_text="The object type in snake case, such as `dashboard` or `feature_flag`.")
    id = serializers.CharField(help_text="The id of the object.")
    name = serializers.CharField(help_text="The latest name of the object.")
    edit_days = serializers.IntegerField(help_text="The number of distinct days the user changed the object.")
    last_at = serializers.CharField(help_text="The last day the user changed the object, as YYYY-MM-DD.")
    created = serializers.BooleanField(help_text="True when the user created the object in the window.")


class ActivitySummaryWatchedObjectSerializer(serializers.Serializer):
    ref = serializers.CharField(help_text="The ref that themes cite, such as `o21`.")
    type = serializers.CharField(help_text="The object type, such as `dashboard` or `insight`.")
    id = serializers.CharField(help_text="The id of the object.")
    name = serializers.CharField(help_text="The name of the object.")
    open_days = serializers.IntegerField(help_text="The number of distinct days the user opened the object.")
    last_at = serializers.CharField(help_text="The last day the user opened the object, as YYYY-MM-DD.")
    not_theirs = serializers.BooleanField(help_text="True when someone else made the object.")


class ActivitySummaryPageVisitsSerializer(serializers.Serializer):
    ref = serializers.CharField(help_text="The ref that themes cite, such as `p1`.")
    product = serializers.ChoiceField(
        choices=ActivitySummaryProduct.choices, help_text="The product whose pages the user opened."
    )
    open_days = serializers.IntegerField(help_text="The number of distinct days the user opened its pages.")
    last_at = serializers.CharField(help_text="The last day the user opened its pages, as YYYY-MM-DD.")


class ActivitySummaryLineRefSerializer(serializers.Serializer):
    ref = serializers.CharField(
        help_text="The ref that themes cite, such as `t1` for a task or `m1` for an MCP session."
    )
    last_at = serializers.CharField(help_text="The day of the task or MCP session, as YYYY-MM-DD.")


class ActivitySummaryProductSplitSerializer(serializers.Serializer):
    works_in = serializers.ListField(
        child=serializers.ChoiceField(choices=ActivitySummaryProduct.choices),
        help_text="Products where the user changed something or tagged a task, the most active first.",
    )
    visits = serializers.ListField(
        child=serializers.ChoiceField(choices=ActivitySummaryProduct.choices),
        help_text="Products the user only opened, the most opened first.",
    )


class ActivitySummaryComputedSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField(help_text="The version of the shape of these fields.")
    owned = ActivitySummaryOwnedObjectSerializer(
        many=True, help_text="Objects the user created or changed, the most edited first."
    )
    watched = ActivitySummaryWatchedObjectSerializer(
        many=True, help_text="Objects the user opened on 3 or more days, the most opened first."
    )
    pages = ActivitySummaryPageVisitsSerializer(
        many=True, help_text="Products whose pages the user opened, the most opened first."
    )
    products = ActivitySummaryProductSplitSerializer(
        help_text="The products the user works in and the products they only visit."
    )
    task_count = serializers.IntegerField(
        help_text="The number of tasks the user gave to PostHog AI or the Slack agent."
    )
    tasks = ActivitySummaryLineRefSerializer(
        many=True,
        help_text="Tasks the user gave to PostHog AI or the Slack agent that the summary input showed, oldest first. "
        "Empty on summaries from before task refs existed.",
    )
    mcp_sessions = ActivitySummaryLineRefSerializer(
        many=True,
        help_text="Sessions of the user's AI agent over MCP that the summary input showed, oldest first. "
        "Empty on summaries from before MCP refs existed.",
    )


@extend_schema_serializer(many=False)
class ActivitySummarySerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=ActivitySummaryStatus.choices,
        help_text="`ready` when a summary exists. `not_ready` when no summary exists yet, which is normal for new or quiet users.",
    )
    headline = serializers.CharField(
        allow_null=True, help_text="One or two sentences about what the user works on and cares about in this project."
    )
    profile = serializers.CharField(
        allow_null=True,
        help_text="A one-page markdown profile of the user's work in this project. Null on summaries from before profiles existed.",
    )
    themes = ActivitySummaryThemeSerializer(many=True, help_text="The main threads of the user's work.")
    modes = serializers.ListField(
        child=serializers.ChoiceField(choices=ActivitySummaryMode.choices),
        help_text="How the user works in this project overall, the main mode first.",
    )
    recent_shift = serializers.CharField(
        allow_null=True, help_text="What changed since the version before this one, or null when nothing changed."
    )
    computed = ActivitySummaryComputedSerializer(
        allow_null=True,
        help_text="Exact fields that code computed from the user's activity, with ids. The theme refs point into them. "
        "Null before the first update that computed them.",
    )
    generated_at = serializers.DateTimeField(allow_null=True, help_text="When this version of the summary was written.")
    version = serializers.IntegerField(help_text="The number of this version of the summary. 0 before the first.")
    prompt_version = serializers.IntegerField(
        allow_null=True, help_text="The version of the prompt that wrote this summary."
    )
    stale = serializers.BooleanField(help_text="True when a newer version will replace this summary soon.")


class ActivitySummaryVersionSerializer(serializers.Serializer):
    version = serializers.IntegerField(help_text="The number of this version. Higher numbers are newer.")
    generated_at = serializers.DateTimeField(help_text="When this version was written.")
    prompt_version = serializers.IntegerField(help_text="The version of the prompt that wrote this version.")
    headline = serializers.CharField(
        allow_null=True, help_text="One or two sentences about what the user works on and cares about in this project."
    )
    recent_shift = serializers.CharField(
        allow_null=True, help_text="What changed since the version before this one, or null when nothing changed."
    )
    themes = ActivitySummaryThemeSerializer(many=True, help_text="The main threads of the user's work.")
    modes = serializers.ListField(
        child=serializers.ChoiceField(choices=ActivitySummaryMode.choices),
        help_text="How the user works in this project overall, the main mode first.",
    )
    profile = serializers.CharField(
        allow_null=True,
        help_text="The one-page markdown profile. Set only when the request asks for one version with `version`.",
    )
    computed = ActivitySummaryComputedSerializer(
        allow_null=True,
        help_text="Exact fields that code computed from the user's activity, with ids. The theme refs point into them. "
        "Set only when the request asks for one version with `version`.",
    )


class ActivitySummaryVersionsQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        min_value=1,
        default=DEFAULT_VERSIONS_LIMIT,
        help_text="The most versions to return, newest first. Capped at the number of versions kept.",
    )
    version = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text="Return only this version, with its full profile. Returns 404 when the version does not exist.",
    )


class ActivitySummaryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = ActivitySummarySerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    requires_resource_level_access = True
    pagination_class = None

    def _own_user_id(self, request: Request) -> int:
        # A summary describes one person, so only that person's own credentials can read it.
        if is_service_auth(request) or not isinstance(request.user, User):
            raise PermissionDenied("Activity summaries can only be read by the user they describe.")
        return request.user.id

    def _capture_read(self, request: Request, endpoint: str, status: str, **properties: Any) -> None:
        report_user_action(
            request.user,
            READ_EVENT,
            properties={"endpoint": endpoint, "status": status, "via_mcp": is_mcp_request(request), **properties},
            team=self.team,
            request=request,
        )

    @validated_request(
        responses={200: OpenApiResponse(response=ActivitySummarySerializer)},
        summary="Get your activity summary",
    )
    def list(self, request: Request, **kwargs: object) -> Response:
        summary = signals_facade.get_activity_summary(team=self.team, user_id=self._own_user_id(request))
        if summary is None:
            self._capture_read(request, "get", "not_enrolled")
            raise NotFound()
        self._capture_read(
            request,
            "get",
            summary.status,
            version=summary.version,
            prompt_version=summary.prompt_version,
            stale=summary.stale,
        )
        return Response(ActivitySummarySerializer(asdict(summary)).data)

    @validated_request(
        query_serializer=ActivitySummaryVersionsQuerySerializer,
        responses={200: OpenApiResponse(response=ActivitySummaryVersionSerializer(many=True))},
        summary="List your activity summary versions",
    )
    @action(detail=False, methods=["GET"], required_scopes=["task:read"])
    def versions(self, request: ValidatedRequest, **kwargs: object) -> Response:
        user_id = self._own_user_id(request)
        query = request.validated_query_data
        requested_version = query.get("version")
        versions = signals_facade.list_activity_summary_versions(
            team=self.team, user_id=user_id, limit=query["limit"], version=requested_version
        )
        if versions is None:
            self._capture_read(request, "versions", "not_enrolled")
            raise NotFound()
        if requested_version is not None and not versions:
            self._capture_read(request, "versions", "not_found", version=requested_version)
            raise NotFound()
        newest = versions[0] if versions else None
        self._capture_read(
            request,
            "versions",
            ActivitySummaryStatus.READY if newest else ActivitySummaryStatus.NOT_READY,
            version=newest.version if newest else None,
            prompt_version=newest.prompt_version if newest else None,
            count=len(versions),
        )
        return Response(ActivitySummaryVersionSerializer([asdict(version) for version in versions], many=True).data)


class ActivitySummarySearchQuerySerializer(serializers.Serializer):
    query = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Natural language or keywords, such as an object name, a topic or a product area. "
        "Without a query, the search lists members with a summary, the newest summary first.",
    )
    search_mode = serializers.ChoiceField(
        choices=SearchMode.choices,
        default=SearchMode.HYBRID,
        help_text="`hybrid` merges the keyword and semantic rankings. `semantic` ranks by meaning only, and "
        "returns 503 when the vector search fails. `keyword` matches query terms in the profile, the headline, "
        "the theme labels and the names of owned and watched objects.",
    )
    product = serializers.ChoiceField(
        choices=ActivitySummaryProduct.choices,
        required=False,
        help_text="Only members who work in or visit this product.",
    )
    exclude_user_uuids = JSONTolerantListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        help_text="Members to leave out, such as people you already checked.",
    )
    include_profile = serializers.BooleanField(
        default=False,
        help_text="Add the one-page markdown profile to each result. Set it only for the people you want to read.",
    )
    limit = serializers.IntegerField(
        min_value=1,
        max_value=SEARCH_MAX_LIMIT,
        default=SEARCH_DEFAULT_LIMIT,
        help_text="The most results to return, best match first.",
    )


class ActivitySummarySearchMatchSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=MatchKind.choices,
        help_text="`semantic` for a vector match, else the summary field a keyword matched.",
    )
    snippet = serializers.CharField(
        allow_null=True, help_text="A short excerpt around the first keyword match. Null for a semantic match."
    )


class ActivitySummarySearchHitSerializer(serializers.Serializer):
    user_uuid = serializers.UUIDField(help_text="The member. Use it in `suggested_reviewers`.")
    first_name = serializers.CharField(help_text="The member's first name.")
    last_name = serializers.CharField(help_text="The member's last name.")
    github_login = serializers.CharField(
        allow_null=True, help_text="The member's GitHub login, lowercase. Null when no GitHub identity is linked."
    )
    score = serializers.FloatField(
        allow_null=True,
        help_text="The reciprocal rank fusion score. Higher is a better match. Null when the request had no query.",
    )
    matched_on = ActivitySummarySearchMatchSerializer(many=True, help_text="Why this member matched.")
    headline = serializers.CharField(
        allow_null=True, help_text="One or two sentences about what the member works on in this project."
    )
    themes = ActivitySummaryThemeSerializer(many=True, help_text="The main threads of the member's work.")
    modes = serializers.ListField(
        child=serializers.ChoiceField(choices=ActivitySummaryMode.choices),
        help_text="How the member works in this project overall, the main mode first.",
    )
    generated_at = serializers.DateTimeField(allow_null=True, help_text="When this summary was written.")
    stale = serializers.BooleanField(help_text="True when a newer version will replace this summary soon.")
    profile = serializers.CharField(
        allow_null=True, help_text="The one-page markdown profile. Set only when the request sets `include_profile`."
    )


class ActivitySummarySearchResultSerializer(serializers.Serializer):
    results = ActivitySummarySearchHitSerializer(many=True, help_text="The matching members, best match first.")
    semantic_used = serializers.BooleanField(
        help_text="False when the search used keywords only: a `keyword` search, a request with no query, or a "
        "`hybrid` search whose vector search failed."
    )
    not_ready_count = serializers.IntegerField(
        help_text="Members with access to the project and no summary yet. The search cannot find them."
    )


class _SemanticSearchUnavailable(APIException):
    status_code = 503
    default_detail = "The semantic search is unavailable. Try again, or use `search_mode=hybrid` or `keyword`."
    default_code = "semantic_search_unavailable"


class ActivitySummaryMembersViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Search the activity summaries of a project's members, for reviewer routing in a scout run.

    `scope_object = "signal_scout_internal"` makes this reachable only with a scout sandbox token, as
    `SignalScoutMembersViewSet` is: session auth, personal API keys and user-grantable OAuth tokens are rejected.
    """

    serializer_class = ActivitySummarySearchResultSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "signal_scout_internal"
    pagination_class = None

    @validated_request(
        query_serializer=ActivitySummarySearchQuerySerializer,
        responses={200: OpenApiResponse(response=ActivitySummarySearchResultSerializer)},
        summary="Search member activity summaries",
        description="Find the project members whose activity summary matches a topic, an object or a product, "
        "including people who only open the work and never edit it. Returns 404 when the search is not available "
        "for this project.",
        operation_id="signals_activity_summary_members_search",
    )
    @action(detail=False, methods=["GET"], required_scopes=["signal_scout_internal:read"])
    def search(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        query = request.validated_query_data
        team = self.team
        properties = {
            "search_mode": query["search_mode"],
            "has_query": bool((query.get("query") or "").strip()),
            "has_product": query.get("product") is not None,
            "excluded_count": len(query["exclude_user_uuids"]),
            "include_profile": query["include_profile"],
        }
        try:
            result = signals_facade.search_activity_summaries(
                team=team,
                query=query.get("query"),
                search_mode=query["search_mode"],
                product=query.get("product"),
                exclude_user_uuids=[str(value) for value in query["exclude_user_uuids"]],
                include_profile=query["include_profile"],
                limit=query["limit"],
            )
        except SemanticSearchUnavailable:
            self._capture(request, team, "semantic_unavailable", **properties)
            raise _SemanticSearchUnavailable()
        if result is None:
            self._capture(request, team, "not_enrolled", **properties)
            raise NotFound()
        self._capture(
            request,
            team,
            ActivitySummaryStatus.READY,
            **properties,
            count=len(result.results),
            semantic_used=result.semantic_used,
            not_ready_count=result.not_ready_count,
        )
        return Response(ActivitySummarySearchResultSerializer(asdict(result)).data)

    def _capture(self, request: Request, team: Team, status: str, **properties: Any) -> None:
        # Counts and modes only. The query can repeat report content, and the results are member data.
        report_user_action(
            request.user,
            READ_EVENT,
            properties={"endpoint": "search", "status": status, "via_mcp": is_mcp_request(request), **properties},
            team=team,
            request=request,
        )
