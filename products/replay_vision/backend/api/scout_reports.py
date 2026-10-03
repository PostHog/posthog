from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.replay_vision.backend.scanner_access import scanner_for_recording_derived_read
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.signals.backend.facade import api as signals_facade
from products.signals.backend.scout_harness.views import ScoutCanonicalTeamAccessPermission

# Reused rather than redeclared: two components with this name generate an incorrect schema, and
# the charts here are the same shape the inbox renders.
from products.signals.backend.serializers import ReportChartSerializer


class ScoutReportSerializer(serializers.Serializer):
    """One report a scanner's scout filed. Enough to read it in Replay Vision; the inbox owns the
    full record (status, priority, reviewers, run trail)."""

    report_id = serializers.CharField(help_text="The report's id, as used by the Signals inbox.")
    skill_name = serializers.CharField(help_text="The scout that filed it, as its skill name.")
    filed_at = serializers.DateTimeField(
        help_text="When the run that filed this report started. Later edits do not move it."
    )
    title = serializers.CharField(help_text="The report's title. Empty when the scout left it unset.")
    summary = serializers.CharField(help_text="The report body, as markdown. Empty when the scout left it unset.")
    charts = ReportChartSerializer(
        many=True,
        help_text=(
            "Charts the scout attached. The summary places one inline with a "
            "`[label](chart:<chart_id>)` link; any it does not place render after the body."
        ),
    )


class ScannerScoutReportViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read-only access to the reports filed by one scanner's scouts.

    This exists rather than reading the project-wide report endpoint from the frontend because that
    endpoint scopes to the team alone: it cannot tell whether a report came from *this* scanner, so a
    project member without access to the scanner could read its recording-derived reports by id.
    """

    # The reports these scouts filed are canonical-team rows, so access is checked against that
    # team and not just the environment in the URL.
    # Appended to the standard stack by `TeamAndOrgViewSetMixin.get_permissions`.
    permission_classes = [ScoutCanonicalTeamAccessPermission]
    scope_object = "replay_scanner"
    # `task` is the scope object Signals gates its own report reads on, so a token that cannot read
    # reports there cannot read them through a scanner either.
    required_scopes = ["replay_scanner:read", "session_recording:read", "task:read"]
    serializer_class = ScoutReportSerializer

    # A scanner's roster is small, and this backs a list a person reads.
    MAX_REPORTS = 50

    def _scanner_id(self) -> str:
        # Scout reports are written from this scanner's observations, so they clear the same bar the
        # observations do.
        return str(scanner_for_recording_derived_read(self).id)

    @extend_schema(
        responses=ScoutReportSerializer(many=True),
        description="Reports filed by this scanner's scouts, newest first.",
    )
    def list(self, request: Request, **kwargs: object) -> Response:
        reports = signals_facade.scout_reports_for_source(
            self.team_id, SCOUT_SOURCE_PRODUCT, self._scanner_id(), limit=self.MAX_REPORTS
        )
        return Response(ScoutReportSerializer(reports, many=True).data)

    @extend_schema(
        responses=ScoutReportSerializer,
        description="One report filed by this scanner's scouts.",
    )
    def retrieve(self, request: Request, pk: str, **kwargs: object) -> Response:
        reports = signals_facade.scout_reports_for_source(
            self.team_id, SCOUT_SOURCE_PRODUCT, self._scanner_id(), report_id=pk
        )
        if not reports:
            # A report belonging to another scanner is indistinguishable from one that doesn't exist,
            # so the caller learns nothing about scanners they can't see.
            raise NotFound()
        return Response(ScoutReportSerializer(reports[0]).data)
