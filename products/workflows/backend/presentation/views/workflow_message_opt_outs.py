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
        trim_whitespace=True,
        help_text="The recipient to opt out, usually the person's email address.",
    )


class WorkflowMessageOptOutResult(models.TextChoices):
    OPTED_OUT = "opted_out", "Opted out"
    ALREADY_OPTED_OUT = "already_opted_out", "Already opted out"
    MISSING_IDENTIFIER = "missing_identifier", "Missing identifier"
    NOT_ON_SAVED_WORKFLOW = "not_on_saved_workflow", "Not on the saved workflow"
    CATEGORY_MISSING = "category_missing", "Category missing"
    WORKFLOW_MISSING = "workflow_missing", "Workflow missing"


class WorkflowMessageOptOutResponseSerializer(serializers.Serializer):
    result = serializers.ChoiceField(
        choices=WorkflowMessageOptOutResult.choices, help_text="Machine-readable result of the opt-out."
    )
    detail = serializers.CharField(help_text="A short result message for the workflow log.")


class WorkflowMessageOptOutViewSet(viewsets.GenericViewSet):
    """Opt the workflow run's recipient out of a message category, for the workflow's "Opt out of messages" step.

    Authenticated by a scoped service JWT the plugin server mints, never by a user credential. The endpoint only
    accepts a category that the saved workflow names, because a test run or a draft sends its own copy of the step
    and could name any category. Anyone who can save the workflow can already edit the opt-out list, so the save
    needs no further access check."""

    authentication_classes = [WorkflowMessageOptOutJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = WorkflowMessageOptOutRequestSerializer

    @extend_schema(
        request=WorkflowMessageOptOutRequestSerializer,
        responses={
            200: WorkflowMessageOptOutResponseSerializer,
            400: OpenApiResponse(
                response=WorkflowMessageOptOutResponseSerializer, description="The step has no recipient to opt out"
            ),
            403: OpenApiResponse(
                response=WorkflowMessageOptOutResponseSerializer,
                description="The saved workflow doesn't opt people out of this category",
            ),
            409: OpenApiResponse(
                response=WorkflowMessageOptOutResponseSerializer, description="The message category was deleted"
            ),
            422: OpenApiResponse(
                response=WorkflowMessageOptOutResponseSerializer, description="The workflow no longer exists"
            ),
        },
        summary="Opt a workflow recipient out of a message category",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        # Both come from the verified token, not the URL or body.
        user = cast(InternalAPIUser, request.user)
        team_id = cast(int, user.current_team_id)
        hog_flow_id = cast(uuid.UUID, request.auth)

        serializer = WorkflowMessageOptOutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category_id: str = serializer.validated_data["category_id"]
        identifier: str = serializer.validated_data["identifier"]

        response = _opt_out(team_id=team_id, hog_flow_id=hog_flow_id, category_id=category_id, identifier=identifier)
        report_team_action(
            Team.objects.get(id=team_id),
            "workflow opt out step ran",
            {
                "result": response.data["result"],
                "all_marketing": category_id == ALL_MARKETING_CATEGORY_ID,
                "hog_flow_id": str(hog_flow_id),
            },
        )
        return response


def _opt_out(*, team_id: int, hog_flow_id: uuid.UUID, category_id: str, identifier: str) -> Response:
    if not identifier:
        return _respond(
            WorkflowMessageOptOutResult.MISSING_IDENTIFIER,
            "There is no email to opt out. Check the step's recipient field, for example {person.properties.email}.",
            status.HTTP_400_BAD_REQUEST,
        )
    try:
        allowed_category_ids = get_workflow_opt_out_category_ids(team_id=team_id, workflow_id=hog_flow_id)
    except WorkflowNotFound:
        return _respond(
            WorkflowMessageOptOutResult.WORKFLOW_MISSING,
            "Workflow no longer exists.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if category_id not in allowed_category_ids:
        return _respond(
            WorkflowMessageOptOutResult.NOT_ON_SAVED_WORKFLOW,
            "The saved workflow doesn't opt people out of this category. Save or publish the workflow, then try again.",
            status.HTTP_403_FORBIDDEN,
        )

    if category_id == ALL_MARKETING_CATEGORY_ID:
        category_key, preference_id, label = None, ALL_MESSAGE_PREFERENCE_CATEGORY_ID, "all marketing messages"
    else:
        try:
            category = get_category(team_id, category_id)
        except MessageCategoryMissing:
            return _category_missing()
        category_key, preference_id, label = category.key, str(category.id), category.name

    if _is_opted_out(team_id, identifier, preference_id):
        return _respond(WorkflowMessageOptOutResult.ALREADY_OPTED_OUT, f"Already opted out of {label}.")
    try:
        add_opt_out(team_id, identifier, category_key, created_by_id=None)
    except MessageCategoryNotFound:
        return _category_missing()
    return _respond(WorkflowMessageOptOutResult.OPTED_OUT, f"Opted out of {label}.")


def _is_opted_out(team_id: int, identifier: str, preference_id: str) -> bool:
    preferences = recipient_preferences(team_id, identifier)
    if preferences is None:
        return False
    try:
        return preference_status(preferences, preference_id) == PreferenceStatus.OPTED_OUT
    except ValueError:
        return False


def _category_missing() -> Response:
    return _respond(
        WorkflowMessageOptOutResult.CATEGORY_MISSING,
        "The message category was deleted. Choose another category in the step.",
        status.HTTP_409_CONFLICT,
    )


def _respond(result: WorkflowMessageOptOutResult, detail: str, http_status: int = status.HTTP_200_OK) -> Response:
    return Response(
        WorkflowMessageOptOutResponseSerializer({"result": result, "detail": detail}).data, status=http_status
    )
