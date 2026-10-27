from collections import Counter

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import get_request_analytics_properties, groups

from products.error_tracking.backend.facade import api as error_tracking_api
from products.error_tracking.backend.facade.contracts import (
    SentryConnection,
    SentryMigrationCategory,
    SentryMigrationFit,
    SentryProjectRef,
)
from products.error_tracking.backend.presentation.views.suppression_rules import (
    ErrorTrackingSuppressionRuleFiltersField,
)


class SentryConnectionRequestSerializer(serializers.Serializer):
    auth_token = serializers.CharField(
        write_only=True,
        max_length=1024,
        help_text=(
            "Sentry auth token with the `org:read` and `project:read` scopes. "
            "PostHog uses it for this request only and doesn't store it."
        ),
    )
    base_url = serializers.CharField(
        required=False,
        default="https://sentry.io",
        max_length=2048,
        help_text="Base URL of the Sentry instance. It must use `https://`. Defaults to `https://sentry.io`. Use your own URL for self-hosted Sentry.",
    )


class SentryProjectRequestSerializer(SentryConnectionRequestSerializer):
    organization_slug = serializers.CharField(max_length=255, help_text="Slug of the Sentry organization.")
    project_slug = serializers.CharField(max_length=255, help_text="Slug of the Sentry project to import from.")
    region_url = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=2048,
        help_text=(
            "Region URL Sentry reports for the organization, as returned by the projects action. "
            "PostHog uses it only when it is on the same host as `base_url`."
        ),
    )


class SentryMigrationApplyRequestSerializer(SentryProjectRequestSerializer):
    item_ids = serializers.ListField(
        child=serializers.CharField(max_length=255),
        allow_empty=False,
        max_length=1000,
        help_text="IDs of the preview items to import.",
    )


class SentryProjectSerializer(serializers.Serializer):
    organization_slug = serializers.CharField(help_text="Slug of the Sentry organization.")
    organization_name = serializers.CharField(help_text="Display name of the Sentry organization.")
    project_slug = serializers.CharField(help_text="Slug of the Sentry project.")
    project_name = serializers.CharField(help_text="Display name of the Sentry project.")
    platform = serializers.CharField(allow_null=True, help_text="Sentry platform of the project, such as `javascript`.")
    region_url = serializers.CharField(
        allow_null=True, help_text="Region URL of the organization. Send it back with the preview and apply actions."
    )


class SentryProjectListResponseSerializer(serializers.Serializer):
    projects = SentryProjectSerializer(many=True, help_text="Sentry projects the token can read.")


class SentryMigrationRateLimitSerializer(serializers.Serializer):
    value = serializers.IntegerField(help_text="Maximum number of exception events per bucket for the project.")
    bucket_size_minutes = serializers.IntegerField(help_text="Bucket window of the rate limit, in minutes.")


class SentryMigrationBuiltInFilterSerializer(serializers.Serializer):
    key = serializers.CharField(
        help_text="Key of the automatic suppression rule, as the built-in filters endpoint lists it."
    )
    name = serializers.CharField(help_text="Name of the automatic suppression rule in PostHog settings.")
    description = serializers.CharField(help_text="What the automatic suppression rule drops.")


class SentryMigrationItemSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable ID of the item. Send it in `item_ids` to import the item.")
    category = serializers.ChoiceField(
        choices=SentryMigrationCategory.choices, help_text="Kind of Sentry setting the item comes from."
    )
    sentry_setting = serializers.CharField(help_text="Name of the setting in Sentry.")
    sentry_value = serializers.CharField(help_text="Value of the setting in Sentry, such as the filter pattern.")
    fit = serializers.ChoiceField(
        choices=SentryMigrationFit.choices,
        help_text=(
            "How closely PostHog reproduces the setting. `good` matches the same events, `partial` is an "
            "approximation explained in `note`, and `unsupported` can't be imported."
        ),
    )
    note = serializers.CharField(allow_null=True, help_text="Explains how the PostHog version differs from Sentry.")
    suppression_rule_filters = ErrorTrackingSuppressionRuleFiltersField(
        allow_null=True,
        help_text="Filters of the suppression rule that the import creates. Null when the item isn't a suppression rule.",
    )
    rate_limit = SentryMigrationRateLimitSerializer(
        allow_null=True, help_text="Project rate limit that the import sets. Null when the item isn't a rate limit."
    )
    built_in_filter = SentryMigrationBuiltInFilterSerializer(
        allow_null=True,
        help_text=(
            "Automatic suppression rule that the import turns on. Null when the item isn't covered by an "
            "automatic rule."
        ),
    )
    already_in_posthog = serializers.BooleanField(
        help_text=(
            "True when the project already has a suppression rule with the same filters, the same automatic rule "
            "turned on, or the same rate limit."
        )
    )


class SentryMigrationPreviewResponseSerializer(serializers.Serializer):
    items = SentryMigrationItemSerializer(many=True, help_text="Sentry settings and the PostHog settings they become.")


class SentryMigrationApplyResponseSerializer(serializers.Serializer):
    suppression_rules_created = serializers.IntegerField(help_text="Number of suppression rules the import created.")
    built_in_filters_enabled = serializers.IntegerField(
        help_text="Number of automatic suppression rules the import turned on."
    )
    rate_limit_updated = serializers.BooleanField(help_text="True when the import set the project rate limit.")


def _connection(data: dict) -> SentryConnection:
    return SentryConnection(auth_token=data["auth_token"], base_url=data["base_url"])


def _project_ref(data: dict) -> SentryProjectRef:
    return SentryProjectRef(
        organization_slug=data["organization_slug"],
        project_slug=data["project_slug"],
        region_url=data.get("region_url") or None,
    )


class ErrorTrackingSentryMigrationViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Imports Sentry inbound filters and rate limits as PostHog suppression rules and rate limits."""

    scope_object = "error_tracking"
    scope_object_read_actions = ["projects", "preview"]
    scope_object_write_actions = ["apply"]
    # An import changes rules and limits for the whole project, so a grant on one error tracking object is not enough.
    requires_resource_level_access = True

    def _capture(self, request: ValidatedRequest, event: str, properties: dict) -> None:
        posthoganalytics.capture(
            event,
            distinct_id=request.user.pk,
            properties={**get_request_analytics_properties(request), **properties},
            groups=groups(self.team.organization, self.team),
        )

    @validated_request(
        request_serializer=SentryConnectionRequestSerializer,
        responses={200: OpenApiResponse(response=SentryProjectListResponseSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def projects(self, request: ValidatedRequest, **kwargs) -> Response:
        try:
            projects = error_tracking_api.list_sentry_projects(_connection(request.validated_data))
        except error_tracking_api.SentryApiError as err:
            raise ValidationError(str(err)) from err
        self._capture(request, "error_tracking_sentry_migration_connected", {"project_count": len(projects)})
        return Response(SentryProjectListResponseSerializer({"projects": projects}).data)

    @validated_request(
        request_serializer=SentryProjectRequestSerializer,
        responses={200: OpenApiResponse(response=SentryMigrationPreviewResponseSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def preview(self, request: ValidatedRequest, **kwargs) -> Response:
        try:
            items = error_tracking_api.preview_sentry_migration(
                self.team.id, _connection(request.validated_data), _project_ref(request.validated_data)
            )
        except error_tracking_api.SentryApiError as err:
            raise ValidationError(str(err)) from err
        self._capture(
            request,
            "error_tracking_sentry_migration_previewed",
            {
                "item_count": len(items),
                "items_by_category": dict(Counter(item.category.value for item in items)),
                "items_by_fit": dict(Counter(item.fit.value for item in items)),
            },
        )
        return Response(SentryMigrationPreviewResponseSerializer({"items": items}).data)

    @validated_request(
        request_serializer=SentryMigrationApplyRequestSerializer,
        responses={200: OpenApiResponse(response=SentryMigrationApplyResponseSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def apply(self, request: ValidatedRequest, **kwargs) -> Response:
        try:
            result = error_tracking_api.apply_sentry_migration(
                self.team.id,
                _connection(request.validated_data),
                _project_ref(request.validated_data),
                request.validated_data["item_ids"],
            )
        except (
            error_tracking_api.SentryApiError,
            error_tracking_api.SentryMigrationSelectionError,
            error_tracking_api.InvalidBytecodeError,
        ) as err:
            raise ValidationError(str(err)) from err
        self._capture(
            request,
            "error_tracking_sentry_migration_applied",
            {
                "selected_item_count": len(request.validated_data["item_ids"]),
                "suppression_rules_created": result.suppression_rules_created,
                "built_in_filters_enabled": result.built_in_filters_enabled,
                "rate_limit_updated": result.rate_limit_updated,
            },
        )
        return Response(SentryMigrationApplyResponseSerializer(result).data, status=status.HTTP_200_OK)
