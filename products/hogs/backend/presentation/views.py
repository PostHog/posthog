"""
DRF views for hogs.

Validate input with serializers, call the facade, and serialize what it returns.
"""

import json
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api
from ..facade.enums import HogActionDecision, HogReportFollowUp, HogReportPriority, HogReportStatus, HogRuleEffect
from .serializers import (
    CompleteActionSerializer,
    CreateHogScheduleSerializer,
    CreateHogSerializer,
    CreateHogTriggerSerializer,
    DecideActionSerializer,
    HogActionSerializer,
    HogEventSerializer,
    HogMessageSerializer,
    HogReportSerializer,
    HogRuleSerializer,
    HogScheduleIdSerializer,
    HogScheduleSerializer,
    HogSerializer,
    HogTriggerIdSerializer,
    HogTriggerSerializer,
    ListMessagesQuerySerializer,
    MessageContentSerializer,
    ProposeActionSerializer,
    PublishReportSerializer,
    ReportFollowUpResultSerializer,
    ReportFollowUpSerializer,
    ReportIdSerializer,
    ReportVerdictSerializer,
    SetRuleSerializer,
    TellHogSerializer,
    UpdateHogSerializer,
)


class HogViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Persistent agents and the chat each one keeps with its owner."""

    # Hogs are a prototype and reuse the task scope: a hog is a standing owner of task runs.
    scope_object = "task"
    scope_object_read_actions = [
        "list",
        "retrieve",
        "messages",
        "schedules",
        "reports",
        "actions",
        "rules",
        "triggers",
    ]
    scope_object_write_actions = [
        "create",
        "partial_update",
        "destroy",
        "send",
        "read",
        "say",
        "tell",
        "done",
        "create_schedule",
        "delete_schedule",
        "publish_report",
        "report_verdict",
        "report_read",
        "report_follow_up",
        "propose_action",
        "decide_action",
        "complete_action",
        "set_rule",
        "create_trigger",
        "delete_trigger",
        "fire_trigger",
    ]
    serializer_class = HogSerializer
    pagination_class = None
    lookup_value_regex = "[0-9a-f-]{36}"

    def _owner(self) -> dict:
        return {"team_id": self.team_id, "user_id": self.request.user.id}

    @validated_request(responses={200: OpenApiResponse(response=HogSerializer(many=True))})
    def list(self, request: Request, **kwargs) -> Response:
        """List the hogs you run, newest chat first, with unread counts."""
        return Response(HogSerializer(api.list_hogs(**self._owner()), many=True).data)

    @validated_request(responses={200: OpenApiResponse(response=HogSerializer)})
    def retrieve(self, request: Request, pk: UUID, **kwargs) -> Response:
        hog = api.get_hog(**self._owner(), hog_id=pk)
        if hog is None:
            raise NotFound()
        return Response(HogSerializer(hog).data)

    @validated_request(CreateHogSerializer, responses={201: OpenApiResponse(response=HogSerializer)})
    def create(self, request: Request, **kwargs) -> Response:
        data = request.validated_data
        hog = api.create_hog(
            **self._owner(),
            name=data["name"],
            emoji=data["emoji"],
            color=data["color"],
            responsibility=data["responsibility"],
            mcp_installation_ids=[str(i) for i in data["mcp_installation_ids"]],
        )
        return Response(HogSerializer(hog).data, status=status.HTTP_201_CREATED)

    @validated_request(UpdateHogSerializer, responses={200: OpenApiResponse(response=HogSerializer)})
    def partial_update(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Update a hog. A hog calls this to save its own responsibility, memory or status."""
        changes = dict(request.validated_data)
        if "mcp_installation_ids" in changes:
            changes["mcp_installation_ids"] = [str(i) for i in changes["mcp_installation_ids"]]
        hog = api.update_hog(**self._owner(), hog_id=pk, changes=changes)
        if hog is None:
            raise NotFound()
        return Response(HogSerializer(hog).data)

    @validated_request(responses={204: OpenApiResponse(description="Deleted")})
    def destroy(self, request: Request, pk: UUID, **kwargs) -> Response:
        if not api.delete_hog(**self._owner(), hog_id=pk):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        query_serializer=ListMessagesQuerySerializer,
        responses={200: OpenApiResponse(response=HogMessageSerializer(many=True))},
    )
    @action(detail=True, methods=["get"])
    def messages(self, request: Request, pk: UUID, **kwargs) -> Response:
        """List the chat with a hog, oldest first."""
        query = request.validated_query_data
        messages = api.list_messages(
            **self._owner(), hog_id=pk, after=query.get("after"), include_internal=query["include_internal"]
        )
        if messages is None:
            raise NotFound()
        return Response(HogMessageSerializer(messages, many=True).data)

    @validated_request(MessageContentSerializer, responses={201: OpenApiResponse(response=HogMessageSerializer)})
    @action(detail=True, methods=["post"])
    def send(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Send a message to a hog as its owner. The hog wakes and decides whether to reply."""
        message = api.send_user_message(**self._owner(), hog_id=pk, content=request.validated_data["content"])
        if message is None:
            raise NotFound()
        return Response(HogMessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @validated_request(responses={204: OpenApiResponse(description="Marked as read")})
    @action(detail=True, methods=["post"])
    def read(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Mark every message in the chat as read by the owner."""
        if not api.mark_read(**self._owner(), hog_id=pk):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(MessageContentSerializer, responses={201: OpenApiResponse(response=HogMessageSerializer)})
    @action(detail=True, methods=["post"])
    def say(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Send a chat message to the owner, as the hog."""
        message = api.hog_say(**self._owner(), hog_id=pk, content=request.validated_data["content"])
        if message is None:
            raise NotFound()
        return Response(HogMessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @validated_request(TellHogSerializer, responses={201: OpenApiResponse(response=HogMessageSerializer)})
    @action(detail=True, methods=["post"])
    def tell(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Send a note from this hog to another hog, which wakes to read it."""
        data = request.validated_data
        try:
            message = api.hog_tell(**self._owner(), hog_id=pk, to_hog_id=data["to_hog_id"], content=data["content"])
        except api.WakeRefused as error:
            raise ValidationError(str(error))
        if message is None:
            raise NotFound()
        return Response(HogMessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @validated_request(responses={200: OpenApiResponse(response=HogSerializer)})
    @action(detail=True, methods=["post"])
    def done(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Mark the hog as no longer working."""
        hog = api.hog_done(**self._owner(), hog_id=pk)
        if hog is None:
            raise NotFound()
        return Response(HogSerializer(hog).data)

    @validated_request(responses={200: OpenApiResponse(response=HogScheduleSerializer(many=True))})
    @action(detail=True, methods=["get"])
    def schedules(self, request: Request, pk: UUID, **kwargs) -> Response:
        """List the schedules that will wake this hog."""
        schedules = api.list_schedules(**self._owner(), hog_id=pk)
        if schedules is None:
            raise NotFound()
        return Response(HogScheduleSerializer(schedules, many=True).data)

    @validated_request(CreateHogScheduleSerializer, responses={201: OpenApiResponse(response=HogScheduleSerializer)})
    @action(detail=True, methods=["post"], url_path="schedules/create")
    def create_schedule(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Schedule a future wake for this hog, once or on a repeat."""
        data = request.validated_data
        try:
            schedule = api.create_schedule(
                **self._owner(),
                hog_id=pk,
                prompt=data["prompt"],
                run_at=data["run_at"],
                cron_expression=data["cron_expression"],
            )
        except api.ScheduleError as error:
            raise ValidationError(str(error))
        if schedule is None:
            raise NotFound()
        return Response(HogScheduleSerializer(schedule).data, status=status.HTTP_201_CREATED)

    @validated_request(HogScheduleIdSerializer, responses={204: OpenApiResponse(description="Deleted")})
    @action(detail=True, methods=["post"], url_path="schedules/delete")
    def delete_schedule(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Delete one of this hog's schedules."""
        if not api.delete_schedule(**self._owner(), hog_id=pk, schedule_id=request.validated_data["schedule_id"]):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(responses={200: OpenApiResponse(response=HogReportSerializer(many=True))})
    @action(detail=True, methods=["get"])
    def reports(self, request: Request, pk: UUID, **kwargs) -> Response:
        """List the reports a hog has published, open ones first."""
        reports = api.list_reports(**self._owner(), hog_id=pk)
        if reports is None:
            raise NotFound()
        return Response(HogReportSerializer(reports, many=True).data)

    @validated_request(PublishReportSerializer, responses={201: OpenApiResponse(response=HogReportSerializer)})
    @action(detail=True, methods=["post"], url_path="reports/create")
    def publish_report(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Publish a report into the owner's chat, as the hog."""
        data = request.validated_data
        report = api.publish_report(
            **self._owner(),
            hog_id=pk,
            title=data["title"],
            summary=data["summary"],
            priority=HogReportPriority(data["priority"]),
            impact=data["impact"],
            proposal=data["proposal"],
            evidence=[dict(item) for item in data["evidence"]],
        )
        if report is None:
            raise NotFound()
        return Response(HogReportSerializer(report).data, status=status.HTTP_201_CREATED)

    @validated_request(ReportVerdictSerializer, responses={200: OpenApiResponse(response=HogReportSerializer)})
    @action(detail=True, methods=["post"], url_path="reports/verdict")
    def report_verdict(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Resolve, dismiss or reopen a report."""
        data = request.validated_data
        report = api.set_report_verdict(
            **self._owner(),
            hog_id=pk,
            report_id=data["report_id"],
            status=HogReportStatus(data["status"]),
            reason=data["reason"],
        )
        if report is None:
            raise NotFound()
        return Response(HogReportSerializer(report).data)

    @validated_request(ReportIdSerializer, responses={200: OpenApiResponse(response=HogReportSerializer)})
    @action(detail=True, methods=["post"], url_path="reports/read")
    def report_read(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Mark a report as opened by the owner."""
        report = api.mark_report_read(**self._owner(), hog_id=pk, report_id=request.validated_data["report_id"])
        if report is None:
            raise NotFound()
        return Response(HogReportSerializer(report).data)

    @validated_request(
        ReportFollowUpSerializer, responses={200: OpenApiResponse(response=ReportFollowUpResultSerializer)}
    )
    @action(detail=True, methods=["post"], url_path="reports/follow_up")
    def report_follow_up(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Wake the hog to implement or investigate one of its reports."""
        data = request.validated_data
        started = api.follow_up_report(
            **self._owner(), hog_id=pk, report_id=data["report_id"], mode=HogReportFollowUp(data["mode"])
        )
        if started is None:
            raise NotFound()
        return Response(ReportFollowUpResultSerializer({"started": started}).data)

    @validated_request(responses={200: OpenApiResponse(response=HogActionSerializer(many=True))})
    @action(detail=True, methods=["get"])
    def actions(self, request: Request, pk: UUID, **kwargs) -> Response:
        """List the actions a hog has proposed, newest first, with each one's status."""
        actions = api.list_actions(**self._owner(), hog_id=pk)
        if actions is None:
            raise NotFound()
        return Response(HogActionSerializer(actions, many=True).data)

    @validated_request(ProposeActionSerializer, responses={201: OpenApiResponse(response=HogActionSerializer)})
    @action(detail=True, methods=["post"], url_path="actions/propose")
    def propose_action(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Ask to do something outside PostHog. The owner's rules, or the owner, decide."""
        data = request.validated_data
        proposed = api.propose_action(
            **self._owner(), hog_id=pk, kind=data["kind"], label=data["label"], draft=data["draft"]
        )
        if proposed is None:
            raise NotFound()
        return Response(HogActionSerializer(proposed).data, status=status.HTTP_201_CREATED)

    @validated_request(DecideActionSerializer, responses={200: OpenApiResponse(response=HogActionSerializer)})
    @action(detail=True, methods=["post"], url_path="actions/decide")
    def decide_action(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Approve or deny an action a hog proposed. Approving wakes the hog to carry it out."""
        data = request.validated_data
        try:
            decided = api.decide_action(
                **self._owner(),
                hog_id=pk,
                action_id=data["action_id"],
                decision=HogActionDecision(data["decision"]),
                always=data["always"],
                draft=data["draft"],
            )
        except api.ApprovalError as error:
            raise ValidationError(str(error))
        if decided is None:
            raise NotFound()
        return Response(HogActionSerializer(decided).data)

    @validated_request(CompleteActionSerializer, responses={200: OpenApiResponse(response=HogActionSerializer)})
    @action(detail=True, methods=["post"], url_path="actions/done")
    def complete_action(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Record that the hog carried out an approved action."""
        data = request.validated_data
        try:
            completed = api.complete_action(
                **self._owner(), hog_id=pk, action_id=data["action_id"], result=data["result"]
            )
        except api.ApprovalError as error:
            raise ValidationError(str(error))
        if completed is None:
            raise NotFound()
        return Response(HogActionSerializer(completed).data)

    @validated_request(responses={200: OpenApiResponse(response=HogRuleSerializer(many=True))})
    @action(detail=True, methods=["get"])
    def rules(self, request: Request, pk: UUID, **kwargs) -> Response:
        """List the owner's standing rules for a hog's actions."""
        rules = api.list_rules(**self._owner(), hog_id=pk)
        if rules is None:
            raise NotFound()
        return Response(HogRuleSerializer(rules, many=True).data)

    @validated_request(SetRuleSerializer, responses={200: OpenApiResponse(response=HogRuleSerializer)})
    @action(detail=True, methods=["post"], url_path="rules/set")
    def set_rule(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Set the standing rule for one kind of action by this hog."""
        data = request.validated_data
        rule = api.set_rule(**self._owner(), hog_id=pk, kind=data["kind"], effect=HogRuleEffect(data["effect"]))
        if rule is None:
            raise NotFound()
        return Response(HogRuleSerializer(rule).data)

    @validated_request(responses={200: OpenApiResponse(response=HogTriggerSerializer(many=True))})
    @action(detail=True, methods=["get"])
    def triggers(self, request: Request, pk: UUID, **kwargs) -> Response:
        """List the triggers that wake this hog on an outside event."""
        triggers = api.list_triggers(**self._owner(), hog_id=pk)
        if triggers is None:
            raise NotFound()
        return Response(HogTriggerSerializer(triggers, many=True).data)

    @validated_request(CreateHogTriggerSerializer, responses={201: OpenApiResponse(response=HogTriggerSerializer)})
    @action(detail=True, methods=["post"], url_path="triggers/create")
    def create_trigger(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Create a trigger: an address that wakes this hog when something posts an event to it."""
        data = request.validated_data
        try:
            trigger = api.create_trigger(
                **self._owner(), hog_id=pk, name=data["name"], instructions=data["instructions"]
            )
        except api.TriggerError as error:
            raise ValidationError(str(error))
        if trigger is None:
            raise NotFound()
        return Response(HogTriggerSerializer(trigger).data, status=status.HTTP_201_CREATED)

    @validated_request(HogTriggerIdSerializer, responses={204: OpenApiResponse(description="Deleted")})
    @action(detail=True, methods=["post"], url_path="triggers/delete")
    def delete_trigger(self, request: Request, pk: UUID, **kwargs) -> Response:
        """Delete one of this hog's triggers."""
        if not api.delete_trigger(**self._owner(), hog_id=pk, trigger_id=request.validated_data["trigger_id"]):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={202: OpenApiResponse(response=HogEventSerializer)})
    @action(detail=True, methods=["post"], url_path="triggers/(?P<trigger_id>[0-9a-f-]{36})/fire")
    def fire_trigger(self, request: Request, pk: UUID, trigger_id: UUID, **kwargs) -> Response:
        """Deliver an event to a trigger. The whole JSON body is the event.

        Send an `Idempotency-Key` header, or an `id` in the body, so a repeated delivery is dropped.
        """
        body = request.data
        external_id = request.headers.get("Idempotency-Key") or (body.get("id") if isinstance(body, dict) else None)
        event = api.fire_trigger(
            **self._owner(),
            hog_id=pk,
            trigger_id=trigger_id,
            payload=json.dumps(body, indent=2, default=str),
            external_id=str(external_id)[:200] if external_id else None,
        )
        if event is None:
            raise NotFound()
        return Response(HogEventSerializer(event).data, status=status.HTTP_202_ACCEPTED)
