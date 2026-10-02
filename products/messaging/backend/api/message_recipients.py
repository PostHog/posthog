from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.messaging.backend.models.message_preferences import PreferenceStatus
from products.messaging.backend.models.message_suppression import SuppressionSource
from products.messaging.backend.services.recipients import (
    InvalidRecipientFilter,
    RecipientPage,
    RecipientQuery,
    count_persons_without_email,
    find_recipient,
    list_recipients,
    parse_recipient_filter,
)


class RecipientListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=512,
        help_text="Case-insensitive substring match on the email address.",
    )
    filter = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        default=list,
        help_text="Repeatable `facet:value` filter; prefix with `-` to negate. Values on one facet are OR, "
        "facets are AND. Facets: `subscribed`, `unsubscribed` and `no-preference` take a topic key or "
        "`all-marketing`; `suppressed` takes `BOUNCE`, `COMPLAINT` or `MANUAL`; `person` takes `linked` or "
        "`none`; `preference` takes `recorded` or `none`.",
    )
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=200, help_text="Page size, 1-200. Defaults to 50."
    )
    cursor = serializers.CharField(
        required=False,
        max_length=512,
        help_text="`next_cursor` from the previous page. Omit for the first page.",
    )
    email = serializers.CharField(
        required=False,
        max_length=512,
        help_text="Return only this address, matched case-insensitively. Responds 404 when the team does not know it.",
    )


class RecipientSuppressionSerializer(serializers.Serializer):
    source = serializers.ChoiceField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        choices=SuppressionSource.choices,
        help_text="Why the address is suppressed: `BOUNCE` (repeated soft bounces), `COMPLAINT` (marked as spam) or `MANUAL` (added by a user).",
    )
    reason = serializers.CharField(allow_null=True, help_text="Free-text reason recorded with the suppression.")
    suppressed_at = serializers.DateTimeField(allow_null=True, help_text="When the address became suppressed.")


class RecipientPersonSerializer(serializers.Serializer):
    uuid = serializers.UUIDField(help_text="UUID of a person whose `email` property is this address.")
    distinct_id = serializers.CharField(help_text="One of the person's distinct IDs.")
    name = serializers.CharField(allow_null=True, help_text="The person's `name` property, if set.")


class RecipientSerializer(serializers.Serializer):
    email = serializers.CharField(help_text="Lower-cased, trimmed email address. One row per address.")
    all_marketing = serializers.ChoiceField(
        choices=PreferenceStatus.choices,
        help_text="Status for all marketing messages. `NO_PREFERENCE` means marketing is sent.",
    )
    topics = serializers.DictField(
        child=serializers.ChoiceField(choices=[PreferenceStatus.OPTED_IN, PreferenceStatus.OPTED_OUT]),
        help_text="Explicit topic statuses keyed by topic key. A topic with no preference is left out. "
        "When preferences exist under several casings of the address, `OPTED_OUT` wins per topic.",
    )
    suppression = RecipientSuppressionSerializer(
        allow_null=True, help_text="Active suppression of the address, or null when sends are not blocked."
    )
    persons = RecipientPersonSerializer(
        many=True, help_text="Up to three persons whose `email` property is this address."
    )
    person_count = serializers.IntegerField(help_text="Number of persons whose `email` property is this address.")
    last_sent_at = serializers.DateTimeField(
        allow_null=True, help_text="When an email was last sent to the address, within the last 30 days."
    )
    preferences_updated_at = serializers.DateTimeField(
        allow_null=True, help_text="When the address's preferences last changed, or null when none were recorded."
    )


class RecipientPageSerializer(serializers.Serializer):
    results = RecipientSerializer(many=True, help_text="Recipients on this page, ordered by address.")
    next_cursor = serializers.CharField(
        allow_null=True, help_text="Pass as `cursor` to get the next page. Null on the last page."
    )


class RecipientCoverageSerializer(serializers.Serializer):
    persons_without_email = serializers.IntegerField(
        help_text="Number of persons with no `email` property. They can't be reached by email."
    )


class MessageRecipientsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "hog_flow"
    # Every row is a recipient email address, so a token also needs person:read, like the suppression list.
    required_scopes = ["hog_flow:read", "person:read"]
    serializer_class = _FallbackSerializer

    @validated_request(
        query_serializer=RecipientListQuerySerializer,
        responses={200: OpenApiResponse(response=RecipientPageSerializer)},
        summary="List every email address the team can send to",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        self._require_hog_flow_viewer()
        params = request.validated_query_data
        if "email" in params:
            return self._single_recipient_page(request, params["email"])
        try:
            query = RecipientQuery(
                limit=params["limit"],
                search=params.get("search"),
                filters=tuple(parse_recipient_filter(raw) for raw in params["filter"]),
                cursor=params.get("cursor"),
            )
            page = list_recipients(self.team, cast(User, request.user), query)
        except InvalidRecipientFilter as error:
            raise ValidationError({"filter": [str(error)]})
        return Response(RecipientPageSerializer(page).data)

    @validated_request(
        responses={200: OpenApiResponse(response=RecipientCoverageSerializer)},
        summary="Count persons who can't be reached by email",
    )
    @action(detail=False, methods=["get"])
    def coverage(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        self._require_hog_flow_viewer()
        coverage = {"persons_without_email": count_persons_without_email(self.team, cast(User, request.user))}
        return Response(RecipientCoverageSerializer(coverage).data)

    def _single_recipient_page(self, request: ValidatedRequest, email: str) -> Response:
        recipient = find_recipient(self.team, cast(User, request.user), email)
        if recipient is None:
            raise NotFound("No recipient with this email address.")
        return Response(RecipientPageSerializer(RecipientPage(results=[recipient], next_cursor=None)).data)

    def _require_hog_flow_viewer(self) -> None:
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "viewer"):
            raise PermissionDenied("You need hog_flow viewer access to view recipients.")
