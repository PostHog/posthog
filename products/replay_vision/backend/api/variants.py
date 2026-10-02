from typing import Any, cast

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.rate_limit import AIBurstRateThrottle, AISustainedRateThrottle
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.search_attributes import POSTHOG_SCANNER_ID_KEY, POSTHOG_TEAM_ID_KEY

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.api.observations import ReplayObservationSerializer
from products.replay_vision.backend.consent import AI_CONSENT_REQUIRED_CODE, is_ai_data_processing_approved
from products.replay_vision.backend.experiment_variants import experiment_variants_readout
from products.replay_vision.backend.models.replay_experiment_synthesis import (
    ReplayExperimentSynthesis,
    ReplayExperimentSynthesisStatus,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.scanner_access import scanner_for_recording_derived_read
from products.replay_vision.backend.temporal.constants import (
    EXPERIMENT_SYNTHESIS_EXECUTION_TIMEOUT,
    EXPERIMENT_SYNTHESIS_WORKFLOW_NAME,
    SYNTHESIS_FAILED_TO_START,
    build_experiment_synthesis_workflow_id,
    on_demand_priority,
)
from products.replay_vision.backend.temporal.synthesis_types import ExperimentSynthesisInputs
from products.replay_vision.backend.variant_synthesis import (
    MIN_OBSERVATIONS_FOR_SYNTHESIS,
    fail_run,
    start_synthesis_run,
    synthesis_observations,
    up_to_date_run,
)

logger = structlog.get_logger(__name__)


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
    error = serializers.CharField(help_text="Why that run failed; empty unless it did.")


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
        scanner = self._experiment_scanner()
        readout = experiment_variants_readout(scanner, access=self.user_access_control, viewer_id=request.user.id)
        return Response(ExperimentVariantsReadoutSerializer(readout).data)

    @extend_schema(
        request=None,
        responses={
            200: VariantsSynthesisStateSerializer,
            202: VariantsSynthesisStateSerializer,
            400: OpenApiResponse(description="Not an experiment scanner, AI analysis is off, or too few summaries."),
            403: OpenApiResponse(description="The caller may not edit this scanner."),
            503: OpenApiResponse(description="The run could not be started."),
        },
        description=(
            "Start a synthesis of what users in each variant do differently. Returns 202 with the run to poll "
            "on `GET variants/`; while a run is in flight, returns that run instead of starting another. "
            "Returns 200 with the latest run when no summary has completed since it started."
        ),
    )
    @action(
        detail=False,
        methods=["post"],
        required_scopes=["replay_scanner:write", "session_recording:read"],
        throttle_classes=[AIBurstRateThrottle, AISustainedRateThrottle],
    )
    def refresh(self, request: Request, **kwargs: Any) -> Response:
        scanner = self._experiment_scanner()
        user = cast(User, request.user)
        # A run spends model calls on the team's behalf, so it takes the access that editing the scanner does.
        if not UserAccessControl(user=user, team=self.team).check_access_level_for_object(
            scanner, required_level="editor"
        ):
            raise PermissionDenied("Refreshing the synthesis requires editor access to this scanner.")
        if not is_ai_data_processing_approved(self.team_id):
            raise ValidationError(
                "Your organization needs to allow AI analysis before you can synthesize variants.",
                code=AI_CONSENT_REQUIRED_CODE,
            )
        summaries = synthesis_observations(scanner, scanner.scanner_version).count()
        if summaries < MIN_OBSERVATIONS_FOR_SYNTHESIS:
            raise ValidationError(
                f"There are {summaries} summaries with a variant so far. A synthesis needs at least "
                f"{MIN_OBSERVATIONS_FOR_SYNTHESIS}, so check back once more sessions are scanned."
            )
        current = up_to_date_run(scanner)
        if current is not None:
            return Response(VariantsSynthesisStateSerializer(current).data, status=status.HTTP_200_OK)
        synthesis, created = start_synthesis_run(scanner, user=user)
        if created:
            try:
                _start_synthesis_workflow(scanner, synthesis)
            except Exception:
                logger.exception("replay_vision.experiment_synthesis.start_failed", scanner_id=str(scanner.id))
                return Response(
                    {"detail": "The synthesis couldn't start. Try again in a few minutes."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            report_user_action(
                user,
                "replay_vision_experiment_synthesis_requested",
                {"scanner_id": str(scanner.id), "scanner_version": synthesis.scanner_version, "summaries": summaries},
                team=self.team,
                request=request,
            )
        return Response(VariantsSynthesisStateSerializer(synthesis).data, status=status.HTTP_202_ACCEPTED)

    def _experiment_scanner(self) -> ReplayScanner:
        scanner = scanner_for_recording_derived_read(self)
        if scanner.scanner_type != ScannerType.EXPERIMENT:
            raise ValidationError("Only experiment scanners have variants.")
        return scanner


def _start_synthesis_workflow(scanner: ReplayScanner, synthesis: ReplayExperimentSynthesis) -> None:
    try:
        client = sync_connect()
        async_to_sync(client.start_workflow)(  # type: ignore[misc]
            EXPERIMENT_SYNTHESIS_WORKFLOW_NAME,  # type: ignore[arg-type]
            ExperimentSynthesisInputs(synthesis_id=synthesis.id, team_id=scanner.team_id),  # type: ignore[arg-type]
            id=build_experiment_synthesis_workflow_id(synthesis.id),
            task_queue=settings.REPLAY_VISION_TASK_QUEUE,
            execution_timeout=EXPERIMENT_SYNTHESIS_EXECUTION_TIMEOUT,
            priority=on_demand_priority(scanner.team_id),
            search_attributes=TypedSearchAttributes(
                search_attributes=[
                    SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=scanner.team_id),
                    SearchAttributePair(key=POSTHOG_SCANNER_ID_KEY, value=str(scanner.id)),
                ]
            ),
        )
    except WorkflowAlreadyStartedError:
        pass
    except Exception:
        # Without a workflow nothing would ever finish the row, and it would block the next run.
        fail_run(synthesis.id, scanner.team_id, SYNTHESIS_FAILED_TO_START)
        raise
