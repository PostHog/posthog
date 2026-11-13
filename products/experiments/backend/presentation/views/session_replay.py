"""Actions for the session recording features: session context, in-session exposure, session buckets and session event deltas."""

import logging
from typing import Any, cast

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.permissions import is_service_auth, posthog_feature_flag_enabled
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
    SessionBucketsBurstRateThrottle,
    SessionBucketsSustainedRateThrottle,
    SessionContextsBurstRateThrottle,
    SessionContextsSustainedRateThrottle,
    SessionEventDeltasBurstRateThrottle,
    SessionEventDeltasSustainedRateThrottle,
)
from posthog.session_recordings.models.session_recording import SessionRecording

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.facade.replay import resolve_in_session_exposure_semantics

# TODO: Route through facade instead of direct import
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.presentation.serializers.session_replay import (
    ExperimentInSessionExposureSerializer,
    ExperimentSessionBucketRequestSerializer,
    ExperimentSessionBucketResponseSerializer,
    ExperimentSessionContextResponseSerializer,
    ExperimentSessionContextsRequestSerializer,
    ExperimentSessionContextsResponseSerializer,
    ExperimentSessionEventDeltaRequestSerializer,
    ExperimentSessionEventDeltaResponseSerializer,
)
from products.experiments.backend.session_buckets import (
    ExperimentSessionBucket,
    SessionBucketUnavailable,
    finalize_session_bucket,
    get_experiment_session_bucket,
)
from products.experiments.backend.session_context import get_session_experiment_context, get_session_experiment_contexts
from products.experiments.backend.session_event_deltas import (
    EXPERIMENT_BEHAVIOR_COMPARISON_FLAG,
    SessionEventDeltasUnavailable,
    all_card_session_ids,
    finalize_watch_cards,
    get_experiment_session_event_deltas,
)

logger = logging.getLogger(__name__)


def _accessible_session_ids(
    request: Request, user_access_control: UserAccessControl, team: Team, session_ids: list[str]
) -> list[str]:
    """Drop session ids whose recording the viewer is denied at the object level.

    The resource-level `session_recording` check the session-context actions run first grants
    access to the replay product, not to every recording in it: a recording can carry its own
    access controls, which the replay retrieve endpoint enforces via `check_object_permissions`.
    Without this filter a viewer denied one recording could still read which experiments it saw.

    Object-level controls can only target a recording that has a Postgres row, so an id without
    one is returned as accessible. That matches replay, which serves those ids from an unsaved
    `SessionRecording` no access control row can point at.
    """
    if is_service_auth(request):
        # Mirrors AccessControlPermission.has_object_permission: service credentials authenticate
        # as synthetic users that UserAccessControl cannot evaluate, so they are gated by API
        # scope and project membership instead of object-level RBAC.
        return session_ids

    recordings = SessionRecording.objects.filter(team=team, session_id__in=session_ids)
    denied_ids = {
        recording.session_id
        for recording in recordings
        if not user_access_control.check_access_level_for_object(recording, required_level="viewer")
    }
    return [session_id for session_id in session_ids if session_id not in denied_ids]


class ExperimentSessionReplayMixin(TeamAndOrgViewSetMixin):
    @extend_schema(
        description=(
            "Resolve which experiments (and variants) a session recording saw. Variants come from the session's "
            "$feature_flag_called events and stamped $feature/<key> event properties — flag evaluation, which may "
            "differ from an experiment's exposure criteria."
        ),
        parameters=[
            OpenApiParameter(
                name="session_id",
                location=OpenApiParameter.QUERY,
                type=str,
                required=True,
                description="ID of the session recording to resolve experiment context for.",
            ),
        ],
        responses={200: OpenApiResponse(response=ExperimentSessionContextResponseSerializer)},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="session_context",
        required_scopes=["experiment:read", "session_recording:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def session_context(self, request: Request, **kwargs: Any) -> Response:
        session_id = (request.query_params.get("session_id") or "").strip()
        if not session_id:
            raise ValidationError({"session_id": ["This field is required."]})

        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading session experiment context requires session replay access.")

        if not _accessible_session_ids(request, self.user_access_control, self.team, [session_id]):
            raise PermissionDenied("You don't have access to this recording.")

        # detail=False actions skip the automatic list-action ACL filtering, so filter here —
        # private experiments must not leak into another user's session context.
        experiments = self.user_access_control.filter_queryset_by_access_level(
            Experiment.objects.filter(team_id=self.team.pk)
        )
        # user threads through to the HogQL queries: exposure criteria can filter on arbitrary
        # properties, which must respect the viewer's property-level access control.
        items = get_session_experiment_context(
            team=self.team, session_id=session_id, experiments=experiments, user=cast(User, request.user)
        )
        if items is None:
            raise NotFound("Recording not found")

        serializer = ExperimentSessionContextResponseSerializer({"session_id": session_id, "results": items})
        return Response(serializer.data)

    @validated_request(
        request_serializer=ExperimentSessionContextsRequestSerializer,
        responses={200: OpenApiResponse(response=ExperimentSessionContextsResponseSerializer)},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="session_contexts",
        required_scopes=["experiment:read", "session_recording:read"],
        # Not the ClickHouse* pair the single-session action uses: that pair only limits
        # personal-API-key traffic, and this endpoint's primary caller is the
        # session-authenticated web app.
        throttle_classes=[SessionContextsBurstRateThrottle, SessionContextsSustainedRateThrottle],
    )
    def session_contexts(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Resolve experiment context for a batch of session recordings.

        Batch variant of `session_context`, used to prefetch the replay player's experiments
        box for a whole recordings list in one request. POST because the id list doesn't fit a
        query string; the endpoint only reads. Already-computed sessions are served from (and
        cold ones written to) the same short-lived per-viewer cache the single-session endpoint
        uses, so opening any prefetched recording renders its context instantly. Sessions whose
        recording metadata doesn't exist yet are omitted from the response, as are recordings
        the caller can't access and sessions beyond the batch's recording-day budget (each
        distinct recording day costs its own set of ClickHouse scans, so only the most recent
        days are computed per request).
        """
        session_ids: list[str] = request.validated_data["session_ids"]

        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading session experiment context requires session replay access.")

        # Denied recordings are omitted rather than rejecting the batch, matching how the response
        # already treats a session whose recording metadata doesn't exist.
        session_ids = _accessible_session_ids(request, self.user_access_control, self.team, session_ids)

        # detail=False actions skip the automatic list-action ACL filtering, so filter here —
        # private experiments must not leak into another user's session context.
        experiments = self.user_access_control.filter_queryset_by_access_level(
            Experiment.objects.filter(team_id=self.team.pk)
        )
        contexts = get_session_experiment_contexts(
            team=self.team, session_ids=session_ids, experiments=experiments, user=cast(User, request.user)
        )
        serializer = ExperimentSessionContextsResponseSerializer(
            {"results": [{"session_id": session_id, "results": items} for session_id, items in contexts.items()]}
        )
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(response=ExperimentInSessionExposureSerializer)},
    )
    @action(methods=["GET"], detail=True, url_path="in_session_exposure", required_scopes=["experiment:read"])
    def in_session_exposure(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """How the recordings tab's in-session exposure scope reads on this experiment.

        Resolved through the same seam as the recordings query's `in_session` refusal, so the
        scope control disables exactly what a query would be refused for, and the copy can say
        when sessions are matched on the stamped flag property rather than on the exposure event.
        Postgres reads only, so it can serve the tab's mount path.
        """
        experiment: Experiment = self.get_object()
        semantics = resolve_in_session_exposure_semantics(team_id=self.team_id, experiment_id=experiment.id)
        if semantics is None:
            raise NotFound()
        return Response(ExperimentInSessionExposureSerializer(semantics).data)

    @validated_request(
        request_serializer=ExperimentSessionBucketRequestSerializer,
        responses={200: OpenApiResponse(response=ExperimentSessionBucketResponseSerializer)},
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path="session_buckets",
        required_scopes=["experiment:read", "session_recording:read"],
        # Heavier than the session-context batch (it scans the run window rather than a known id
        # list) and called by the session-authenticated web app, which the ClickHouse* pair
        # doesn't cover.
        throttle_classes=[SessionBucketsBurstRateThrottle, SessionBucketsSustainedRateThrottle],
    )
    def session_buckets(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Session recordings of this experiment matching a bucket.

        Answers the questions a recordings query can't express on its own — "fired any of these
        metrics", "fired none of them", "was exposed but never completed the funnel in this
        session" — by returning a bounded, most-recent-first list of session IDs to pass back as
        a recordings query's session_ids. POST because the metric list doesn't fit a query
        string; the endpoint only reads.

        Session-scoped and goal-free: the set describes what happened in each session, while the
        experiment analysis counts per person over the whole run window. A session can be in the
        drop-off bucket while the same person converts in a later one.
        """
        experiment: Experiment = self.get_object()

        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading experiment session buckets requires session replay access.")

        try:
            scan = get_experiment_session_bucket(
                team=self.team,
                # user threads through to the HogQL query: metric sources and exposure criteria
                # can filter on arbitrary properties, which must respect the viewer's
                # property-level access control.
                user=cast(User, request.user),
                experiment=experiment,
                bucket=ExperimentSessionBucket(request.validated_data["bucket"]),
                metric_uuids=request.validated_data["metric_uuids"],
                variant=request.validated_data["variant"],
                limit=request.validated_data["limit"],
            )
        except SessionBucketUnavailable as error:
            raise ValidationError(str(error))

        # Applied to the computed set rather than inside the scan: the bucket is cached per
        # viewer, so filtering on read honors a revocation that lands while an entry is warm. The
        # cut to `limit` follows it, so a denied recording never spends a returned slot and
        # `truncated` describes what this viewer may see.
        result = finalize_session_bucket(
            scan,
            _accessible_session_ids(request, self.user_access_control, self.team, scan.candidate_session_ids),
        )
        return Response(ExperimentSessionBucketResponseSerializer(result).data)

    @validated_request(
        request_serializer=ExperimentSessionEventDeltaRequestSerializer,
        responses={200: OpenApiResponse(response=ExperimentSessionEventDeltaResponseSerializer)},
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path="session_event_deltas",
        required_scopes=["experiment:read", "session_recording:read"],
        # The heaviest read in this family: it compares every event name in the window, so unlike
        # the bucket scan there is no event-name predicate for ClickHouse to prune on.
        throttle_classes=[SessionEventDeltasBurstRateThrottle, SessionEventDeltasSustainedRateThrottle],
    )
    def session_event_deltas(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """The recordings worth watching for this experiment, grouped into cards.

        Each card is one sentence and the recordings that back it: an event one variant did clearly
        more than the others, an error signal concentrated in one variant, or a shortcut to a
        metric event happening on screen. Every card's count is a count of recordings that actually
        exist, so handing its session ids to the recordings list can't come back empty. POST to
        take the same throttle and cache posture as the other reads in this family rather than
        because it carries a body: it takes no parameters, and it only reads.

        It reports no effect size. Cards carry a direction and a band rather than a rate, a ratio
        or a person count: the experiment's results already state magnitudes, computed per person
        over the whole run window, and this reads one session per person over a clamped one. Two
        numbers for the same event would read as a contradiction, so this surface states none. That
        is what lets a card sit on one of the experiment's own metric events, which it names, so a
        reader is sent to the results rather than given a second answer.
        """
        experiment: Experiment = self.get_object()

        if not self._session_event_deltas_enabled():
            raise NotFound()

        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Comparing an experiment's session behavior requires session replay access.")

        try:
            result = get_experiment_session_event_deltas(
                team=self.team,
                # user threads through to the HogQL queries: exposure criteria can filter on
                # arbitrary properties, which must respect the viewer's property-level access
                # control.
                user=cast(User, request.user),
                experiment=experiment,
            )
        except SessionEventDeltasUnavailable as error:
            raise ValidationError(str(error))

        # Applied to the computed shelf rather than inside the scan, as the session buckets do it:
        # the shelf is cached across viewers sharing a restriction profile, so filtering on read is
        # what keeps one viewer's entry from leaking another's denied recordings, and a revocation
        # lands even while an entry is warm. The resource-level check above grants the replay
        # product, not every recording in it — without this a viewer denied one recording could
        # still read its id, the variant it was in, and an event it contains.
        result = finalize_watch_cards(
            result,
            _accessible_session_ids(request, self.user_access_control, self.team, all_card_session_ids(result)),
        )
        return Response(ExperimentSessionEventDeltaResponseSerializer(result).data)

    def _session_event_deltas_enabled(self) -> bool:
        # Scoped to the experiment's organization rather than the caller's current one: a user in
        # several orgs could otherwise switch their current org to a flagged-in one and read an
        # experiment in an org that is not.
        try:
            return posthog_feature_flag_enabled(
                EXPERIMENT_BEHAVIOR_COMPARISON_FLAG,
                str(cast(User, self.request.user).distinct_id),
                organization_id=self.organization_id,
                team_id=self.team.id,
            )
        except Exception:
            logger.warning("Failed to evaluate the experiment behavior comparison flag", exc_info=True)
            return False
