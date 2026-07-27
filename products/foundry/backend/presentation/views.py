"""
DRF views for foundry.

Validate JSON via serializers, call facade methods,
return serialized responses. No business logic here.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api, contracts
from ..facade.enums import BetEventKind, BetVerdict
from .serializers import (
    BetEventSerializer,
    BetNodeSerializer,
    BetSerializer,
    CreateBetEventSerializer,
    CreateBetSerializer,
    RecordVerdictSerializer,
)


class BetViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "bet"
    serializer_class = BetSerializer
    pagination_class = None

    def _get(self, bet_id: str) -> contracts.BetDTO:
        try:
            return api.get_bet(self.team_id, bet_id)
        except api.BetNotFound as e:
            raise exceptions.NotFound(str(e))

    @extend_schema(responses={200: BetSerializer(many=True)}, description="List the project's bets, newest first.")
    def list(self, request: Request, **kwargs) -> Response:
        return Response(BetSerializer(api.list_bets(self.team_id), many=True).data)

    @extend_schema(responses={200: BetSerializer}, description="Retrieve a single bet.")
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        return Response(BetSerializer(self._get(pk)).data)

    @extend_schema(
        request=CreateBetSerializer,
        responses={201: BetSerializer},
        description="Create a bet in the drafted state.",
    )
    def create(self, request: Request, **kwargs) -> Response:
        serializer = CreateBetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dto = api.create_bet(
            contracts.CreateBetInput(team_id=self.team_id, **serializer.validated_data),
            user=request.user,
        )
        return Response(BetSerializer(dto).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses={200: BetSerializer},
        description="Fund a drafted bet: creates its feature flag ('bet-<slug>') and a draft experiment, then moves it to funded.",
    )
    @action(detail=True, methods=["post"])
    def fund(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        self._get(pk)
        try:
            dto = api.fund_bet(
                self.team_id,
                pk,
                user=request.user,
                serializer_context=self.get_serializer_context(),
            )
        except api.BetStateError as e:
            raise exceptions.ValidationError(str(e))
        return Response(BetSerializer(dto).data)

    @extend_schema(
        request=RecordVerdictSerializer,
        responses={200: BetSerializer},
        description="Record the market verdict on an exposed bet.",
    )
    @action(detail=True, methods=["post"])
    def verdict(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        serializer = RecordVerdictSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._get(pk)
        try:
            dto = api.record_verdict(
                self.team_id,
                pk,
                BetVerdict(serializer.validated_data["verdict"]),
                user=request.user,
            )
        except api.BetStateError as e:
            raise exceptions.ValidationError(str(e))
        return Response(BetSerializer(dto).data)

    @extend_schema(
        methods=["GET"],
        responses={200: BetEventSerializer(many=True)},
        description="List the bet's append-only event log, oldest first.",
    )
    @extend_schema(
        methods=["POST"],
        request=CreateBetEventSerializer,
        responses={201: BetEventSerializer},
        description=(
            "Append a typed orchestrator event (run.started, node.spawned, gate.result, "
            "exposure.started, ...) and drive any state transition it implies. Events are "
            "immutable — there is no update or delete."
        ),
    )
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def events(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        self._get(pk)
        if request.method == "GET":
            return Response(BetEventSerializer(api.list_events(self.team_id, pk), many=True).data)
        serializer = CreateBetEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            event = api.record_event(
                self.team_id,
                pk,
                BetEventKind(serializer.validated_data["kind"]),
                serializer.validated_data["payload"],
                user=request.user,
            )
        except api.BetStateError as e:
            raise exceptions.ValidationError(str(e))
        return Response(BetEventSerializer(event).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={200: BetNodeSerializer(many=True)},
        description="List the bet's node tree, as projected from node.spawned/node.finished/node.failed events.",
    )
    @action(detail=True, methods=["get"], pagination_class=None)
    def nodes(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        self._get(pk)
        return Response(BetNodeSerializer(api.list_nodes(self.team_id, pk), many=True).data)
