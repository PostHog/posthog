from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.replay_vision.backend.api.observations import ReplayObservationSerializer
from products.replay_vision.backend.experiment_variants import experiment_variants_readout
from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.scanner_access import scanner_for_recording_derived_read
from products.signals.backend.scout_harness.views import ScoutCanonicalTeamAccessPermission


class VariantsExperimentSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="The experiment's id.")
    name = serializers.CharField(help_text="The experiment's name.")
    status = serializers.CharField(help_text="draft, running, paused, exposure_frozen, or stopped.")
    start_date = serializers.DateTimeField(allow_null=True, help_text="When the experiment launched.")
    end_date = serializers.DateTimeField(allow_null=True, help_text="When the experiment ended; null while it runs.")
    planned_duration_days = serializers.FloatField(
        allow_null=True, help_text="The experiment's recommended running time in days, when one was set."
    )
    current_day = serializers.IntegerField(
        allow_null=True,
        help_text="The experiment's day number: 1 on its launch day, frozen once it ends. Null before launch.",
    )


class VariantsWindowSerializer(serializers.Serializer):
    total_observations = serializers.IntegerField(
        help_text="Succeeded observations of this scanner, attributed to a variant or not."
    )
    first_observation_at = serializers.DateTimeField(
        allow_null=True, help_text="When the earliest of those observations completed."
    )
    last_observation_at = serializers.DateTimeField(
        allow_null=True, help_text="When the latest of those observations completed."
    )


class VariantAnalysisLineSerializer(serializers.Serializer):
    theme = serializers.CharField(help_text="A short label for the theme, shared across variants.")
    statement = serializers.CharField(help_text="How the theme shows up for this variant.")
    count = serializers.IntegerField(
        help_text="How many of this variant's summaries the analysis read show the theme, as the scout counted them."
    )
    example_observation_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="Observations of this variant the scout cited for the theme. Ids it can't back are dropped.",
    )


class VariantAnalysisDifferenceSerializer(serializers.Serializer):
    theme = serializers.CharField(help_text="The theme the difference rests on.")
    statement = serializers.CharField(help_text="What differs between the variants.")
    counts = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Summaries the analysis read that show the theme, per variant key, as the scout counted them.",
    )


class VariantsAnalysisStateSerializer(serializers.Serializer):
    scout_config_id = serializers.CharField(help_text="The variant analysis scout's config id.")
    scout_enabled = serializers.BooleanField(help_text="Whether the scout runs on its schedule.")
    recorded_at = serializers.DateTimeField(
        allow_null=True, help_text="When the run behind the newest analysis started; null before its first run."
    )
    scanner_version = serializers.IntegerField(
        allow_null=True, help_text="The scanner version the newest analysis covered."
    )
    current = serializers.BooleanField(
        help_text=(
            "Whether the newest analysis covers the scanner's current version. When false, digests and "
            "differences are null until the scout's next run."
        )
    )


class VariantReadoutSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="The variant key.")
    observations = serializers.IntegerField(help_text="Succeeded observations attributed to this variant.")
    distinct_people = serializers.IntegerField(help_text="Distinct people (by distinct id) behind those observations.")
    median_session_duration_s = serializers.FloatField(
        allow_null=True, help_text="Median scanned session length in seconds; null with no observations."
    )
    sampling_rate = serializers.FloatField(
        allow_null=True,
        help_text=(
            "The 0..1 rate this variant was sampled at when its latest observation was dispatched. Read even "
            "counts against it: balanced sampling gives a small variant a higher rate."
        ),
    )
    analysis_observations = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Summaries of this variant the analysis read: the denominator of its digest and difference counts. "
            "Null without a current analysis."
        ),
    )
    digest = VariantAnalysisLineSerializer(
        many=True,
        allow_null=True,
        help_text="This variant's most notable themes from the variant analysis. Null without a current analysis.",
    )
    latest_observations = ReplayObservationSerializer(
        many=True, help_text="This variant's most recent observations, newest first."
    )


class ExperimentVariantsReadoutSerializer(serializers.Serializer):
    experiment = VariantsExperimentSerializer(
        allow_null=True, help_text="The watched experiment; null if it was deleted."
    )
    window = VariantsWindowSerializer(help_text="The span of observations the counts cover.")
    variants = VariantReadoutSerializer(
        many=True, help_text="One entry per watched variant, plus any variant still holding observations."
    )
    differences = VariantAnalysisDifferenceSerializer(
        many=True,
        allow_null=True,
        help_text="What differs between variants, from the variant analysis. Null without a current analysis.",
    )
    unattributed_count = serializers.IntegerField(help_text="Succeeded observations with no attributed variant.")
    analysis = VariantsAnalysisStateSerializer(
        allow_null=True, help_text="The scanner's variant analysis scout and its newest run; null when none is set up."
    )


class _ReadoutSchema(PostHogAutoSchema):
    """Keeps drf-spectacular from wrapping the ``list`` response in an array: the readout is one object."""

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class ReplayScannerVariantsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """What users in each variant of an experiment scanner's experiment do, side by side."""

    # The variant analysis is read from the scout's canonical-team records, so access is checked
    # against that team and not just the environment in the URL.
    # Appended to the standard stack by `TeamAndOrgViewSetMixin.get_permissions`.
    permission_classes = [ScoutCanonicalTeamAccessPermission]
    schema = _ReadoutSchema()
    scope_object = "replay_scanner"
    required_scopes = ["replay_scanner:read", "session_recording:read"]

    @extend_schema(
        # Pinned: the schema override renames the operation to `_retrieve`, and the MCP tool and its
        # callers use the `_list` name.
        operation_id="vision_scanners_variants_list",
        responses={
            200: ExperimentVariantsReadoutSerializer,
            400: OpenApiResponse(description="The scanner is not an experiment scanner."),
        },
        description=(
            "Per-variant readout for an experiment scanner: observation counts, distinct people, median "
            "session length, sampling rate and latest observations per variant, read live, plus the digests "
            "and differences of the scanner's variant analysis scout."
        ),
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        scanner = scanner_for_recording_derived_read(self)
        if scanner.scanner_type != ScannerType.EXPERIMENT:
            raise ValidationError("Only experiment scanners have variants.")
        readout = experiment_variants_readout(scanner, access=self.user_access_control, viewer_id=request.user.id)
        return Response(ExperimentVariantsReadoutSerializer(readout).data)
