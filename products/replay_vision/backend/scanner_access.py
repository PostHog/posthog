"""Scanner-level RBAC helper shared by the vision-action engine (run-time creator gate) and the
API serializer (write-time editor gate). Lives outside `temporal/` so the API can import it without
pulling the temporal package onto its import path.

Also home to the two queries that read observations back across scanner origins, so `all_origins`
appears once instead of at every reading call site."""

import uuid
from typing import TYPE_CHECKING, Any

from django.db.models import Q

from rest_framework.exceptions import NotFound, PermissionDenied

from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.models.experiment import Experiment
from products.replay_vision.backend.models.replay_scanner import ReplayScanner

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from posthog.models.user import User

    from products.replay_vision.backend.models.replay_observation import ReplayObservation


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError):
        return False
    return True


def scanners_for_reading_observations(team_id: int) -> "QuerySet[ReplayScanner]":
    """Every scanner whose observations can be read, inline scans included.

    The one place `all_origins` belongs on a read path. `ReplayScanner.objects` is configured-only so
    that a new call site can't leak inline scans into a list or a sweep, which leaves exactly one way to
    get this wrong: a path that reads results and forgets to opt back in, silently hiding an inline
    scan's answers. Go through this instead of naming the manager, and still apply the caller's own
    access-level filter on top — this widens origin, not RBAC.
    """
    return ReplayScanner.all_origins.filter(team_id=team_id)


def is_experiment_accessible(access: UserAccessControl | None, team_id: int, experiment_id: int) -> bool:
    """Whether the caller may view this experiment, filtered by object-level access (not just team).

    The single source of truth for "is a scanner-viewer allowed to know this experiment exists".
    A denied or cross-team id reads as inaccessible, so callers can treat it as not-found rather
    than disclosing the experiment through a scanner surface. `access` is None only outside request
    context (internal serialization), where there is no viewer to gate on, so it passes.
    """
    team_experiments = Experiment.objects.filter(team_id=team_id)
    accessible = access.filter_queryset_by_access_level(team_experiments) if access is not None else team_experiments
    return accessible.filter(id=experiment_id).exists()


def _accessible_experiment_ids(access: UserAccessControl, team_id: int, experiment_ids: set[int]) -> set[int]:
    """The subset of `experiment_ids` the caller may view, in one query. Empty input, empty result."""
    if not experiment_ids:
        return set()
    accessible = access.filter_queryset_by_access_level(
        Experiment.objects.filter(team_id=team_id, id__in=experiment_ids)
    )
    return set(accessible.values_list("id", flat=True))


def accessible_observations(
    access: UserAccessControl, team_id: int, observations: "QuerySet[ReplayObservation]"
) -> "QuerySet[ReplayObservation]":
    """Drop observations whose recorded experiment the caller can't view.

    An observation's population is fixed at creation, so it authorizes against the experiment in its
    own `scanner_snapshot`, not the scanner's *current* targeting — retargeting or clearing a scanner
    must not expose the historical rows it produced under a restricted experiment. A snapshot with no
    experiment targeting (every observation predating this feature) is unrestricted here and stays
    subject to the scanner and session-recording gates the caller already passed.

    One experiment query for the whole page, not one per row.
    """
    snapshot_experiment_ids = {
        eid
        for eid in observations.values_list(
            "scanner_snapshot__experiment_targeting__experiment_id", flat=True
        ).distinct()
        if eid is not None
    }
    accessible = _accessible_experiment_ids(access, team_id, snapshot_experiment_ids)
    if accessible == snapshot_experiment_ids:
        return observations
    # Keep rows whose snapshot names no experiment (untargeted, unrestricted) OR an accessible one.
    # Phrased positively rather than `.exclude(path__in=inaccessible)`: on a nullable JSON path, exclude
    # negates to `NOT (path IN (...))`, which is NULL — and therefore false — for untargeted rows, so it
    # would wrongly drop them. `isnull` OR membership is null-safe. The lookup keys are written as
    # literals (not composed from a variable) so the ORM-field-injection lint sees they're not caller input.
    return observations.filter(
        Q(scanner_snapshot__experiment_targeting__experiment_id__isnull=True)
        | Q(scanner_snapshot__experiment_targeting__experiment_id__in=accessible)
    )


def readable_observation_scanner_ids(access: UserAccessControl, team_id: int) -> list[uuid.UUID]:
    """Scanner ids whose observations the caller may read across scanners, experiment access included.

    For the surfaces that scope by scanner (the session dock, Max search) rather than filter rows. A
    scanner is included when the caller can read the scanner (recording RBAC) and can view its current
    targeted experiment, if any. Batches the experiment lookup into one query instead of one per
    scanner. Row-level history is still gated by `accessible_observations` on the rows themselves; this
    only narrows which scanners are in scope.
    """
    scanners = list(
        access.filter_queryset_by_access_level(scanners_for_reading_observations(team_id)).only(
            "id", "experiment_targeting"
        )
    )
    targeted = {eid for s in scanners if (eid := (s.experiment_targeting or {}).get("experiment_id")) is not None}
    accessible = _accessible_experiment_ids(access, team_id, targeted)
    return [
        s.id
        for s in scanners
        if (eid := (s.experiment_targeting or {}).get("experiment_id")) is None or eid in accessible
    ]


def can_read_targeted_experiment(access: UserAccessControl, team_id: int, scanner: ReplayScanner) -> bool:
    """Whether the caller may read a scanner given its *current* targeted experiment.

    Gates the per-scanner observation endpoint at the scanner level, so a denied experiment scanner
    reads as not-found. Row-level history within an accessible scanner is gated separately by
    `accessible_observations`, which follows each row's snapshot. A scanner with no targeting passes.
    """
    targeting = scanner.experiment_targeting
    if not targeting or targeting.get("experiment_id") is None:
        return True
    return is_experiment_accessible(access, team_id, targeting["experiment_id"])


def scanner_for_reading_observations(team_id: int, scanner_id: "str | uuid.UUID") -> ReplayScanner | None:
    """Resolve one scanner by id for reading its observations. See `scanners_for_reading_observations`."""
    if not is_uuid(str(scanner_id)):
        return None
    return scanners_for_reading_observations(team_id).filter(id=scanner_id).first()


def readable_scanner_ids(user: "User", team: Team, scanner_ids: list[str]) -> list[str]:
    """Restrict an action's bound scanner ids to the ones the given user may actually read.

    A vision action's scanner binding is user-supplied, so without this a user could point an action
    at a same-team scanner they lack `replay_scanner` viewer access to and receive its recording-derived
    reasoning and outcome in the synthesized report. The engine applies it to the action's creator on
    every run; the serializer applies it to the requesting user whenever the targeting changes. Mirrors
    the scanner-access gate `max_tools` applies on interactive reads (object-level access control; note
    the underlying queryset filter is a no-op for orgs without the access-control feature, where no
    per-scanner restriction exists anyway).
    """
    # Drop non-UUID ids before querying: `selection.scanner_ids` is a user-supplied CharField list, and a
    # malformed value would raise ValidationError inside the Temporal activity on every run (a permanent
    # retry loop). Mirrors the UUID pre-validation in `max_tools._resolve_scanner_scope`.
    valid_ids = [scanner_id for scanner_id in scanner_ids if is_uuid(scanner_id)]
    if not valid_ids:
        return []
    readable = UserAccessControl(user=user, team=team).filter_queryset_by_access_level(
        ReplayScanner.objects.filter(team_id=team.id, id__in=valid_ids)
    )
    return [str(scanner_id) for scanner_id in readable.values_list("id", flat=True)]


def selection_target_ids(scanner_id: uuid.UUID, selection: dict[str, Any] | None) -> set[str]:
    """Scanner ids an action's selection pulls observations from, beyond its bound `scanner`.

    Shared so the API and the Max tools authorize an action against the same set. A summary fans in
    observations from every scanner named here, so access to the bound one is not access to the report.
    """
    configured = (selection or {}).get("scanner_ids") or []
    return {str(s) for s in configured if is_uuid(s)} - {str(scanner_id)}


def scanner_for_recording_derived_read(
    viewset: Any, scanner_id_kwarg: str = "parent_lookup_scanner_id"
) -> ReplayScanner:
    """The scanner named in a nested route's URL, once the caller may read what it produced.

    Observations and the scout reports written from them are both recording-derived, so both inherit
    the scanner's own RBAC *and* require session_recording read. Shared so that bar has one
    definition: a viewset that gates on only half of it leaks recording content.
    """
    try:
        scanner_id = uuid.UUID(viewset.kwargs[scanner_id_kwarg])
    except (KeyError, ValueError):
        raise NotFound()
    scanner = scanner_for_reading_observations(viewset.team_id, scanner_id)
    if scanner is None:
        raise NotFound()
    viewset.check_object_permissions(viewset.request, scanner)
    if not viewset.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
        raise PermissionDenied("Reading replay observations requires session_recording read access.")
    # An experiment scanner's output is that experiment's exposed sessions, so reading it needs
    # experiment access too. Not-found, not 403: a denied experiment scanner reads as if it doesn't
    # exist, matching the serializer's targeting redaction.
    if not can_read_targeted_experiment(viewset.user_access_control, viewset.team_id, scanner):
        raise NotFound()
    return scanner
