"""Pick the recordings worth watching in one experiment's exposed sessions.

The recordings tab can list an arm's sessions but says nothing about which of the thousands carry
signal, so picking what to watch is sampling rather than targeting. This module answers that with
watch cards: bounded groups of recordings, each one a sentence a reader can act on — "this arm did
this event clearly more than the others, here are recordings of it happening".

**Recordings are the deliverable.** A card's count is a count of watchable recordings, checked
against replay existence before the card is returned; a finding that no recording can back is
dropped, because a promise the playlist can't keep reads as the feature being broken. The event
comparison underneath is the picking mechanism, not the product.

**It reports no effect size, on purpose, and this is the constraint the file serves.** The results
tab publishes one already, from a real statistics engine: per person, over the whole run window,
with sample-ratio checks and credible intervals behind it. This reads one session per person over a
window clamped to hours or days. Measured on a production experiment the two agreed on direction
for every shared event and on no number at all — 7.5x there against 41x here for the same event —
because the later sessions where people convert are outside what this reads. So the two rules that
follow are not stylistic:

  1. The experiment's own metric events never enter the comparison. Those are the events it was
     built to move, so they would top the ranking on nearly every experiment, and each row would
     sit one tab away from a differently-computed answer to the same question. They come back only
     as shortcuts — "recordings where this metric's event happened, per arm" — which claim nothing.
  2. Cards carry a direction and a band, never a rate, a ratio or a person count. Whatever we
     called it, a precise number next to an event name is an effect size, and would be read
     against the one the results tab computes.

**Population.** The same session-scoped exposure evidence the tab's list and the session buckets
use: a session containing an event that matches the experiment's exposure criteria and carries one
of the flag's defined variants. That is not the analysis's population — a person whose SDK deduped
later exposure events contributes only the session they were bucketed in. The comparison survives
that because it is a *ratio* between arms selected by the same mechanism, which is exactly what an
absolute per-session claim (the buckets) could not do.

**One person, one session.** The sessions an arm is exposed in are not a fair denominator: a
variant that stops re-evaluating the flag once a user has acted contributes fewer later sessions,
and those missing sessions are the quiet ones. Measured on a production experiment this reached
3.7x more exposed sessions in one arm off near-identical people, which pushed nine in ten event
names to one side of the comparison: arithmetic reading as behavior. Counting each exposed person
once fixes the denominator, and it makes the rows independent, which is what the ranking's noise
test below assumes. It is not enough on its own, because the same imbalance is still in the
numerator: on that experiment one arm's people averaged seven covered sessions each against the
other's two, so they had seven chances to have done anything rather than two, and nine in ten event
names still leaned one way. So a person is read from one session, the first the comparison covers
them in, which is the same amount of behavior on both sides. A card's *recordings*, by contrast,
come from any of the arm's covered sessions containing the event — the statistics need fairness,
the watchlist needs the behavior on screen.

**Ranking.** Each arm is compared against all the others pooled, so a five-arm experiment needs no
pairing and costs the same one scan as two arms. Rates are compared on the log of their ratio, and
an event earns a card only once the *conservative* end of that ratio is still a real difference.
Without that test the list ranks rarity: on a production A/A pair — two arms of one experiment
rendering identically — the raw ratio produced a full page of confident findings, every one of them
noise, while the same data under this test produced nothing. The same conservative end picks the
band a card is reported in, so a difference that only cleared the floor because the sample is large
reports as slight, whatever its point estimate.

**Cost.** The scan cannot prune by event name — the whole point is that it does not know which
events matter yet. So the window is the only thing bounding it, which is why a first query resolves
what the session ceiling actually covers and the scan is then clamped to that: on a busy project
the ceiling is reached within hours of a nominally two-week window, and scanning the rest reads the
project's whole recent history to find nothing. The follow-up queries that back cards with
recordings filter by event name and by session id, so they prune on the events table's primary key
and stay cheap. It is still the heaviest read on the tab, which is why the caller is expected to
load it on demand.
"""

import json
import math
import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Optional

from django.utils import timezone

from posthog.schema import EventsNode, MultipleVariantHandling

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.utils import get_safe_cache, safe_cache_set

from products.access_control.backend.property_access_control import get_restricted_properties_for_team
from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    get_multiple_variant_handling_from_experiment,
    get_test_accounts_filter,
    normalize_to_exposure_criteria,
)
from products.experiments.backend.metric_events import (
    MetricEventSource,
    SharedHogQLDatabase,
    build_source_condition,
    resolve_metric_events,
)
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.session_exposure import SessionExposure, resolve_session_exposure

# Tighter than MAX_BUCKET_SCAN_DAYS. The bucket scan filters by event name in its WHERE, so
# ClickHouse prunes on the events table's primary key; this one compares every event name there is
# and has no such predicate, so the window is all that stands between it and the team's whole
# recent history.
MAX_DELTA_SCAN_DAYS = 14
# Tighter again under the exposure fallback. The stamped flag property rides on every client
# event, so not even the coverage query can prune by event name there, and the full window is
# read three times per response before the session ceiling can clamp anything. Two days keeps
# each of those reads inside the query timeout on the largest projects; `date_from` already
# reports the window actually covered.
MAX_FALLBACK_DELTA_SCAN_DAYS = 2
# Ceiling on the exposed sessions one comparison covers, most recent first. Bounds the aggregation
# state rather than the rows read, and because the cut is on recency across both arms at once, the
# arms stay covered over the same period — a comparison split across different stretches of time
# would be measuring the calendar as much as the variant.
MAX_DELTA_SCAN_SESSIONS = 20_000
# How far back of a session's own events the scan has to reach once the window is clamped to what
# the ceiling covers. The ceiling is resolved from each session's *last* activity, so a session that
# began before that floor would otherwise be read from the middle, and the events it opened with
# would go missing from a comparison that claims to have seen the session.
MAX_SESSION_DURATION_HOURS = 24
# Ceiling on (event name x arm) rows one comparison ranks. Distinct event names per project are
# normally in the hundreds; a project that keys event names by id is what this is for.
MAX_DELTA_EVENT_ROWS = 10_000
# How many behavior cards one response carries. The shelf is scanned, not scrolled, and a long tail
# of near-identical differences is noise rather than depth.
MAX_BEHAVIOR_CARDS = 8
# How many of the experiment's metric events get shortcut cards, in the order its metrics are
# defined, so the primary metric's event comes first. Per event there is one card per arm, so this
# stays small to keep a five-arm experiment's shelf readable.
MAX_METRIC_CARD_EVENTS = 2
# Recording candidates fetched per card before replay existence is checked, and how many survive
# onto the card. The margin absorbs sessions that were never recorded without a second round trip.
MAX_CARD_RECORDING_CANDIDATES = 60
MAX_CARD_RECORDINGS = 20
# An event has to have been done by this many people in the arm it is more common in before it can
# earn a card. The separation test below already drops rare events on its own; this only keeps the
# candidate set from being mostly rows that can never pass it.
MIN_SUPPORT_PERSONS = 10
# Below this many exposed people an arm is noise to compare, whatever the floor above allows. With
# fewer than two arms past it there is nothing to compare at all, which is reported as "too early"
# rather than as an empty shelf that would read as "the variants behaved identically".
MIN_ARM_PERSONS = 50
# Laplace-style smoothing on both shares before they are divided. Keeps "none in one arm" finite and
# pulls small counts toward no difference, so the ranking is not led by rare events.
RATIO_SMOOTHING = 0.5
# How many standard errors of separation a difference needs before it earns a card at all. This is a
# ranking floor, not a significance claim, and it is deliberately past the conventional 1.96: one
# comparison tests every event name in the project at once, so the loose threshold that reads as
# "95% sure" for a single question is wrong by hundreds of tries here. On a production A/A pair the
# 1.96 version still let a difference through, barely above the floor; at this width the same data
# fell short of the floor and produced no cards at all.
CONFIDENCE_Z = 2.58
# ...and how big the conservative end of the ratio still has to be, in log space: about 1.35x. A
# difference the reader cannot see while watching a recording is not worth a card telling them to.
MIN_LOG_RATIO_LOWER_BOUND = 0.3
# Where that conservative end earns a stronger word, in log space: about 3x and about 1.5x. Bands
# rather than the number itself, for the reason in the module docstring — the number is the part
# that reads as an effect size and collides with the one the results tab computes.
FAR_MORE_LOG_RATIO = 1.1
MORE_LOG_RATIO = 0.4
# Per (team, experiment, window bucket, viewer restriction profile). The window moves with
# wall-clock time on a running experiment, so the key it is built from is quantized to this same
# interval — at any finer resolution the key would change faster than the entry expires and the
# TTL would never apply, leaving the heaviest read on the tab uncached in practice.
DELTA_CACHE_TTL = 15 * 60
# Kept beside the scan rather than with the viewset's other constants so the flag and what it gates
# can't drift.
EXPERIMENT_BEHAVIOR_COMPARISON_FLAG = "experiment-behavior-comparison"

# Events whose *name* carries no behavior, so a difference in how often people do them says nothing
# about what they did. Page views and autocaptures are the interesting ones to leave out: they are
# in almost every session in both arms, so they rank last anyway, but their names describe a
# mechanism rather than an action. What replaces them is a page-level comparison, which needs the
# project's path-cleaning rules and a second grouping key, so it is not this scan.
UNCOMPARABLE_EVENTS = frozenset(
    {
        "$pageview",
        "$pageleave",
        "$autocapture",
        "$web_vitals",
        "$feature_flag_called",
        "$experiment_exposure",
        "$feature_enrollment_update",
        "$identify",
        "$groupidentify",
        "$create_alias",
        "$merge_dangerously",
        "$set",
        "$snapshot",
        "$$heatmap",
        "survey shown",
    }
)

# Events whose card belongs on the friction shelf rather than the behavior one. Same pipeline and
# the same evidence bar — the split is presentation: a reader triages "the new variant breaks
# something" differently from "the new variant changes what people do".
FRICTION_EVENTS = frozenset({"$exception", "$rageclick", "$dead_click"})

# Distinct from session_buckets' CUSTOM_EXPOSURE_UNLINKABLE_REASON in both name and wording: the
# bucket can't *match* such an event, this can't *compare* on it, and a reader hitting one of the two
# endpoints should get the sentence that describes what they asked for.
CUSTOM_EXPOSURE_UNCOMPARABLE_REASON = (
    "This experiment's exposure event has only ever been captured server-side, where there is no session to "
    "record, so no session can be compared."
)


class SessionEventDeltasUnavailable(Exception):
    """The cards can't be computed for this experiment — a caller error, not a failure.
    Raised instead of returning an empty shelf, so "we declined to compare" never reads as
    "the arms behaved identically"."""


class DeltaStrength(StrEnum):
    """How far apart an arm and the rest are, conservatively, in bands rather than as a number."""

    # Nobody in the other arms did it, among the people compared. A fact about the compared set
    # rather than a ratio, and the one band that is exact.
    ONLY = "only"
    FAR_MORE = "far_more"
    MORE = "more"
    SLIGHTLY_MORE = "slightly_more"


class WatchCardKind(StrEnum):
    # An event this arm did clearly more than the other arms together.
    BEHAVIOR = "behavior"
    # Same evidence, but the event is an error/rage signal, so it reads as a defect lead.
    FRICTION = "friction"
    # A shortcut to recordings around one of the experiment's own metric events. No comparison
    # claim: what happened to the metric is the results tab's answer.
    METRIC = "metric"


@dataclass(frozen=True)
class ExperimentWatchCard:
    """One group of recordings worth opening, and the one sentence that justifies it.

    Deliberately no rate, no ratio and no person count: a precise number next to an event name is
    an effect size, and the results tab publishes those for everything the experiment measures,
    computed over a different window and a different unit. The only number here is how many
    recordings the card can actually show.
    """

    kind: WatchCardKind
    event: str
    # The arm whose recordings these are — for comparison cards, the arm that did the event more.
    variant: str
    # None on metric cards: they are shortcuts, not comparisons.
    strength: Optional[DeltaStrength]
    # The metric whose event this card shortcuts to; None outside metric cards.
    metric_name: Optional[str]
    recording_count: int
    session_ids: list[str]


@dataclass(frozen=True)
class ExperimentWatchArm:
    """One arm's compared population: exposed people, and the sessions they were seen in."""

    key: str
    persons: int
    sessions: int


@dataclass(frozen=True)
class ExperimentWatchResult:
    cards: list[ExperimentWatchCard]
    arms: list[ExperimentWatchArm]
    multiple_variant_persons: int
    multiple_variant_handling: str
    metric_events: list[str]
    date_from: datetime
    date_to: datetime
    filter_test_accounts: bool
    used_exposure_fallback: bool
    sessions_truncated: bool
    events_truncated: bool
    min_arm_persons: int
    too_early: bool


def all_card_session_ids(result: ExperimentWatchResult) -> list[str]:
    """Every recording the shelf would hand out, deduped — what the caller runs its per-recording
    access filter over."""
    return sorted({session_id for card in result.cards for session_id in card.session_ids})


def finalize_watch_cards(result: ExperimentWatchResult, accessible_session_ids: list[str]) -> ExperimentWatchResult:
    """Cut every card down to the recordings this viewer may open, dropping the ones left with none.

    Applied on read rather than inside the scan, for the same reason the session buckets do it: the
    shelf is cached — and shared across viewers with the same property restrictions — so this cut
    is what keeps one viewer's entry from leaking another's denied recordings, and it honors a
    revocation that lands while an entry is still warm. A card that loses every recording is
    dropped rather than shown greyed-out — the same rule the scan applies to sessions replay never
    recorded, since either way there is nothing to watch behind it. `recording_count` is recomputed
    so it keeps meaning "recordings this card can show you".
    """
    accessible = set(accessible_session_ids)
    cards = []
    for card in result.cards:
        session_ids = [session_id for session_id in card.session_ids if session_id in accessible]
        if session_ids:
            cards.append(replace(card, recording_count=len(session_ids), session_ids=session_ids))
    return replace(result, cards=cards)


def get_experiment_session_event_deltas(team: Team, user: User, experiment: Experiment) -> ExperimentWatchResult:
    """The recordings worth watching for this experiment, grouped into cards.

    The caller passes the result through `finalize_watch_cards` with the recordings this viewer may
    open, which is what the cached shelf is cut down to before it is returned.

    `user` is the viewer: exposure criteria can filter on arbitrary event properties, so the
    queries run under that user's property-level access control, as the experiment query runners
    do.

    Raises SessionEventDeltasUnavailable when nothing can be compared at all — an experiment that
    never launched, fewer than two variants, or an exposure event that can never match a session.
    """
    # Exposure criteria over the events table is experiments' own logic and cost, so it bills to
    # experiments rather than to the tab it renders on.
    tag_queries(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.pk)

    if experiment.start_date is None:
        raise SessionEventDeltasUnavailable("This experiment hasn't launched, so it has no exposed sessions yet.")

    variant_keys = [variant["key"] for variant in experiment.feature_flag.variants or []]
    if len(variant_keys) < 2:
        raise SessionEventDeltasUnavailable("This experiment's feature flag defines fewer than two variants.")

    window_end = experiment.end_date or timezone.now()
    window_start = max(experiment.start_date, window_end - timedelta(days=MAX_DELTA_SCAN_DAYS))
    criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
    filter_test_accounts = bool(criteria.filterTestAccounts) if criteria else False

    # Resolved once for the whole response, because each call reads the experiment's saved-metric
    # join again.
    metrics = resolve_metric_events(experiment)
    metric_event_names = _metric_event_names(metrics)
    # The same rollout resolution the analysis queries and the session buckets apply, so the
    # compared population is the one the experiment's own results count.
    exposure = resolve_session_exposure(team, experiment, event_names=frozenset(metric_event_names))
    if exposure.is_unmatchable:
        raise SessionEventDeltasUnavailable(CUSTOM_EXPOSURE_UNCOMPARABLE_REASON)
    if exposure.used_fallback:
        window_start = max(window_start, window_end - timedelta(days=MAX_FALLBACK_DELTA_SCAN_DAYS))

    # The experiment's own metric events never enter the comparison — the module docstring's first
    # rule. They reappear below as shortcut cards, which claim nothing the results tab also claims.
    excluded_events = sorted(
        UNCOMPARABLE_EVENTS
        | metric_event_names
        | ({exposure.exposure_event} if exposure.exposure_event is not None else set())
    )
    multiple_variant_handling = get_multiple_variant_handling_from_experiment(experiment.exposure_criteria)

    cache_key = _cache_key(team, user, experiment, window_start, window_end, exposure.default_exposure_event)
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    modifiers = create_default_modifiers_for_team(team)
    setup = _QuerySetup(
        team=team,
        user=user,
        experiment=experiment,
        variant_keys=variant_keys,
        exposure=exposure,
        window_end=window_end,
        shared_hogql=SharedHogQLDatabase(
            # Postgres foreign-key lazy joins are the most expensive part of building the virtual
            # database and these queries only read events and replay summaries.
            database=Database.create_for(team=team, user=user, modifiers=modifiers, build_postgres_foreign_keys=False),
            modifiers=modifiers,
        ),
    )

    scan = _query_event_deltas(
        setup,
        multiple_variant_handling=multiple_variant_handling,
        excluded_events=excluded_events,
        window_start=window_start,
    )

    arms = [
        ExperimentWatchArm(key=key, persons=scan.persons.get(("", key), 0), sessions=scan.sessions.get(key, 0))
        for key in variant_keys
    ]
    qualified_arms = [arm.key for arm in arms if arm.persons >= MIN_ARM_PERSONS]
    too_early = len(qualified_arms) < 2

    candidates: list[ExperimentWatchCard] = []
    metric_nodes: dict[str, list[EventsNode]] = {}
    if not too_early:
        candidates = _pick_behavior_cards(scan, arm_keys=qualified_arms)
        metric_cards, metric_nodes = _metric_card_candidates(
            metrics, arm_keys=qualified_arms, never_linked=exposure.never_linked
        )
        candidates += metric_cards

    cards: list[ExperimentWatchCard] = []
    if candidates:
        recordings = _recordings_for_cards(
            setup,
            wanted=[(candidate.event, candidate.variant) for candidate in candidates],
            covered_from=scan.covered_from,
            metric_nodes=metric_nodes,
        )
        for candidate in candidates:
            session_ids = recordings.get((candidate.event, candidate.variant), [])
            # A card that can't show a single recording is dropped, not rendered greyed-out: the
            # deliverable is what can be watched, and replay sampling or retention already ate
            # these sessions.
            if session_ids:
                cards.append(replace(candidate, recording_count=len(session_ids), session_ids=session_ids))

    result = ExperimentWatchResult(
        cards=cards,
        arms=arms,
        multiple_variant_persons=scan.persons.get(("", MULTIPLE_VARIANT_KEY), 0),
        multiple_variant_handling=multiple_variant_handling.value,
        # Reported without the ones already left out for describing a mechanism: a reader pointed
        # at the results tab for `$pageview` would go looking for a row that was never coming
        # either way.
        metric_events=sorted(metric_event_names - UNCOMPARABLE_EVENTS),
        date_from=scan.covered_from,
        date_to=window_end,
        filter_test_accounts=filter_test_accounts,
        used_exposure_fallback=exposure.used_fallback,
        sessions_truncated=scan.sessions_truncated,
        events_truncated=scan.events_truncated,
        min_arm_persons=MIN_ARM_PERSONS,
        too_early=too_early,
    )
    safe_cache_set(cache_key, result, timeout=DELTA_CACHE_TTL)
    return result


@dataclass(frozen=True)
class SessionEventDeltaScan:
    """What the scan returned: per (event name, variant) the number of that arm's exposed people
    who did it in their first covered session, plus each arm's own totals under the empty event
    name."""

    persons: dict[tuple[str, str], int]
    sessions: dict[str, int]
    events_truncated: bool
    sessions_truncated: bool
    # The start of what was actually compared, which is later than the requested window whenever the
    # session ceiling bit. Carried here rather than recomputed by the caller: it is a property of
    # the scan, and reporting the requested window instead would claim coverage that never happened.
    covered_from: datetime


@dataclass(frozen=True)
class _QuerySetup:
    """Everything the scan and the recordings query share: the experiment's exposure semantics and
    one HogQL database. The ast builders are methods so every use site gets a fresh tree — the
    HogQL resolver annotates nodes in place, so one instance can't appear in two clauses."""

    team: Team
    user: User
    experiment: Experiment
    variant_keys: list[str]
    exposure: SessionExposure
    window_end: datetime
    shared_hogql: SharedHogQLDatabase

    def exposure_condition(self) -> ast.Expr:
        # Every defined variant, not only the ones being compared: the multi-variant check has to
        # see a person who also saw a third arm, or that person reads as single-variant and is
        # attributed to an arm they only half belong to.
        return self.exposure.condition(self.variant_keys)

    def variant_value(self) -> ast.Expr:
        return self.exposure.variant_value()

    def window_conditions(self, start: datetime) -> list[ast.Expr]:
        return [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=start),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.window_end),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq, left=ast.Field(chain=["$session_id"]), right=ast.Constant(value="")
            ),
            *get_test_accounts_filter(self.team, self.experiment.exposure_criteria),
        ]

    def exposed_sessions(self, start: datetime, *, of: str) -> ast.SelectQuery:
        # The exposed sessions, most recent first. Its only job is to bound what the scan
        # aggregates: without it the scan would hold one row per person in the whole window rather
        # than per exposed person.
        #
        # On the default path the exposure condition carries an event name, so ClickHouse prunes
        # this on the events table's primary key. Under the exposure fallback there is no event
        # name to prune on, only the stamped flag property, so it reads the window instead. That is
        # the same posture the session buckets take on their own fallback path, but it lands harder
        # here because three queries in one response each resolve this subquery.
        #
        # `of` picks the one column each use site can take: the ceiling has to be applied before
        # either is read, and an IN subquery may only return one.
        last_seen = ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])]))
        return ast.SelectQuery(
            select=[last_seen if of == "last_seen" else ast.Field(chain=[of])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=[*self.window_conditions(start), self.exposure_condition()]),
            group_by=[ast.Field(chain=["$session_id"])],
            order_by=[
                ast.OrderExpr(expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])]), order="DESC"),
            ],
            limit=ast.Constant(value=MAX_DELTA_SCAN_SESSIONS),
        )

    def run(self, query: ast.SelectQuery) -> list[tuple]:
        response = execute_hogql_query(
            query,
            team=self.team,
            user=self.user,
            context=self.shared_hogql.fresh_context(self.team, self.user),
            modifiers=self.shared_hogql.modifiers,
        )
        return list(response.results or [])


def _cache_key(
    team: Team,
    user: User,
    experiment: Experiment,
    window_start: datetime,
    window_end: datetime,
    default_exposure_event: str,
) -> str:
    # The version segment must be bumped whenever ExperimentWatchResult or SessionEventDeltaScan
    # changes shape: entries are pickled, so a deploy would otherwise restore instances missing the
    # new fields.
    spec = json.dumps(
        [
            # Which event the default exposure resolved to. The $experiment_exposure rollout can
            # flip under a team, and cards computed on the other event are a different population.
            default_exposure_event,
            # The window moves with wall-clock time on a running experiment, so it is quantized to
            # the cache's own TTL rather than to the minute: at minute resolution the key changes
            # every minute and the entry it would have reused is still warm, so every reload pays
            # for a full scan. The cost of the coarser bucket is that an answer can be one TTL
            # stale, which is what the TTL already promised.
            int(window_start.timestamp()) // DELTA_CACHE_TTL,
            int(window_end.timestamp()) // DELTA_CACHE_TTL,
            # The experiment's metrics decide what is excluded from the comparison and what gets a
            # shortcut card, its exposure criteria decide who is compared and how someone who saw
            # two variants is split, and the flag's variants decide the arms. All of them are
            # editable while an entry is warm, and none can be re-applied on read, so an edit has
            # to miss the cache rather than be served the answer to the previous configuration.
            experiment.updated_at.isoformat(),
            experiment.feature_flag.updated_at.isoformat() if experiment.feature_flag.updated_at else None,
            # A saved metric is editable without touching the experiment row, and its events decide
            # exclusions and shortcut cards the same way an inline metric's do.
            sorted(updated.isoformat() for updated in experiment.saved_metrics.values_list("updated_at", flat=True)),
            # Property restrictions are compiled into the SQL, so a restriction change has to miss
            # the cache rather than be re-applied on read.
            sorted(get_restricted_properties_for_team(user=user, team=team)),
        ]
    )
    digest = hashlib.sha256(spec.encode()).hexdigest()[:16]
    # Keyed by the viewer's restriction profile, not by the viewer: the property restrictions in
    # the digest are the only viewer-dependent input to the scan, and per-recording access is
    # applied on read. One viewer's scan then serves every viewer whose restrictions match, which
    # on the heaviest read in this family is the difference between paying it once per team per
    # TTL and once per viewer.
    return f"experiment_session_event_deltas_v4_{team.pk}_{experiment.pk}_{digest}"


def _metric_event_names(metrics: list[MetricEventSource]) -> set[str]:
    """Every named event this experiment's metrics count.

    These are excluded from the comparison and shortcut instead. Sources with no single event name
    (actions, all-events nodes) are skipped — they can match client-captured events, so their
    identity can't be decided from a name.
    """
    return {
        source.node.event
        for metric in metrics
        for source in metric.sources
        if isinstance(source.node, EventsNode) and source.node.event
    }


def _query_event_deltas(
    setup: _QuerySetup,
    *,
    multiple_variant_handling: MultipleVariantHandling,
    excluded_events: list[str],
    window_start: datetime,
) -> SessionEventDeltaScan:
    # What the session ceiling actually covers. Cheap next to the scan — it prunes on the exposure
    # event name — and it is what lets the scan skip the stretch of the window where none of the
    # covered sessions live. On a busy project that is most of the window.
    coverage = setup.run(
        ast.SelectQuery(
            select=[
                ast.Call(name="min", args=[ast.Field(chain=["last_seen"])]),
                ast.Call(name="count", args=[]),
            ],
            select_from=ast.JoinExpr(table=setup.exposed_sessions(window_start, of="last_seen")),
        )
    )
    covered_sessions = int(coverage[0][1]) if coverage else 0
    if not covered_sessions:
        return SessionEventDeltaScan(
            persons={}, sessions={}, events_truncated=False, sessions_truncated=False, covered_from=window_start
        )
    oldest_covered: datetime = coverage[0][0]
    covered_from = max(window_start, oldest_covered - timedelta(hours=MAX_SESSION_DURATION_HOURS))

    # One row per (person, exposed session): when it began, which arm its exposures carried, and
    # which event names it contains. The uncomparable names are dropped here rather than in the
    # WHERE so a session whose only events are exposures still produces a row and its person still
    # counts toward their arm's total.
    session_rows = ast.SelectQuery(
        select=[
            ast.Field(chain=["person_id"]),
            ast.Alias(alias="started", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(
                alias="first_exposure",
                expr=ast.Call(name="minIf", args=[ast.Field(chain=["timestamp"]), setup.exposure_condition()]),
            ),
            ast.Alias(
                alias="session_variant",
                expr=ast.Call(
                    name="argMinIf",
                    args=[setup.variant_value(), ast.Field(chain=["timestamp"]), setup.exposure_condition()],
                ),
            ),
            ast.Alias(
                alias="session_variants",
                expr=ast.Call(name="countDistinctIf", args=[setup.variant_value(), setup.exposure_condition()]),
            ),
            ast.Alias(
                alias="event_names",
                expr=ast.Call(
                    name="groupUniqArrayIf",
                    args=[
                        ast.Field(chain=["event"]),
                        ast.And(
                            exprs=[
                                ast.Call(name="notEmpty", args=[ast.Field(chain=["event"])]),
                                ast.Call(
                                    name="not",
                                    args=[
                                        ast.Call(
                                            name="has",
                                            args=[
                                                ast.Constant(value=excluded_events),
                                                ast.Field(chain=["event"]),
                                            ],
                                        )
                                    ],
                                ),
                            ]
                        ),
                    ],
                ),
            ),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                *setup.window_conditions(covered_from),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["$session_id"]),
                    # Re-resolved over the clamped window rather than passed in as ids: the ceiling
                    # picks the same sessions either way, and 20,000 ids inlined into the SQL is a
                    # megabyte of query text.
                    right=setup.exposed_sessions(covered_from, of="$session_id"),
                ),
            ]
        ),
        group_by=[ast.Field(chain=["person_id"]), ast.Field(chain=["$session_id"])],
    )

    # A (person, session) group can carry no exposure at all: server-side events reuse a client
    # session's `$session_id` under their own person, so a covered session can hold a second
    # person who was never exposed in it. Such a group's `session_variant` is NULL and its
    # `first_exposure` is the epoch default, and the variant selections below stay correct only
    # because ClickHouse aggregates skip NULL arguments — countDistinct can't count the NULL toward
    # "saw two variants", and argMin can't let the epoch-timestamped NULL win. Wrapping these
    # values in coalesce/assumeNotNull would silently misattribute every person who shares a
    # session. The person's behavior and session count get no such implicit protection — their
    # inputs are non-null even in an unexposed group — so both are conditioned on the group
    # carrying an exposure explicitly, in `person_rows` below.
    if multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
        # Mirrors get_variant_selection_expr across the person's sessions rather than within one.
        variant_expr: ast.Expr = ast.Call(
            name="argMin", args=[ast.Field(chain=["session_variant"]), ast.Field(chain=["first_exposure"])]
        )
    else:
        variant_expr = ast.Call(
            name="if",
            args=[
                ast.Or(
                    exprs=[
                        # Two arms across their sessions, or two inside one of them. The second is
                        # not implied by the first: a session carrying both exposures can still be
                        # the person's only one.
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Gt,
                            left=ast.Call(name="countDistinct", args=[ast.Field(chain=["session_variant"])]),
                            right=ast.Constant(value=1),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Gt,
                            left=ast.Call(name="max", args=[ast.Field(chain=["session_variants"])]),
                            right=ast.Constant(value=1),
                        ),
                    ]
                ),
                ast.Constant(value=MULTIPLE_VARIANT_KEY),
                ast.Call(name="any", args=[ast.Field(chain=["session_variant"])]),
            ],
        )

    # One row per exposed person: which arm they saw, how many sessions of theirs the comparison
    # covers, and what they did in the first of them. Only the first, because the arms don't
    # necessarily get the same number of sessions per person — a variant that stops re-evaluating
    # the flag once someone has acted contributes fewer later sessions, and a person seen in seven
    # sessions has seven times the chance to have done anything than one seen in two. Measured on a
    # production experiment that difference alone put nine in ten event names on the same side of
    # the comparison; one session each removes it.
    # Exposed sessions only, for both the count and the behavior read: a person can also appear in
    # a covered session someone else was exposed in, and reading behavior from there would break
    # "read from the first session *they* were exposed in" — their real exposed session's events
    # silently replaced by whatever they did in a session the comparison never bucketed them by.
    group_is_exposed = ast.CompareOperation(
        op=ast.CompareOperationOp.Gt,
        left=ast.Field(chain=["session_variants"]),
        right=ast.Constant(value=0),
    )
    person_rows = ast.SelectQuery(
        select=[
            ast.Alias(alias="variant", expr=variant_expr),
            ast.Alias(alias="session_count", expr=ast.Call(name="countIf", args=[group_is_exposed])),
            ast.Alias(
                alias="event_names",
                expr=ast.Call(
                    name="argMinIf",
                    args=[ast.Field(chain=["event_names"]), ast.Field(chain=["started"]), group_is_exposed],
                ),
            ),
        ],
        select_from=ast.JoinExpr(table=session_rows),
        group_by=[ast.Field(chain=["person_id"])],
    )

    # The empty event name is the arm's own totals. They ride the same aggregation so the
    # denominator can never be computed over a different set than the numerators — and `notEmpty`
    # above guarantees no real event name collides with it.
    query = ast.SelectQuery(
        select=[
            ast.Alias(
                alias="event_name",
                expr=ast.Call(
                    name="arrayJoin",
                    args=[
                        ast.Call(
                            name="arrayConcat",
                            args=[ast.Array(exprs=[ast.Constant(value="")]), ast.Field(chain=["event_names"])],
                        )
                    ],
                ),
            ),
            ast.Field(chain=["variant"]),
            ast.Alias(alias="persons", expr=ast.Call(name="count", args=[])),
            ast.Alias(alias="sessions", expr=ast.Call(name="sum", args=[ast.Field(chain=["session_count"])])),
        ],
        select_from=ast.JoinExpr(table=person_rows),
        # Every arm, not only the qualifying ones: the totals are what decide which arms qualify at
        # all, and on a three-arm experiment a total over two arms could never reach the ceiling.
        group_by=[ast.Field(chain=["event_name"]), ast.Field(chain=["variant"])],
        # By name, not by count: every arm's rows for one event stay adjacent, so hitting the
        # ceiling drops whole events instead of leaving an event with one arm's count and a silent
        # zero for the others.
        order_by=[
            ast.OrderExpr(expr=ast.Field(chain=["event_name"]), order="ASC"),
            ast.OrderExpr(expr=ast.Field(chain=["variant"]), order="ASC"),
        ],
        # One past the cap, so a result that lands exactly on it isn't read as cut short.
        limit=ast.Constant(value=MAX_DELTA_EVENT_ROWS + 1),
    )

    rows = [(str(row[0]), str(row[1]), int(row[2]), int(row[3])) for row in setup.run(query)]
    events_truncated = len(rows) > MAX_DELTA_EVENT_ROWS
    if events_truncated:
        # The ceiling can land between an event's arm rows, which would read as one arm never
        # having done it. Dropping the last event name is exact rather than nearly right.
        last_event = rows[-1][0]
        rows = [row for row in rows if row[0] != last_event]

    return SessionEventDeltaScan(
        persons={(event_name, variant): persons for event_name, variant, persons, _sessions in rows},
        sessions={variant: sessions for event_name, variant, _persons, sessions in rows if event_name == ""},
        events_truncated=events_truncated,
        sessions_truncated=covered_sessions >= MAX_DELTA_SCAN_SESSIONS,
        covered_from=covered_from,
    )


def _separation(
    *, baseline_count: int, target_count: int, baseline_persons: int, target_persons: int
) -> tuple[float, float]:
    """The smoothed ratio of the two populations' rates, and how much of it survives the noise.

    The second number is the conservative end of the ratio in log space: the difference minus the
    uncertainty in it, so an event two people did more of in one arm cannot outrank one hundreds
    did, however lopsided the raw ratio looks. Zero means the populations are indistinguishable on
    it.
    """
    baseline_share = (baseline_count + RATIO_SMOOTHING) / (baseline_persons + 1)
    target_share = (target_count + RATIO_SMOOTHING) / (target_persons + 1)
    ratio = target_share / baseline_share

    # Standard error of the log of a ratio of two independent proportions. Independent is why the
    # unit is the person: two sessions of one person are not, and treating them as such is what
    # makes an A/A comparison look full of findings.
    variance = (
        1 / (baseline_count + RATIO_SMOOTHING)
        + 1 / (target_count + RATIO_SMOOTHING)
        - 1 / (baseline_persons + 1)
        - 1 / (target_persons + 1)
    )
    standard_error = math.sqrt(max(variance, 0.0))
    return ratio, max(abs(math.log(ratio)) - CONFIDENCE_Z * standard_error, 0.0)


def _strength(*, separation: float, baseline_count: int, target_count: int) -> DeltaStrength:
    """Which band the difference falls in, read off the conservative end of it rather than the raw
    one. A card that is only past the floor because the sample is large says "slightly", however
    big the point estimate looks."""
    if not baseline_count or not target_count:
        return DeltaStrength.ONLY
    if separation >= FAR_MORE_LOG_RATIO:
        return DeltaStrength.FAR_MORE
    if separation >= MORE_LOG_RATIO:
        return DeltaStrength.MORE
    return DeltaStrength.SLIGHTLY_MORE


def _pick_behavior_cards(scan: SessionEventDeltaScan, *, arm_keys: list[str]) -> list[ExperimentWatchCard]:
    """The events one arm did clearly more than the other arms pooled, strongest first.

    One card per event at most, on the arm where it is most over-represented — an event five arms
    share is nobody's finding, and an event one arm lacks shows up as the other arms' card. Pooling
    the rest is what makes a five-arm experiment cost the same ranking as two; on two arms it *is*
    the pairwise comparison.
    """
    arm_persons = {key: scan.persons.get(("", key), 0) for key in arm_keys}
    total_persons = sum(arm_persons.values())
    event_names = {event_name for event_name, _variant in scan.persons if event_name != ""}

    picked: list[tuple[float, ExperimentWatchCard]] = []
    for event_name in sorted(event_names):
        counts = {key: scan.persons.get((event_name, key), 0) for key in arm_keys}
        total_count = sum(counts.values())
        best: Optional[tuple[float, ExperimentWatchCard]] = None
        for key in arm_keys:
            rest_persons = total_persons - arm_persons[key]
            rest_count = total_count - counts[key]
            if counts[key] < MIN_SUPPORT_PERSONS or not rest_persons:
                continue
            # Only where the arm over-indexes: the card's recordings live on the arm that did the
            # event, and under-indexing is the same fact seen from the other arms' cards.
            if counts[key] * rest_persons <= rest_count * arm_persons[key]:
                continue
            _ratio, separation = _separation(
                baseline_count=rest_count,
                target_count=counts[key],
                baseline_persons=rest_persons,
                target_persons=arm_persons[key],
            )
            if separation < MIN_LOG_RATIO_LOWER_BOUND:
                continue
            card = ExperimentWatchCard(
                kind=WatchCardKind.FRICTION if event_name in FRICTION_EVENTS else WatchCardKind.BEHAVIOR,
                event=event_name,
                variant=key,
                strength=_strength(separation=separation, baseline_count=rest_count, target_count=counts[key]),
                metric_name=None,
                recording_count=0,
                session_ids=[],
            )
            if best is None or separation > best[0]:
                best = (separation, card)
        if best is not None:
            picked.append(best)

    picked.sort(key=lambda entry: (-entry[0], entry[1].event))
    # Friction is capped by FRICTION_EVENTS instead, at one card per name, because it renders on
    # its own shelf and is the first thing a reader triages. Sharing one budget would let a run of
    # behavior findings push the only $exception card out of the response entirely.
    behavior = [card for _separation_value, card in picked if card.kind == WatchCardKind.BEHAVIOR]
    friction = [card for _separation_value, card in picked if card.kind == WatchCardKind.FRICTION]
    return behavior[:MAX_BEHAVIOR_CARDS] + friction


def _metric_card_candidates(
    metrics: list[MetricEventSource], *, arm_keys: list[str], never_linked: frozenset[str]
) -> tuple[list[ExperimentWatchCard], dict[str, list[EventsNode]]]:
    """Shortcut cards to recordings around the experiment's own metric events, one per arm.

    No strength and no comparison claim: what happened to the metric is the results tab's answer.
    These cards only say "here is the metric's event happening on screen, in this arm". Events that
    have only ever been captured server-side can't back a recording and are skipped outright.

    Also returns each card event's source nodes from the metric whose name the card carries, so the
    recordings lookup can honor that metric's property filters: the card is labeled with the
    metric's name, and a recording of the event happening outside the metric would be mislabeled.
    """
    named: list[tuple[str, str]] = []
    owner_by_event: dict[str, str] = {}
    nodes_by_event: dict[str, list[EventsNode]] = {}
    for metric in metrics:
        for source in metric.sources:
            node = source.node
            if not isinstance(node, EventsNode) or not node.event:
                continue
            if node.event in UNCOMPARABLE_EVENTS or node.event in never_linked:
                continue
            if node.event not in owner_by_event:
                owner_by_event[node.event] = metric.metric_uuid
                nodes_by_event[node.event] = [node]
                named.append((node.event, metric.metric_name))
            elif owner_by_event[node.event] == metric.metric_uuid:
                # Another source of the owning metric on the same event — a funnel can repeat an
                # event across steps with different filters, and any of them counts as the metric.
                nodes_by_event[node.event].append(node)

    kept = named[:MAX_METRIC_CARD_EVENTS]
    cards = [
        ExperimentWatchCard(
            kind=WatchCardKind.METRIC,
            event=event,
            variant=arm_key,
            strength=None,
            metric_name=metric_name,
            recording_count=0,
            session_ids=[],
        )
        for event, metric_name in kept
        for arm_key in arm_keys
    ]
    return cards, {event: nodes_by_event[event] for event, _name in kept}


def _recordings_for_cards(
    setup: _QuerySetup,
    *,
    wanted: list[tuple[str, str]],
    covered_from: datetime,
    metric_nodes: Optional[dict[str, list[EventsNode]]] = None,
) -> dict[tuple[str, str], list[str]]:
    """Recent recorded sessions per (event, arm) pair, most recent first.

    Unlike the scan this prunes on event names, so it reads a sliver of the window. Every candidate
    then goes through replay's own existence check rather than being trusted because it was exposed:
    replay sampling, retention and deletion mean most exposed sessions have nothing to play, and a
    card is only as good as the recordings behind it.
    """
    wanted_events = sorted({event for event, _arm in wanted})
    wanted_arms = sorted({arm for _event, arm in wanted})
    # A metric card's event counts only where the metric's own property filters hold: the card
    # carries the metric's name, so a recording of the event happening outside the metric would be
    # mislabeled. An unfiltered source subsumes any filtered one on the same event, so an event
    # with one stays on the plain name match.
    filtered_nodes = {
        event: nodes
        for event, nodes in (metric_nodes or {}).items()
        if event in wanted_events and all(node.properties or node.fixedProperties for node in nodes)
    }
    plain_events = [event for event in wanted_events if event not in filtered_nodes]

    def card_event_match() -> ast.Expr:
        # Rebuilt per use site, like the setup's own builders: the HogQL resolver annotates ast
        # nodes in place, so one instance can't appear in two clauses of the same query.
        conditions: list[ast.Expr] = []
        if plain_events:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=plain_events),
                )
            )
        for nodes in filtered_nodes.values():
            conditions.extend(build_source_condition(node, setup.team) for node in nodes)
        if not conditions:
            return ast.Constant(value=False)
        return ast.Or(exprs=conditions) if len(conditions) > 1 else conditions[0]

    wanted_event_rows = card_event_match()
    if setup.exposure.used_fallback:
        # The stamped flag property rides on the wanted events themselves, so their names are the
        # whole predicate.
        reachable_rows: ast.Expr = wanted_event_rows
    else:
        # The exposure condition itself rather than the name of the event it matches, because an
        # action-based exposure config resolves to no single name: `get_exposure_event_and_property`
        # returns None for one, since an action can match several events. An event-name list would
        # then drop every exposure row, leaving each session with no variant and every card
        # unbacked. The condition carries the action's own event predicates, so ClickHouse still
        # prunes on the events table's primary key. Same shape as the session buckets' WHERE.
        reachable_rows = ast.Or(exprs=[wanted_event_rows, setup.exposure_condition()])

    session_rows = ast.SelectQuery(
        select=[
            ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"])),
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
            ast.Alias(
                alias="variant",
                expr=ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Gt,
                            left=ast.Call(
                                name="countDistinctIf", args=[setup.variant_value(), setup.exposure_condition()]
                            ),
                            right=ast.Constant(value=1),
                        ),
                        ast.Constant(value=MULTIPLE_VARIANT_KEY),
                        ast.Call(name="anyIf", args=[setup.variant_value(), setup.exposure_condition()]),
                    ],
                ),
            ),
            ast.Alias(
                alias="events_present",
                expr=ast.Call(
                    name="groupUniqArrayIf",
                    args=[ast.Field(chain=["event"]), card_event_match()],
                ),
            ),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                *setup.window_conditions(covered_from),
                reachable_rows,
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["$session_id"]),
                    right=setup.exposed_sessions(covered_from, of="$session_id"),
                ),
            ]
        ),
        group_by=[ast.Field(chain=["$session_id"])],
    )

    candidates_query = ast.SelectQuery(
        select=[
            ast.Alias(alias="event_name", expr=ast.Call(name="arrayJoin", args=[ast.Field(chain=["events_present"])])),
            ast.Field(chain=["variant"]),
            ast.Field(chain=["session_id"]),
        ],
        select_from=ast.JoinExpr(table=session_rows),
        # A session that saw more than one variant belongs to no card. The check is per session
        # here while the scan makes it per person across all of theirs, so under `exclude` a card
        # can carry a recording from someone the comparison itself set aside, and under
        # `first_seen` one from a session the scan counted toward another arm. Same split as the
        # module docstring's: the comparison needs a fair population, the watchlist needs the
        # behavior on screen.
        where=ast.CompareOperation(
            op=ast.CompareOperationOp.In, left=ast.Field(chain=["variant"]), right=ast.Constant(value=wanted_arms)
        ),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["last_seen"]), order="DESC")],
        limit_by=ast.LimitByExpr(
            n=ast.Constant(value=MAX_CARD_RECORDING_CANDIDATES),
            exprs=[ast.Field(chain=["event_name"]), ast.Field(chain=["variant"])],
        ),
        # Sized on what LIMIT BY can emit, not on the cards asked for. The arrayJoin produces every
        # (wanted event, wanted arm) pair that occurs, which is more pairs than there are cards —
        # a carded event also happens in the arms that didn't earn a card. LIMIT runs after LIMIT BY
        # and cuts by recency across all of them, so a limit sized on the cards would drop a card's
        # older recordings in favor of rows belonging to a pair nobody asked about, and the card
        # would then be dropped as unbacked.
        limit=ast.Constant(value=MAX_CARD_RECORDING_CANDIDATES * max(len(wanted_events) * len(wanted_arms), 1)),
    )

    # The query emits every (wanted event, wanted arm) pair that occurs — a carded event also
    # happens in arms that earned no card — but only the pairs a card actually asked for go on to
    # the replay existence check, which pays per id.
    wanted_pairs = set(wanted)
    candidates: dict[tuple[str, str], list[str]] = {}
    for row in setup.run(candidates_query):
        pair = (str(row[0]), str(row[1]))
        if pair in wanted_pairs:
            candidates.setdefault(pair, []).append(str(row[2]))

    all_session_ids = sorted({session_id for ids in candidates.values() for session_id in ids})
    if not all_session_ids:
        return {}

    # Replay's own existence check rather than a read of the replay summaries here: "a row exists"
    # is not the same question as "this recording can be opened", and only that helper applies the
    # team's retention period and the deleted flag. A card promising a recording that expired or was
    # deleted is the one failure the whole shelf is built to avoid.
    exists_by_id = SessionReplayEvents().batch_exists(all_session_ids, setup.team)
    recorded = {session_id for session_id in all_session_ids if exists_by_id.get(session_id)}

    return {
        pair: [session_id for session_id in ids if session_id in recorded][:MAX_CARD_RECORDINGS]
        for pair, ids in candidates.items()
    }
