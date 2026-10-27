from dataclasses import asdict
from typing import Any

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
    is_mcp_request,
)
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import APIScopePermission, is_service_auth

from products.signals.backend.activity_summary.prompt import ActivitySummaryMode
from products.signals.backend.activity_summary.read import DEFAULT_VERSIONS_LIMIT, ActivitySummaryStatus
from products.signals.backend.activity_summary.render import Product
from products.signals.backend.facade import api as signals_facade

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
        help_text="Refs into `computed.owned`, `computed.watched` and `computed.pages` of the same version, "
        "such as `o1` or `p2`, that show this thread. A ref is valid only inside one version.",
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
