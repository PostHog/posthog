"""Who a scanner's findings affected: counted from observations, exportable as a static cohort.

"Affected" needs a per-type predicate: monitors flag via verdict, classifiers via a tag,
scorers via a score bound. Callers must pass the qualifier the scanner type requires.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Case, CharField, Count, FloatField, Func, Q, QuerySet, Value, When
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast
from django.utils import timezone

from posthog.models.user import User

from products.cohorts.backend.models.cohort import Cohort
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType

DEFAULT_IMPACT_WINDOW_DAYS = 30
# Bounds the synchronous in-request insert (~1 personhog batch round-trip per 1000 ids).
MAX_COHORT_DISTINCT_IDS = 10_000
# Stable prefix so Vision can re-identify its own cohorts later (dedup, cleanup).
AFFECTED_COHORT_NAME_PREFIX = "Affected by "

# Presence of a distinct_id, which may still be an anonymous device id — not proof of an identified person.
_HAS_USER = ~Q(distinct_id__isnull=True) & ~Q(distinct_id="")


@dataclass(frozen=True)
class ScannerImpact:
    affected_sessions: int
    affected_users: int
    sessions_without_user: int
    window_days: int


def affected_observations(
    scanner: ReplayScanner,
    window_days: int,
    *,
    tag: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
) -> QuerySet[ReplayObservation]:
    """Succeeded observations matching the scanner type's impact predicate.

    Raises ValueError when the type's required qualifier is missing, an inapplicable one is
    passed, or the type has no impact semantics (summarizers).
    """
    since = timezone.now() - timedelta(days=window_days)
    base = ReplayObservation.objects.filter(
        scanner=scanner,
        team_id=scanner.team_id,
        status=ObservationStatus.SUCCEEDED,
        created_at__gte=since,
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
        # Same `@>` predicate the observations list filter uses, over fixed and freeform tags.
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
    aggregates = affected_observations(
        scanner, window_days, tag=tag, min_score=min_score, max_score=max_score
    ).aggregate(
        affected_sessions=Count("session_id", distinct=True),
        affected_users=Count("distinct_id", filter=_HAS_USER, distinct=True),
        sessions_without_user=Count("session_id", filter=~_HAS_USER, distinct=True),
    )
    return ScannerImpact(window_days=window_days, **aggregates)


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
    """Static cohort of the users the scanner flagged; returns the cohort and its real member count.

    Raises ValueError on a missing/invalid qualifier for the scanner type, an empty window,
    a window over the size cap, or when no flagged distinct id resolves to a person.
    """
    distinct_ids = list(
        affected_observations(scanner, window_days, tag=tag, min_score=min_score, max_score=max_score)
        .filter(_HAS_USER)
        .values_list("distinct_id", flat=True)
        .distinct()
    )
    if not distinct_ids:
        raise ValueError("No users in the window to save as a cohort.")
    if len(distinct_ids) > MAX_COHORT_DISTINCT_IDS:
        raise ValueError(
            f"Too many users to save as one cohort ({len(distinct_ids):,}; the limit is "
            f"{MAX_COHORT_DISTINCT_IDS:,}). Narrow the window."
        )

    qualifier = _qualifier_label(tag, min_score, max_score)
    cohort = Cohort.objects.create(
        team_id=scanner.team_id,
        name=f"{AFFECTED_COHORT_NAME_PREFIX}{scanner.name}{qualifier} ({timezone.now().date().isoformat()})"[:400],
        description=(
            f"Users flagged by the '{scanner.name}' scanner{qualifier} in the last {window_days} days. Static snapshot."
        ),
        is_static=True,
        created_by=user,
    )
    try:
        cohort.insert_users_by_list(distinct_ids, team_id=scanner.team_id, raise_on_error=True)
    except Exception:
        # Nothing references the cohort yet; don't leave a partial one behind.
        cohort.delete()
        raise
    cohort.refresh_from_db()
    # The real member count: person-less distinct ids are dropped and merged persons dedupe during insert.
    inserted = cohort.count or 0
    if inserted == 0:
        cohort.delete()
        raise ValueError("None of the flagged users have a person profile to add to a cohort.")
    return cohort, inserted
