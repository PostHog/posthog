from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.replay_vision.backend.api.observations import ReplayObservationSerializer
from products.replay_vision.backend.experiment_variants import experiment_variants_readout
from products.replay_vision.backend.models.replay_experiment_synthesis import ReplayExperimentSynthesisStatus
from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.scanner_access import scanner_for_recording_derived_read


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


class VariantDigestLineSerializer(serializers.Serializer):
    theme_key = serializers.CharField(help_text="The shared theme this line describes.")
    statement = serializers.CharField(help_text="The theme as it shows up in this variant.")
    count = serializers.IntegerField(help_text="This variant's summaries that match the theme.")


class VariantDifferenceSerializer(serializers.Serializer):
    statement = serializers.CharField(help_text="One thing that differs between variants.")
    theme_key = serializers.CharField(help_text="The shared theme the statement rests on.")
    counts = serializers.DictField(
        child=serializers.IntegerField(), help_text="Summaries matching the theme per variant, `{variant: n}`."
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
    synthesis_observations = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Summaries of this variant the latest synthesis counted: the denominator of its digest and "
            "difference counts. Read those counts as shares of this, not of `observations`. Null before one runs."
        ),
    )
    digest = VariantDigestLineSerializer(
        many=True, allow_null=True, help_text="This variant's digest from the latest synthesis; null before one runs."
    )
    latest_observations = ReplayObservationSerializer(
        many=True, help_text="This variant's most recent observations, newest first."
    )


class VariantsSynthesisStateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=ReplayExperimentSynthesisStatus.choices, help_text="The latest synthesis run's state."
    )
    scanner_version = serializers.IntegerField(help_text="The scanner version that run covered.")
    computed_at = serializers.DateTimeField(allow_null=True, help_text="When that run finished.")


class ExperimentVariantsReadoutSerializer(serializers.Serializer):
    experiment = VariantsExperimentSerializer(
        allow_null=True, help_text="The watched experiment; null if it was deleted."
    )
    window = VariantsWindowSerializer(help_text="The span of observations the counts cover.")
    variants = VariantReadoutSerializer(
        many=True, help_text="One entry per watched variant, plus any variant still holding observations."
    )
    differences = VariantDifferenceSerializer(
        many=True,
        allow_null=True,
        help_text="What differs between variants, from the latest synthesis of the current scanner version; null before one runs.",
    )
    unattributed_count = serializers.IntegerField(
        help_text="Succeeded observations with no attributed variant. They stay out of the synthesis."
    )
    synthesis = VariantsSynthesisStateSerializer(
        allow_null=True, help_text="The latest synthesis run of any state; null if none has run."
    )


class ReplayScannerVariantsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """What users in each variant of an experiment scanner's experiment do, side by side."""

    scope_object = "replay_scanner"
    required_scopes = ["replay_scanner:read", "session_recording:read"]

    @extend_schema(
        responses={
            200: ExperimentVariantsReadoutSerializer,
            400: OpenApiResponse(description="The scanner is not an experiment scanner."),
        },
        description=(
            "Per-variant readout for an experiment scanner: observation counts, distinct people, median "
            "session length and sampling rate per variant, read live, plus the digests and differences of "
            "the latest synthesis."
        ),
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        scanner = scanner_for_recording_derived_read(self)
        if scanner.scanner_type != ScannerType.EXPERIMENT:
            raise ValidationError("Only experiment scanners have variants.")
        readout = experiment_variants_readout(scanner, access=self.user_access_control, viewer_id=request.user.id)
        return Response(ExperimentVariantsReadoutSerializer(readout).data)
