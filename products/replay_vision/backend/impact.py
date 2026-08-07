"""Who a scanner's findings affected: counted from observations, exportable as a static cohort."""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Case, CharField, Count, FloatField, Func, Q, QuerySet, Value, When
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from posthog.models.person.util import get_person_uuids_by_distinct_ids
from posthog.models.user import User

from products.cohorts.backend.models.cohort import Cohort
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType

DEFAULT_IMPACT_WINDOW_DAYS = 30
# Bounds the synchronous in-request insert.
MAX_COHORT_DISTINCT_IDS = 10_000
# Stable prefix so Vision can re-identify its own cohorts.
COHORT_NAME_PREFIX = "Matched by "

# A distinct_id may still be an anonymous device id, not an identified person.
_HAS_USER = ~Q(distinct_id__isnull=True) & ~Q(distinct_id="")


@dataclass(frozen=True)
class ScannerImpact:
    affected_sessions: int
    affected_users: int
    sessions_without_user: int
    window_days: int


def cohort_team_id(scanner: ReplayScanner) -> int:
    """Team a cohort for this scanner lands on. ``Cohort`` inherits ``RootTeamMixin``, so on save its
    team is rewritten to the project's root team. Persons must be resolved and counted against that
    same team; resolving against the scanner's (possibly child) environment would count a different
    person set than the cohort insert writes to, and the count would read back as zero."""
    return scanner.team.parent_team_id or scanner.team_id


def person_backed_user_count(team_id: int, distinct_ids: list[str]) -> int:
    """Distinct persons behind these distinct IDs — the count that can actually enter a cohort.
    Anonymous device IDs from recordings captured without a person profile resolve to nothing and
    drop out, so this is lower than the raw distinct-id count whenever recordings went unidentified."""
    if not distinct_ids:
        return 0
    return len(set(get_person_uuids_by_distinct_ids(team_id, distinct_ids)))


def affected_observations(
    scanner: ReplayScanner,
    window_days: int,
    *,
    tag: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
) -> QuerySet[ReplayObservation]:
    """Succeeded observations matching the type's impact predicate; raises ValueError on invalid qualifiers."""
    since = timezone.now() - timedelta(days=window_days)
    base = ReplayObservation.objects.annotate(
        # Session time, not scan time: backfills must not count as current impact.
        _affected_at=Coalesce("session_started_at", "created_at"),
    ).filter(
        scanner=scanner,
        team_id=scanner.team_id,
        status=ObservationStatus.SUCCEEDED,
        _affected_at__gte=since,
    )
    scanner_type = scanner.scanner_type
    has_scores = min_score is not None or max_score is not None

    if scanner_type == ScannerType.MONITOR:
        if tag or has_scores:
            raise ValueError("Monitor impact is verdict-based; tag and score filters don't apply.")
        return base.filter(scanner_result__model_output__verdict="yes")

    if scanner_type == ScannerType.CLASSIFIER:
        if has_scores:
            raise ValueError("Classifiers don't produce scores; use `tag` instead.")
        if not tag:
            raise ValueError("Classifier impact requires `tag`: the tag whose affected users you want.")
        # Same predicate as the observations list filter.
        return base.filter(
            Q(scanner_result__model_output__tags__contains=[tag])
            | Q(scanner_result__model_output__tags_freeform__contains=[tag])
        )

    if scanner_type == ScannerType.SCORER:
        if tag:
            raise ValueError("Scorers don't produce tags; use `min_score`/`max_score` instead.")
        if not has_scores:
            raise ValueError("Scorer impact requires `min_score` and/or `max_score`.")
        score_jsonb = KeyTransform("score", KeyTransform("model_output", "scanner_result"))
        score_text = KeyTextTransform("score", KeyTextTransform("model_output", "scanner_result"))
        # CASE-guard the cast so a non-numeric score (schema drift) doesn't 500 the query.
        qs = base.annotate(
            _score_type=Func(score_jsonb, function="jsonb_typeof", output_field=CharField()),
            _score=Case(
                When(_score_type="number", then=Cast(score_text, FloatField())),
                default=Value(None),
                output_field=FloatField(),
            ),
        )
        if min_score is not None:
            qs = qs.filter(_score__gte=min_score)
        if max_score is not None:
            qs = qs.filter(_score__lte=max_score)
        return qs

    raise ValueError(f"Impact is not available for {scanner_type} scanners.")


def compute_scanner_impact(
    scanner: ReplayScanner,
    window_days: int = DEFAULT_IMPACT_WINDOW_DAYS,
    *,
    tag: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
) -> ScannerImpact:
    observations = affected_observations(scanner, window_days, tag=tag, min_score=min_score, max_score=max_score)
    aggregates = observations.aggregate(
        affected_sessions=Count("session_id", distinct=True),
        sessions_without_user=Count("session_id", filter=~_HAS_USER, distinct=True),
    )
    # Resolve persons so the user count matches what the cohort insert can actually save, rather than
    # trusting the raw distinct_id (which may be an anonymous device id with no person profile). Bounded
    # to the same cap the cohort insert enforces so a huge scanner can't pull an unbounded id list.
    distinct_ids = [
        distinct_id
        for distinct_id in observations.filter(_HAS_USER)
        .order_by()
        .values_list("distinct_id", flat=True)
        .distinct()[:MAX_COHORT_DISTINCT_IDS]
        if distinct_id
    ]
    return ScannerImpact(
        window_days=window_days,
        affected_sessions=aggregates["affected_sessions"],
        sessions_without_user=aggregates["sessions_without_user"],
        affected_users=person_backed_user_count(cohort_team_id(scanner), distinct_ids),
    )


def _qualifier_label(tag: str | None, min_score: float | None, max_score: float | None) -> str:
    if tag:
        return f", tag {tag}"
    if min_score is not None and max_score is not None:
        return f", score {min_score:g} to {max_score:g}"
    if min_score is not None:
        return f", score {min_score:g}+"
    if max_score is not None:
        return f", score up to {max_score:g}"
    return ""


def create_affected_cohort(
    scanner: ReplayScanner,
    user: User | None,
    window_days: int = DEFAULT_IMPACT_WINDOW_DAYS,
    *,
    tag: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
) -> tuple[Cohort, int]:
    """Static cohort of matched users; returns (cohort, real member count). Raises ValueError when not creatable."""
    distinct_ids = list(
        affected_observations(scanner, window_days, tag=tag, min_score=min_score, max_score=max_score)
        .filter(_HAS_USER)
        .values_list("distinct_id", flat=True)
        .distinct()[: MAX_COHORT_DISTINCT_IDS + 1]
    )
    if not distinct_ids:
        raise ValueError("No users in the window to save as a cohort.")
    if len(distinct_ids) > MAX_COHORT_DISTINCT_IDS:
        raise ValueError(f"Too many users to save as one cohort (over {MAX_COHORT_DISTINCT_IDS:,}). Narrow the window.")

    qualifier = _qualifier_label(tag, min_score, max_score)
    cohort = Cohort.objects.create(
        team_id=scanner.team_id,
        name=f"{COHORT_NAME_PREFIX}{scanner.name}{qualifier} ({timezone.now().date().isoformat()})"[:400],
        description=(
            f"Users matched by the '{scanner.name}' scanner{qualifier} in the last {window_days} days. Static snapshot."
        ),
        is_static=True,
        created_by=user,
    )
    # `Cohort.objects.create` may have rewritten the team to the project's root (RootTeamMixin), so
    # insert and count members against the cohort's own team. Passing the scanner's team here would
    # write members under one team while the post-insert count reads another, reporting zero members.
    try:
        cohort.insert_users_by_list(distinct_ids, team_id=cohort.team_id, raise_on_error=True)
    except Exception:
        # Don't leave a partial cohort behind.
        cohort.delete()
        raise
    cohort.refresh_from_db()
    # Person-less ids are dropped and merged persons dedupe during insert.
    inserted = cohort.count or 0
    if inserted == 0:
        cohort.delete()
        raise ValueError(
            "None of the matched sessions are linked to a person profile, so there's no one to add to a cohort. "
            "This happens when recordings are captured before users are identified. Identify users during "
            "capture, then run the scanner again."
        )
    return cohort, inserted
