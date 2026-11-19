from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_serializer
from pydantic import BaseModel, ConfigDict
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from posthog.schema import EventPropertyFilter, FilterLogicalOperator

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import report_user_action
from posthog.models.user import User

from products.error_tracking.backend.facade import api as error_tracking_api

ISSUE_TAGS_OFF = "Issue tags are off for this project."

FILTERS_HELP_TEXT = (
    "Property-group filters on event properties, evaluated against the first event of each new issue. "
    "At least one filter is required. Person, cohort, HogQL and other filter types are rejected."
)
LABEL_HELP_TEXT = "Display name of the tag the rule applies to each new issue whose first event matches the filters."
DESCRIPTION_HELP_TEXT = "What the tag means. Shown with the tag."
# The bounds of the Postgres integer column that stores the order key.
ORDER_KEY_MIN, ORDER_KEY_MAX = -(2**31), 2**31 - 1


class ErrorTrackingIssueTagRuleFilterGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: FilterLogicalOperator
    values: list[EventPropertyFilter]


class ErrorTrackingIssueTagRuleFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: FilterLogicalOperator
    values: list[ErrorTrackingIssueTagRuleFilterGroup | EventPropertyFilter]


# The schema names only the filter types a rule can run, two levels deep as the filter editor writes them. The full
# property filter union is too large for some MCP clients, which drop a tool whose schema is above their size limit.
# Generated clients cannot express a model that refers to itself, so the schema does not describe deeper nesting.
@extend_schema_field(ErrorTrackingIssueTagRuleFilters)  # type: ignore[arg-type]
class ErrorTrackingIssueTagRuleFiltersField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "object",
        "nullable": True,
        "properties": {
            "message": {"type": "string"},
            "issue": {"type": "object", "additionalProperties": True},
            "properties": {"type": "object", "additionalProperties": True},
        },
    }
)
class ErrorTrackingIssueTagRuleDisabledDataField(serializers.JSONField):
    pass


class ErrorTrackingIssueTagRuleSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier of the tag rule.")
    key = serializers.CharField(
        read_only=True,
        help_text="Tag key that issues store for this rule's tag. Use it to filter issues by the tag, "
        "or to apply or remove the tag on one issue. It changes when an edit changes which properties the "
        "filters read.",
    )
    label = serializers.CharField(max_length=128, help_text=LABEL_HELP_TEXT)  # type: ignore[assignment]
    description = serializers.CharField(allow_blank=True, help_text=DESCRIPTION_HELP_TEXT)
    filters = ErrorTrackingIssueTagRuleFiltersField(help_text=FILTERS_HELP_TEXT)
    version = serializers.IntegerField(
        read_only=True, help_text="Starts at 1, and goes up by one each time the filters change."
    )
    order_key = serializers.IntegerField(
        help_text="Position in the list of tag rules. Lower values come first. Every matching rule applies its "
        "tag, whatever its position."
    )
    disabled_data = ErrorTrackingIssueTagRuleDisabledDataField(
        read_only=True,
        allow_null=True,
        help_text="Why the rule was turned off after it failed on an event, or null when the rule is active. "
        "A turned-off rule tags no new issues until its filters are saved again.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the rule was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the rule was last updated.")


@extend_schema_serializer(many=False)
class ErrorTrackingIssueTagRuleListResponseSerializer(serializers.Serializer):
    results = ErrorTrackingIssueTagRuleSerializer(many=True, help_text="Tag rules in ascending order key.")


class ErrorTrackingIssueTagRuleCreateRequestSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=128, help_text=LABEL_HELP_TEXT)  # type: ignore[assignment]
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=1000,
        help_text=f"{DESCRIPTION_HELP_TEXT} Defaults to empty.",
    )
    filters = ErrorTrackingIssueTagRuleFiltersField(help_text=FILTERS_HELP_TEXT)
    order_key = serializers.IntegerField(
        required=False,
        default=0,
        min_value=ORDER_KEY_MIN,
        max_value=ORDER_KEY_MAX,
        help_text="Position in the list of tag rules. Lower values come first. Defaults to 0.",
    )


class ErrorTrackingIssueTagRuleUpdateRequestSerializer(serializers.Serializer):
    label = serializers.CharField(  # type: ignore[assignment]
        required=False,
        max_length=128,
        help_text="Replacement display name for the tag. Omit to keep the existing label.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="Replacement description. Omit to keep the existing description.",
    )
    filters = ErrorTrackingIssueTagRuleFiltersField(
        required=False,
        help_text="Replacement event property filters, with at least one filter. Omit to keep the existing filters. "
        "New filters apply only to issues created after the update. Existing tags stay when the new filters read "
        "the same properties. When they read different properties, the rule gets a new key and loses its tags.",
    )


class ErrorTrackingIssueTagRuleReorderRequestSerializer(serializers.Serializer):
    orders = serializers.DictField(
        child=serializers.IntegerField(min_value=ORDER_KEY_MIN, max_value=ORDER_KEY_MAX),
        help_text="Mapping from tag rule UUID to its new order key.",
    )


class ErrorTrackingIssueTagRuleViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    scope_object_write_actions = ["create", "update", "partial_update", "destroy", "reorder"]
    requires_resource_level_access = True
    serializer_class = ErrorTrackingIssueTagRuleSerializer
    pagination_class = None

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, error_tracking_api.IssueTagsDisabledError):
            exc = NotFound(ISSUE_TAGS_OFF)
        elif isinstance(exc, error_tracking_api.IssueTagRuleFiltersError):
            exc = ValidationError({"filters": str(exc)})
        elif isinstance(exc, error_tracking_api.IssueTagRuleLimitError):
            exc = ValidationError(str(exc))
        return super().handle_exception(exc)

    @extend_schema(responses={200: OpenApiResponse(response=ErrorTrackingIssueTagRuleListResponseSerializer)})
    def list(self, request, *args, **kwargs) -> Response:
        rules = error_tracking_api.list_issue_tag_rules(self.team.id, self._user)
        return Response({"results": self.get_serializer(rules, many=True).data})

    def retrieve(self, request, *args, pk=None, **kwargs) -> Response:
        rule = error_tracking_api.get_issue_tag_rule(self.team.id, pk, self._user)
        if rule is None:
            raise NotFound()
        return Response(self.get_serializer(rule).data)

    @validated_request(
        request_serializer=ErrorTrackingIssueTagRuleCreateRequestSerializer,
        responses={201: OpenApiResponse(response=ErrorTrackingIssueTagRuleSerializer)},
    )
    def create(self, request: ValidatedRequest, *args, **kwargs) -> Response:
        rule = error_tracking_api.create_issue_tag_rule(
            self.team.id,
            self._user,
            label=request.validated_data["label"],
            description=request.validated_data["description"],
            filters=request.validated_data["filters"],
            order_key=request.validated_data["order_key"],
        )
        self._report("error_tracking_tag_rule_created", request)
        return Response(self.get_serializer(rule).data, status=status.HTTP_201_CREATED)

    def _apply_rule_update(self, request: ValidatedRequest, pk: str) -> Response:
        rule = error_tracking_api.update_issue_tag_rule(
            self.team.id,
            pk,
            self._user,
            label=request.validated_data.get("label"),
            description=request.validated_data.get("description"),
            filters=request.validated_data.get("filters"),
        )
        if rule is None:
            raise NotFound()
        self._report("error_tracking_tag_rule_edited", request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(request_serializer=ErrorTrackingIssueTagRuleUpdateRequestSerializer, responses={204: None})
    def update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    @validated_request(request_serializer=ErrorTrackingIssueTagRuleUpdateRequestSerializer, responses={204: None})
    def partial_update(self, request: ValidatedRequest, *args, pk=None, **kwargs) -> Response:
        return self._apply_rule_update(request, pk)

    def destroy(self, request, *args, pk=None, **kwargs) -> Response:
        if not error_tracking_api.delete_issue_tag_rule(self.team.id, pk, self._user):
            raise NotFound()
        self._report("error_tracking_tag_rule_deleted", request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(request_serializer=ErrorTrackingIssueTagRuleReorderRequestSerializer, responses={204: None})
    @action(methods=["PATCH"], detail=False)
    def reorder(self, request: ValidatedRequest, **kwargs) -> Response:
        error_tracking_api.reorder_issue_tag_rules(self.team.id, request.validated_data["orders"], self._user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @property
    def _user(self) -> User:
        return cast(User, self.request.user)

    def _report(self, event: str, request) -> None:
        report_user_action(self._user, event, team=self.team, organization=self.team.organization, request=request)
