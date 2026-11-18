import uuid
from typing import Any, cast

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import InternalAPIUser
from posthog.event_usage import report_team_action
from posthog.models import Team

from products.messaging.backend.facade.categories import MessageCategoryMissing, get_category
from products.messaging.backend.facade.preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageCategoryNotFound,
    PreferenceStatus,
    add_opt_out,
    preference_status,
    recipient_preferences,
)
from products.workflows.backend.facade.api import WorkflowNotFound, get_workflow_opt_out_category_ids
from products.workflows.backend.facade.service_jwt import WORKFLOW_MESSAGE_OPT_OUT_PURPOSE
from products.workflows.backend.facade.workflows import ALL_MARKETING_CATEGORY_ID
from products.workflows.backend.presentation.views.workflow_step_auth import WorkflowStepJWTAuthentication


class WorkflowMessageOptOutJWTAuthentication(WorkflowStepJWTAuthentication):
    purpose = WORKFLOW_MESSAGE_OPT_OUT_PURPOSE


class WorkflowMessageOptOutRequestSerializer(serializers.Serializer):
    category_id = serializers.CharField(
        max_length=64,
        help_text='ID of the message category to opt out of, or "$all" for all marketing messages.',
    )
    identifier = serializers.CharField(
        max_length=512,
        allow_blank=True,
        help_text="The recipient to opt out, usually the person's email address.",
    )


class WorkflowMessageOptOutResult(models.TextChoices):
    OPTED_OUT = "opted_out", "Opted out"
    ALREADY_OPTED_OUT = "already_opted_out", "Already opted out"
    MISSING_IDENTIFIER = "missing_identifier", "Missing identifier"
    NOT_ON_SAVED_WORKFLOW = "not_on_saved_workflow", "Not on the saved workflow"
    CATEGORY_UNUSABLE = "category_unusable", "Category deleted or transactional"
    WORKFLOW_MISSING = "workflow_missing", "Workflow missing"


class WorkflowMessageOptOutResponseSerializer(serializers.Serializer):
    result = serializers.ChoiceField(
        choices=WorkflowMessageOptOutResult.choices, help_text="Machine-readable result of the opt-out."
    )
    detail = serializers.CharField(help_text="A short result message for the workflow log.")


class _Refused(Exception):
    def __init__(self, result: WorkflowMessageOptOutResult, http_status: int, detail: str) -> None:
        self.result, self.http_status, self.detail = result, http_status, detail


class WorkflowMessageOptOutViewSet(viewsets.GenericViewSet):
    """Opt the run's recipient out of a message category, for the workflow's "Opt out of messages" step.

    Authenticated by a scoped service JWT the plugin server mints. A test run or a draft sends its own copy of the
    step, so the endpoint only accepts a category the saved workflow names. Saving the step checked the access."""

    authentication_classes = [WorkflowMessageOptOutJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowMessageOptOutRequestSerializer

    @extend_schema(
        request=WorkflowMessageOptOutRequestSerializer,
        responses={
            200: WorkflowMessageOptOutResponseSerializer,
            **{
                code: OpenApiResponse(response=WorkflowMessageOptOutResponseSerializer) for code in (400, 403, 409, 422)
            },
        },
        summary="Opt a workflow recipient out of a message category",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Both come from the verified token, not the URL or body.
        team_id = cast(int, cast(InternalAPIUser, request.user).current_team_id)
        hog_flow_id = cast(uuid.UUID, request.auth)
        serializer = WorkflowMessageOptOutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category_id: str = serializer.validated_data["category_id"]

        try:
            result, detail = _opt_out(team_id, hog_flow_id, category_id, serializer.validated_data["identifier"])
            http_status: int = status.HTTP_200_OK
        except _Refused as refused:
            result, detail, http_status = refused.result, refused.detail, refused.http_status
        report_team_action(
            Team.objects.get(id=team_id),
            "workflow opt out step ran",
            {
                "result": result,
                "all_marketing": category_id == ALL_MARKETING_CATEGORY_ID,
                "hog_flow_id": str(hog_flow_id),
            },
        )
        return Response(
            WorkflowMessageOptOutResponseSerializer({"result": result, "detail": detail}).data, status=http_status
        )


def _opt_out(
    team_id: int, hog_flow_id: uuid.UUID, category_id: str, identifier: str
) -> tuple[WorkflowMessageOptOutResult, str]:
    if not identifier:
        raise _Refused(
            WorkflowMessageOptOutResult.MISSING_IDENTIFIER,
            status.HTTP_400_BAD_REQUEST,
            "There is no email to opt out. Check the step's recipient field, for example {person.properties.email}.",
        )
    try:
        allowed_category_ids = get_workflow_opt_out_category_ids(team_id=team_id, workflow_id=hog_flow_id)
    except WorkflowNotFound:
        raise _Refused(
            WorkflowMessageOptOutResult.WORKFLOW_MISSING,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Workflow no longer exists.",
        )
    if category_id not in allowed_category_ids:
        raise _Refused(
            WorkflowMessageOptOutResult.NOT_ON_SAVED_WORKFLOW,
            status.HTTP_403_FORBIDDEN,
            "The saved workflow doesn't opt people out of this category. Save or publish the workflow, then try again.",
        )

    unusable = _Refused(
        WorkflowMessageOptOutResult.CATEGORY_UNUSABLE,
        status.HTTP_409_CONFLICT,
        "The message category was deleted or is transactional. Choose a marketing category in the step.",
    )
    if category_id == ALL_MARKETING_CATEGORY_ID:
        category_key, preference_id, label = None, ALL_MESSAGE_PREFERENCE_CATEGORY_ID, "all marketing messages"
    else:
        try:
            category = get_category(team_id, category_id)
        except MessageCategoryMissing:
            raise unusable
        # Transactional sends ignore opt-outs, so an opt-out there would report success and change nothing.
        if category.category_type != "marketing":
            raise unusable
        category_key, preference_id, label = category.key, str(category.id), category.name

    preferences = recipient_preferences(team_id, identifier) or {}
    try:
        already_opted_out = preference_status(preferences, preference_id) == PreferenceStatus.OPTED_OUT
    except ValueError:
        already_opted_out = False
    # Opt out even when already opted out, so a retry after a failed Customer.io sync queues that sync again.
    try:
        add_opt_out(team_id, identifier, category_key, created_by_id=None)
    except MessageCategoryNotFound:
        raise unusable
    if already_opted_out:
        return WorkflowMessageOptOutResult.ALREADY_OPTED_OUT, f"Already opted out of {label}."
    return WorkflowMessageOptOutResult.OPTED_OUT, f"Opted out of {label}."
