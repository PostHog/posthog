from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.rbac.user_access_control import UserAccessControl

from products.replay_vision.backend.scanner_access import scanner_for_recording_derived_read
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.signals.backend.facade import api as signals_facade
from products.signals.backend.scout_harness.serializers import SignalScoutConfigSerializer, SignalScoutCreateSerializer
from products.signals.backend.scout_harness.views import ScoutCanonicalTeamAccessPermission


class ScannerScoutCreateSerializer(SignalScoutCreateSerializer):
    """A scout to stand up for this scanner. The scanner comes from the URL, never the body: it is
    what the caller's access is checked against, and what the scout is recorded as belonging to.

    Inherits the Signals scout definition so a scout created here clears the same name and prompt-size
    bars as one created through the generic endpoint.
    """

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        # Bundling files with a prompt is the generic endpoint's affordance; this one creates a scout
        # from a template in the Vision UI.
        fields.pop("files", None)
        return fields


class ScannerScoutCreateResponseSerializer(serializers.Serializer):
    """The scout that now watches this scanner."""

    created = serializers.BooleanField(
        help_text="False when a scout of this name already existed and the supplied config was applied to it."
    )
    config = SignalScoutConfigSerializer(help_text="The scout's config, including the source recorded for it.")


class ScannerScoutViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Creating the scouts that watch one scanner.

    Scout creation lives here rather than going straight to the Signals scout endpoint because the
    scanner a scout belongs to is recorded on its config and later trusted: the reports endpoint
    serves a scanner's reports on the strength of that record. Signals cannot check whether a caller
    may act on a Replay Vision scanner, so the check, and the stamping, happen here.
    """

    # Scout rows canonicalize to the parent team on save, so a caller authorized against a child
    # environment would otherwise read and write another team's rows. Signals' own scout endpoints
    # carry this for the same reason.
    # Appended to the standard stack by `TeamAndOrgViewSetMixin.get_permissions`.
    permission_classes = [ScoutCanonicalTeamAccessPermission]
    scope_object = "replay_scanner"
    # Every object this touches: the scanner and the recordings behind it, the skill a scout is,
    # and the scout config itself.
    required_scopes = ["replay_scanner:write", "session_recording:read", "llm_skill:write", "signal_scout:write"]
    serializer_class = ScannerScoutCreateSerializer

    def _scanner_for_writing(self) -> Any:
        scanner = scanner_for_recording_derived_read(self)
        # Creating a scout points an agent at this scanner's observations on a schedule and spends
        # credits doing it, so it takes the same editor access as changing the scanner itself.
        access = UserAccessControl(user=cast(User, self.request.user), team=self.team)
        if not access.check_access_level_for_object(scanner, required_level="editor"):
            raise PermissionDenied("Creating a scout for this scanner requires editor access to it.")
        return scanner

    @extend_schema(
        request=ScannerScoutCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=ScannerScoutCreateResponseSerializer, description="The scout and its config were created."
            ),
            200: OpenApiResponse(
                response=ScannerScoutCreateResponseSerializer,
                description="The scout already existed; the supplied config was applied.",
            ),
            403: OpenApiResponse(description="The caller may not edit this scanner."),
        },
        description="Create a scout that watches this scanner, recorded as belonging to it.",
    )
    def create(self, request: Any, **kwargs: Any) -> Response:
        scanner = self._scanner_for_writing()
        payload = ScannerScoutCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        validated = payload.validated_data

        # Scouts live on the canonical team, so the skill-authoring bar is checked against that team
        # rather than the URL's: `create_scout_for_source` runs it on whichever team it is given.
        canonical_team = self.team.parent_team or self.team
        result = signals_facade.create_scout_for_source(
            team=canonical_team,
            user=request.user,
            name=validated["name"],
            description=validated["description"],
            body=validated["body"],
            files=[],
            config_options=validated.get("config", {}),
            request=request,
            serializer_context={"project_id": self.team.project_id, "request": request},
            # From the URL the caller's access was checked against, never from the body.
            source_product=SCOUT_SOURCE_PRODUCT,
            source_id=str(scanner.id),
        )
        return Response(
            ScannerScoutCreateResponseSerializer({"created": result.created, "config": result.config}).data,
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )
