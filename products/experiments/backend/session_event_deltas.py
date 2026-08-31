"""Pick the recordings worth watching in one experiment's exposed sessions.

The recordings tab can list an arm's sessions but says nothing about which of the thousands carry
signal, so picking what to watch is sampling rather than targeting. This module answers that with
watch cards: bounded groups of recordings, each one a sentence a reader can act on — "this arm did
this event clearly more than the others, here are recordings of it happening".

**Recordings are the deliverable.** A card's count is a count of watchable recordings, checked
against replay existence before the card is returned; a finding that no recording can back is
dropped, because a promise the playlist can't keep reads as the feature being broken. The event
comparison underneath is the picking mechanism, not the product. A card also names a few of its
recordings to start with, each carrying the signals that earn it the place, because narrowing
thousands of recordings to twenty still leaves twenty that a list renders identically and the
recordings list orders by its own sort rather than by the order they arrive in.

**It reports no effect size, on purpose, and this is the constraint the file serves.** The results
tab publishes one already, from a real statistics engine: per person, over the whole run window,
with sample-ratio checks and credible intervals behind it. This reads one session per person over a
window clamped to hours or days. Measured on a production experiment the two agreed on direction
for every shared event and on no number at all — 7.5x there against 41x here for the same event —
because the later sessions where people convert are outside what this reads. So the three rules
that follow are not stylistic:

  1. Cards carry a direction and a band, never a rate, a ratio or a person count. Whatever we
     called it, a precise number next to an event name is an effect size, and would be read
     against the one the results tab computes.
  2. A card on one of the experiment's own metric events names the metric it belongs to and says
     nothing about how that metric moved. Metric events are ranked like any other event rather
     than held out, because on a UI experiment the events closest to the change are usually the
     ones a metric already counts: measured on two production experiments, the largest separation
     in the whole project was a metric event both times, and holding them out left the shelf
     ranking incidental events or nothing at all. What must not happen is a second, differently
     computed answer to the question the results tab answers, and rule 1 is what prevents that.
  3. An event no other variant can fire is the variant's own rendering rather than something a
     person chose to do, so it is separated onto its own shelf and capped. A variant that ships a
     new element instruments that element, and such an event separates the arms perfectly, so
     without the split it outranks every real behavioral difference: measured on a production
     experiment, the two strongest findings were a callout variant's own impression and dismissal
     events, at a thousand times the separation of anything a person actually did differently.

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
from posthog.utils import get_safe_cache, pluralize, safe_cache_set

from products.access_control.backend.property_access_control import (
    get_restricted_properties_with_group_type_index_for_team,
)
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
from products.experiments.backend.models.experiment import Experiment, metric_display_rank
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
# How many events the variant's own rendering emits get a card. They confirm the change is live and
# say nothing about behavior, so a couple covers the question however many such events a variant
# instruments.
MAX_VARIANT_ONLY_CARDS = 2
# How many of the experiment's metric events get shortcut cards, in the order the experiment's own
# metrics page lists them, so the metric a reader thinks of first is the one they get. An event that
# already earned a comparison card is not repeated as a shortcut.
MAX_METRIC_CARD_EVENTS = 2
# How many recordings a card names to start with. Enough to offer a choice, few enough that the
# reader still opens one instead of reading a second list.
MAX_CARD_HIGHLIGHTS = 3
# Two cards sharing this much of their recordings are one playlist under two names, so the second
# one is dropped, e.g. if two cards share 18 of their 20 recordings.
DUPLICATE_CARD_OVERLAP = 0.8
# How far one count can carry a recording up the highlight order. Past a few occurrences a count
# measures how long the session is rather than what it shows, and raw totals hand every card the
# same longest session. Only the ranking is bounded; the reason still prints the true count.
HIGHLIGHT_COUNT_DAMPING = 3
# A session at or past this many of one friction signal, without a single rage click, is a client
# stuck in an error loop or automation, not a person to watch, so it is never offered as a
# highlight. It stays on its cards' playlists. A rage click exempts the session because it is the
# one signal only a person produces: as of August 2026, production sessions past this bound with a
# rage click show a median 23 active minutes across several distinct errors (a person suffering
# through them), while those without show under a minute of activity and one error repeating.
MAX_HIGHLIGHT_SIGNAL_COUNT = 100
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
# When the other variants are this close to never firing an event at all, relative to how often
# they would have fired it at this arm's rate, they are not doing it less: they have no way to do
# it. A leak is tolerated rather than requiring a flat zero because an element one variant renders
# can still be reached from the others by a shared route, and because a person who saw two variants
# in a session the comparison kept carries one arm's events under the other's key.
VARIANT_ONLY_MAX_LEAKAGE = 0.02
# ...and how many people doing it the other variants had to be missing before their absence means
# anything. The comparison counts each person once, so this floor is an expected count of people
# who did the event, not of event occurrences. Below it, "nobody else did it" is what a handful of
# people looks like whatever the cause, so the card stays on the behavior shelf and the evidence
# floors decide whether it appears at all.
VARIANT_ONLY_MIN_EXPECTED = 10.0
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

# What a card ranks its own recordings by, strongest kind first, as (event name, singular label).
# Counted per session rather than compared across arms: each is a property of the session rather
# than of the event that earned the card, so a recording keeps the same reason on every card it
# backs. Counted over the whole covered session, so the phrase still describes what the reader sees
# once the recording is open. One more signal rides alongside these without being one of them: how
# many times the session fired the card's own event, which is per card by construction and so
# computed at pick time rather than here.
HIGHLIGHT_SIGNALS: tuple[tuple[str, str], ...] = (
    ("$rageclick", "rage click"),
    ("$exception", "error"),
    ("$dead_click", "dead click"),
)

# Events whose card belongs on the friction shelf rather than the behavior one. Same pipeline and
# the same evidence bar — the split is presentation: a reader triages "the new variant breaks
# something" differently from "the new variant changes what people do". Derived from the highlight
# signals because they are the same three events by design: what the friction shelf cards and what
# a highlight reason counts as friction must never disagree.
FRICTION_EVENTS = frozenset(event for event, _singular in HIGHLIGHT_SIGNALS)

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
    # An event only this arm can fire, because the arm is what renders it. Confirms the change is
    # live rather than saying anything about what people did with it.
    VARIANT_ONLY = "variant_only"
    # A shortcut to recordings around one of the experiment's own metric events. No comparison
    # claim: what happened to the metric is the results tab's answer.
    METRIC = "metric"


@dataclass(frozen=True)
class ExperimentWatchHighlight:
    """One recording a card names first, and everything it carries that earned it the place.

    The friction signals are session-level rather than per event, so a recording keeps them on
    every card it backs. That is deliberate: the reason has to survive a reader opening the
    recording, and "this session rage clicked six times" does, while anything scoped to the card's
    own event would contradict itself the moment the same session appeared under a second card.
    The one per-card part, "did this N times", survives the same trip because "this" reads against
    whichever card it is printed on.
    """

    session_id: str
    reason: str


@dataclass(frozen=True)
class _CardRecordings:
    """What one card's recordings lookup found: the recordings themselves, and which of them to
    open first."""

    session_ids: list[str]
    highlights: list[ExperimentWatchHighlight]


@dataclass(frozen=True)
class _MetricEvent:
    """One named event an experiment metric counts, and the name of the metric that owns it."""

    event: str
    metric_name: str


@dataclass(frozen=True)
class _CandidateRecording:
    """One session behind one (event, arm) pair: its session-level signal counts, and how often it
    fired the pair's own event."""

    session_id: str
    signals: dict[str, int]
    repetition: int


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
    # The metric this card's event belongs to, on a shortcut card and on a comparison card alike.
    # Set means the results tab measures this event, so the card must be read as pointing there
    # rather than as a second answer.
    metric_name: Optional[str]
    recording_count: int
    session_ids: list[str]
    # Which of those recordings to open first, strongest signal first. Empty when none of them
    # carries one, which is itself worth showing: it says the card's recordings are unremarkable
    # apart from the event that earned the card.
    highlights: list[ExperimentWatchHighlight]


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
    # Reported so a reader can tell a card carrying every recording of its event from one that ran
    # into the ceiling. A count sitting on the cap is a floor, and printed as a plain number beside
    # an event name it reads as a measurement of that event.
    max_card_recordings: int
    # How many cards the duplicate-recording-set rule removed from this viewer's shelf, reported
    # so the shelf-loaded telemetry can say how often DUPLICATE_CARD_OVERLAP fires on real shelves
    # before anyone tunes it. Set in `finalize_watch_cards` rather than here, because the shelf is
    # cached across viewers and the duplicate cut runs on the shelf a viewer actually gets.
    dropped_duplicate_cards: int
    too_early: bool


def all_card_session_ids(result: ExperimentWatchResult) -> list[str]:
    """Every recording the shelf would hand out, deduped — what the caller runs its per-recording
    access filter over."""
    return sorted({session_id for card in result.cards for session_id in card.session_ids})


def finalize_watch_cards(result: ExperimentWatchResult, accessible_session_ids: list[str]) -> ExperimentWatchResult:
    """The shelf this viewer gets: their recordings, no card restating another, highlights assigned.

    Applied on read rather than inside the scan, for the same reason the session buckets do it: the
    shelf is cached, and shared across viewers with the same property restrictions, so this cut is
    what keeps one viewer's entry from leaking another's denied recordings, and it honors a
    revocation that lands while an entry is still warm. A card that loses every recording is
    dropped rather than shown greyed-out, the same rule the scan applies to sessions replay never
    recorded, since either way there is nothing to watch behind it. `recording_count` is recomputed
    so it keeps meaning "recordings this card can show you".

    The cut is silent, as it is on the bucket and batch-context reads: the response must not say
    whether this filter removed anything, because that would tell the viewer recordings denied to
    them ran through this experiment, which is the fact the object-level control withholds.

    The duplicate cut and the highlight assignment run here rather than in the scan because both
    are statements about the shelf a viewer sees. Cutting a duplicate against recordings this
    viewer can't open would drop a card whose remaining recordings they can, and could leave two
    surviving cards showing the same ones; naming a card's first recordings before either cut lets
    a card that is no longer on the shelf keep its claim on one.
    """
    accessible = set(accessible_session_ids)
    cards = []
    for card in result.cards:
        session_ids = [session_id for session_id in card.session_ids if session_id in accessible]
        if session_ids:
            highlights = [highlight for highlight in card.highlights if highlight.session_id in accessible]
            cards.append(
                replace(card, recording_count=len(session_ids), session_ids=session_ids, highlights=highlights)
            )
    deduped = _drop_duplicate_recording_sets(cards)
    return replace(result, cards=_assign_highlights(deduped), dropped_duplicate_cards=len(cards) - len(deduped))


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

    # Metric events stay in — the module docstring's second rule. A card on one is labeled with its
    # metric instead of being held out of the ranking. Never-session-linked events need no exclusion
    # here: every query in this family requires a non-empty $session_id, so an event that has never
    # carried one cannot be counted, let alone carded.
    excluded_events = sorted(
        UNCOMPARABLE_EVENTS | ({exposure.exposure_event} if exposure.exposure_event is not None else set())
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

    cards: list[ExperimentWatchCard] = []
    if not too_early:
        named_metric_events, nodes_by_metric_event = _metric_events_by_name(metrics, experiment)
        comparison_candidates = _pick_behavior_cards(
            scan,
            arm_keys=qualified_arms,
            metric_names_by_event={named.event: named.metric_name for named in named_metric_events},
        )
        carded_events = {candidate.event for candidate in comparison_candidates}
        metric_cards = _metric_card_candidates(
            named_metric_events,
            arm_keys=qualified_arms,
            never_linked=exposure.never_linked,
            # An event that already won a comparison card is not offered a second time as a
            # shortcut to the same recordings, which on a two-metric experiment would be half the
            # shelf restating the other half.
            carded_events=carded_events,
        )
        # A metric's property filters narrow the recordings behind its *shortcut* cards only. A
        # comparison card was ranked on the bare event name, so filtering its recordings would show
        # a narrower set than the one that earned it the card, and could leave it with none.
        resolved = _resolve_cards(
            setup,
            candidates=[*comparison_candidates, *metric_cards],
            metric_nodes=_shortcut_nodes(metric_cards, nodes_by_metric_event),
            covered_from=scan.covered_from,
        )
        comparison_cards = [card for card in resolved if card.kind != WatchCardKind.METRIC]
        shortcut_by_pair = {(card.event, card.variant): card for card in resolved if card.kind == WatchCardKind.METRIC}

        # The shortcut selection is decided again now that survival is known: a comparison
        # candidate that died on the replay existence check must not keep suppressing its event's
        # shortcuts, or an event the experiment measures vanishes from the shelf just because the
        # one arm that earned its comparison card had nothing recorded. Re-running the selection,
        # rather than appending a recovery batch, keeps the shelf inside MAX_METRIC_CARD_EVENTS
        # and keeps a recovered event at its display-order position instead of after lower-ranked
        # ones, which can also displace a lower-ranked event's already-resolved shortcut cards.
        final_shortcuts = _metric_card_candidates(
            named_metric_events,
            arm_keys=qualified_arms,
            never_linked=exposure.never_linked,
            carded_events={card.event for card in comparison_cards},
        )
        queried_events = {card.event for card in metric_cards}
        unqueried = [card for card in final_shortcuts if card.event not in queried_events]
        if unqueried:
            shortcut_by_pair.update(
                {
                    (card.event, card.variant): card
                    for card in _resolve_cards(
                        setup,
                        candidates=unqueried,
                        metric_nodes=_shortcut_nodes(unqueried, nodes_by_metric_event),
                        covered_from=scan.covered_from,
                    )
                }
            )
        cards = comparison_cards + [
            shortcut_by_pair[(card.event, card.variant)]
            for card in final_shortcuts
            if (card.event, card.variant) in shortcut_by_pair
        ]

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
        max_card_recordings=MAX_CARD_RECORDINGS,
        # Settled per viewer in `finalize_watch_cards`; the cached shelf carries a placeholder.
        dropped_duplicate_cards=0,
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
            # The experiment's metrics decide which cards carry a metric label and which events
            # get shortcut cards, its exposure criteria decide who is compared and how someone who
            # saw two variants is split, and the flag's variants decide the arms. All of them are
            # editable while an entry is warm, and none can be re-applied on read, so an edit has
            # to miss the cache rather than be served the answer to the previous configuration.
            experiment.updated_at.isoformat(),
            experiment.feature_flag.updated_at.isoformat() if experiment.feature_flag.updated_at else None,
            # A saved metric is editable without touching the experiment row, and its events decide
            # metric labels and shortcut cards the same way an inline metric's do.
            sorted(updated.isoformat() for updated in experiment.saved_metrics.values_list("updated_at", flat=True)),
            # Property restrictions are compiled into the SQL, so a restriction change has to miss
            # the cache rather than be re-applied on read.
            [
                {
                    "name": restriction.name,
                    "property_type": restriction.property_type,
                    "group_type_index": restriction.group_type_index,
                }
                for restriction in sorted(
                    get_restricted_properties_with_group_type_index_for_team(user=user, team=team),
                    key=lambda restriction: (
                        restriction.name,
                        restriction.property_type,
                        restriction.group_type_index if restriction.group_type_index is not None else -1,
                    ),
                )
            ],
        ]
    )
    digest = hashlib.sha256(spec.encode()).hexdigest()[:16]
    # Keyed by the viewer's restriction profile, not by the viewer: the property restrictions in
    # the digest are the only viewer-dependent input to the scan, and per-recording access is
    # applied on read. One viewer's scan then serves every viewer whose restrictions match, which
    # on the heaviest read in this family is the difference between paying it once per team per
    # TTL and once per viewer.
    return f"experiment_session_event_deltas_v8_{team.pk}_{experiment.pk}_{digest}"


def _metric_event_names(metrics: list[MetricEventSource]) -> set[str]:
    """Every named event this experiment's metrics count.

    Collected for the session-linkability lookup and for labeling the cards these events earn;
    they stay in the comparison itself. Sources with no single event name (actions, all-events
    nodes) are skipped — they can match client-captured events, so their identity can't be decided
    from a name.
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


def _card_kind(
    *, event_name: str, target_count: int, target_persons: int, baseline_count: int, baseline_persons: int
) -> WatchCardKind:
    """Which shelf a comparison card belongs on.

    Friction is decided first and beats everything: an error only the new variant throws is the
    single most useful thing this surface can find, and routing it to the variant's-own-rendering
    shelf on the strength of the same evidence would bury it.

    Everything else turns on how much of the event the other arms are missing rather than on the
    ratio. A ratio alone can't tell "almost nobody else did it" from "nobody else could": both look
    enormous, and the second is the variant rendering something the others never had. Comparing the
    other arms' occurrences against the number this arm's rate predicts for them separates the two,
    and it needs the prediction to be large before an absence means anything at all.
    """
    if event_name in FRICTION_EVENTS:
        return WatchCardKind.FRICTION
    expected_baseline = target_count / target_persons * baseline_persons
    if (
        expected_baseline >= VARIANT_ONLY_MIN_EXPECTED
        and baseline_count <= expected_baseline * VARIANT_ONLY_MAX_LEAKAGE
    ):
        return WatchCardKind.VARIANT_ONLY
    return WatchCardKind.BEHAVIOR


def _pick_behavior_cards(
    scan: SessionEventDeltaScan, *, arm_keys: list[str], metric_names_by_event: dict[str, str]
) -> list[ExperimentWatchCard]:
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
            strength = _strength(separation=separation, baseline_count=rest_count, target_count=counts[key])
            card = ExperimentWatchCard(
                kind=_card_kind(
                    event_name=event_name,
                    target_count=counts[key],
                    target_persons=arm_persons[key],
                    baseline_count=rest_count,
                    baseline_persons=rest_persons,
                ),
                event=event_name,
                variant=key,
                strength=strength,
                metric_name=metric_names_by_event.get(event_name),
                recording_count=0,
                session_ids=[],
                highlights=[],
            )
            if best is None or separation > best[0]:
                best = (separation, card)
        if best is not None:
            picked.append(best)

    picked.sort(key=lambda entry: (-entry[0], entry[1].event))
    # Each shelf gets its own budget. Friction is capped by FRICTION_EVENTS instead, at one card per
    # name, because it is the first thing a reader triages; the variant's-own-rendering shelf is
    # capped low because it always sorts above everything else and is never the reason to open a
    # recording. Sharing one budget would let either of them push the whole behavior shelf out of
    # the response, which is the failure mode both splits exist to prevent.
    by_kind: dict[WatchCardKind, list[ExperimentWatchCard]] = {}
    for _separation_value, card in picked:
        by_kind.setdefault(card.kind, []).append(card)
    return (
        by_kind.get(WatchCardKind.BEHAVIOR, [])[:MAX_BEHAVIOR_CARDS]
        + by_kind.get(WatchCardKind.FRICTION, [])
        + by_kind.get(WatchCardKind.VARIANT_ONLY, [])[:MAX_VARIANT_ONLY_CARDS]
    )


def _shares_recordings(session_ids: set[str], other: set[str]) -> bool:
    """Whether one card's recordings are, near enough, already the other's.

    Measured against the smaller card rather than the union, so a card whose recordings all sit
    inside a longer one counts as a duplicate too.
    """
    return len(session_ids & other) >= min(len(session_ids), len(other)) * DUPLICATE_CARD_OVERLAP


def _drop_duplicate_recording_sets(cards: list[ExperimentWatchCard]) -> list[ExperimentWatchCard]:
    """The shelf with every card that only restates a higher-ranked card's recordings taken out.

    Two events an arm's people do together are ranked as two findings, because the comparison reads
    one event name at a time and both separate the arms. The reader gets one playlist twice, and on
    a redesign experiment, where a whole flow's events move together, that is most of the shelf.

    Compared within a shelf and never across them. An event a variant renders itself always
    co-occurs with the behavior it drives, so cutting the variant's-own-rendering card against the
    behavior card would empty the shelf built to hold it, and a metric shortcut is an offer to
    watch a metric event happen rather than a restatement of the finding it shares recordings with.

    Cards arrive in rank order, so the one kept is the one that earned its place. A dropped card is
    not replaced by the next-ranked candidate: candidates are capped before their recordings are
    resolved, and refilling would cost another round trip to find out whether the replacement can
    be backed by a recording at all.
    """
    kept: list[ExperimentWatchCard] = []
    seen_by_kind: dict[WatchCardKind, list[set[str]]] = {}
    for card in cards:
        session_ids = set(card.session_ids)
        shelf = seen_by_kind.setdefault(card.kind, [])
        if any(_shares_recordings(session_ids, other) for other in shelf):
            continue
        shelf.append(session_ids)
        kept.append(card)
    return kept


def _assign_highlights(cards: list[ExperimentWatchCard]) -> list[ExperimentWatchCard]:
    """Each card cut down to the few recordings it names first, taken from its own ranking.

    The shelf's cards overlap by construction, so a recording an earlier card already names sorts
    last here rather than being dropped: no card is left without highlights, and no reader is sent
    to the same recording from every card on the shelf. Cards arrive in rank order, so the stronger
    card gets first claim on a recording both could name.
    """
    claimed: set[str] = set()
    assigned = []
    for card in cards:
        unclaimed = [highlight for highlight in card.highlights if highlight.session_id not in claimed]
        already = [highlight for highlight in card.highlights if highlight.session_id in claimed]
        highlights = (unclaimed + already)[:MAX_CARD_HIGHLIGHTS]
        claimed.update(highlight.session_id for highlight in highlights)
        assigned.append(replace(card, highlights=highlights))
    return assigned


def _metric_events_by_name(
    metrics: list[MetricEventSource], experiment: Experiment
) -> tuple[list[_MetricEvent], dict[str, list[EventsNode]]]:
    """Every named event the experiment's metrics count, paired with the metric that owns it, in the
    order the experiment's own metrics page lists them.

    That order rather than the order the metrics happen to be stored in: a reader who put the metric
    they care about first sees a shelf built around a different one otherwise, and on a production
    experiment that is exactly what happened — the event the experiment was built to move sat eighth
    in storage order and never reached the shelf.

    Also returns each event's source nodes from the metric that owns it, so the recordings lookup
    can honor that metric's property filters: the card is labeled with the metric's name, and a
    recording of the event happening outside the metric would be mislabeled.
    """
    rank = metric_display_rank(
        [
            *(experiment.primary_metrics_ordered_uuids or []),
            *(experiment.secondary_metrics_ordered_uuids or []),
        ]
    )

    named: list[_MetricEvent] = []
    owner_by_event: dict[str, str] = {}
    nodes_by_event: dict[str, list[EventsNode]] = {}
    for metric in sorted(metrics, key=lambda metric: rank(metric.metric_uuid)):
        for source in metric.sources:
            node = source.node
            if not isinstance(node, EventsNode) or not node.event:
                continue
            if node.event in UNCOMPARABLE_EVENTS:
                continue
            if node.event not in owner_by_event:
                owner_by_event[node.event] = metric.metric_uuid
                nodes_by_event[node.event] = [node]
                named.append(_MetricEvent(event=node.event, metric_name=metric.metric_name))
            elif owner_by_event[node.event] == metric.metric_uuid:
                # Another source of the owning metric on the same event — a funnel can repeat an
                # event across steps with different filters, and any of them counts as the metric.
                nodes_by_event[node.event].append(node)

    return named, nodes_by_event


def _metric_card_candidates(
    named_metric_events: list[_MetricEvent],
    *,
    arm_keys: list[str],
    never_linked: frozenset[str],
    carded_events: set[str],
) -> list[ExperimentWatchCard]:
    """Shortcut cards to recordings around the experiment's own metric events, one per arm.

    No strength and no comparison claim: what happened to the metric is the results tab's answer.
    These cards only say "here is the metric's event happening on screen, in this arm". Events that
    have only ever been captured server-side can't back a recording and are skipped outright.
    """
    kept = [
        named for named in named_metric_events if named.event not in never_linked and named.event not in carded_events
    ][:MAX_METRIC_CARD_EVENTS]
    return [
        ExperimentWatchCard(
            kind=WatchCardKind.METRIC,
            event=named.event,
            variant=arm_key,
            strength=None,
            metric_name=named.metric_name,
            recording_count=0,
            session_ids=[],
            highlights=[],
        )
        for named in kept
        for arm_key in arm_keys
    ]


def _shortcut_nodes(
    metric_cards: list[ExperimentWatchCard], nodes_by_metric_event: dict[str, list[EventsNode]]
) -> dict[str, list[EventsNode]]:
    """The source nodes behind the shortcut cards in `metric_cards`, so the recordings lookup can
    apply their metrics' property filters to those cards only."""
    return {
        card.event: nodes_by_metric_event[card.event] for card in metric_cards if card.event in nodes_by_metric_event
    }


def _resolve_cards(
    setup: _QuerySetup,
    *,
    candidates: list[ExperimentWatchCard],
    metric_nodes: dict[str, list[EventsNode]],
    covered_from: datetime,
) -> list[ExperimentWatchCard]:
    """The candidates that recordings can back, each carrying its recordings and highlights.

    A candidate without a single recording is dropped, not returned greyed-out: the deliverable is
    what can be watched, and replay sampling or retention already ate these sessions.
    """
    if not candidates:
        return []
    recordings = _recordings_for_cards(
        setup,
        wanted=[(candidate.event, candidate.variant) for candidate in candidates],
        covered_from=covered_from,
        metric_nodes=metric_nodes,
    )
    return [
        replace(
            candidate,
            recording_count=len(found.session_ids),
            session_ids=found.session_ids,
            highlights=found.highlights,
        )
        for candidate in candidates
        if (found := recordings.get((candidate.event, candidate.variant))) is not None
    ]


def _recordings_for_cards(
    setup: _QuerySetup,
    *,
    wanted: list[tuple[str, str]],
    covered_from: datetime,
    metric_nodes: Optional[dict[str, list[EventsNode]]] = None,
) -> dict[tuple[str, str], _CardRecordings]:
    """Recent recorded sessions per (event, arm) pair, most recent first, and which of them to open
    first.

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

    def highlight_signal_rows() -> ast.Expr:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=[event for event, _singular in HIGHLIGHT_SIGNALS]),
        )

    def highlight_count(event_name: str) -> ast.Expr:
        return ast.Call(
            name="countIf",
            args=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=event_name),
                )
            ],
        )

    def event_condition(event_name: str) -> ast.Expr:
        # The same per-event terms card_event_match() is assembled from, so a filtered metric
        # event's repetition counts exactly the occurrences that made it into events_present.
        if event_name in filtered_nodes:
            conditions = [build_source_condition(node, setup.team) for node in filtered_nodes[event_name]]
            return ast.Or(exprs=conditions) if len(conditions) > 1 else conditions[0]
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value=event_name)
        )

    # The signal rows join the predicate rather than riding on a second query: they are three event
    # names, so ClickHouse still prunes this on the events table's primary key, and a session that
    # carries only signal rows contributes an empty `events_present` and drops out at the arrayJoin
    # below rather than polluting any card.
    wanted_event_rows = ast.Or(exprs=[card_event_match(), highlight_signal_rows()])
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
            *(
                ast.Alias(alias=_highlight_alias(event), expr=highlight_count(event))
                for event, _singular in HIGHLIGHT_SIGNALS
            ),
            # How often the session fired each wanted event, one aggregated count per event rather
            # than an array of every occurrence: an occurrences array is unbounded on a hot event,
            # while these keep the per-session aggregation state bounded by the distinct wanted
            # names, the same shape the highlight-signal counts use.
            *(
                ast.Alias(alias=_repetition_alias(index), expr=ast.Call(name="countIf", args=[event_condition(event)]))
                for index, event in enumerate(wanted_events)
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
            *(ast.Field(chain=[_highlight_alias(event)]) for event, _singular in HIGHLIGHT_SIGNALS),
            *(ast.Field(chain=[_repetition_alias(index)]) for index in range(len(wanted_events))),
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
    repetition_index = {event: index for index, event in enumerate(wanted_events)}
    signal_base = 3
    repetition_base = signal_base + len(HIGHLIGHT_SIGNALS)
    candidates: dict[tuple[str, str], list[_CandidateRecording]] = {}
    for row in setup.run(candidates_query):
        pair = (str(row[0]), str(row[1]))
        if pair not in wanted_pairs:
            continue
        candidates.setdefault(pair, []).append(
            _CandidateRecording(
                session_id=str(row[2]),
                signals={
                    event: int(row[signal_base + index]) for index, (event, _singular) in enumerate(HIGHLIGHT_SIGNALS)
                },
                repetition=int(row[repetition_base + repetition_index[pair[0]]]),
            )
        )

    all_session_ids = sorted(
        {recording.session_id for pair_recordings in candidates.values() for recording in pair_recordings}
    )
    if not all_session_ids:
        return {}

    # Replay's own existence check rather than a read of the replay summaries here: "a row exists"
    # is not the same question as "this recording can be opened", and only that helper applies the
    # team's retention period and the deleted flag. A card promising a recording that expired or was
    # deleted is the one failure the whole shelf is built to avoid.
    exists_by_id = SessionReplayEvents().batch_exists(all_session_ids, setup.team)
    recorded = {session_id for session_id in all_session_ids if exists_by_id.get(session_id)}

    found = {}
    for pair, pair_recordings in candidates.items():
        kept = [recording for recording in pair_recordings if recording.session_id in recorded][:MAX_CARD_RECORDINGS]
        # A pair without a single playable recording is left out entirely, so any card leaning on
        # it is dropped rather than returned promising zero recordings.
        if not kept:
            continue
        found[pair] = _CardRecordings(
            session_ids=[recording.session_id for recording in kept],
            # Ranked, but not yet cut to the few a card names: which of them this card ends up
            # naming depends on the cards beside it, and which cards those are is settled per
            # viewer.
            highlights=_rank_highlights(
                kept,
                # On a card whose own event is one of the friction signals, the signal count already
                # is the repetition, so counting both would say "2 rage clicks, did this 2 times".
                count_repetition=pair[0] not in FRICTION_EVENTS,
            ),
        )
    return found


def _highlight_alias(event_name: str) -> str:
    """Column alias for one highlight signal's per-session count. Derived from the event name so the
    select list, the outer projection and the row unpacking cannot drift apart."""
    return f"signal_{event_name.lstrip('$')}"


def _repetition_alias(index: int) -> str:
    """Column alias for one wanted event's per-session occurrence count. Derived from the event's
    index in the sorted wanted events so the select list, the outer projection and the row unpacking
    cannot drift apart."""
    return f"repetition_{index}"


def _rank_highlights(
    recordings: list[_CandidateRecording], *, count_repetition: bool
) -> list[ExperimentWatchHighlight]:
    """A card's recordings worth opening first, best first, each with everything it carries.

    Every recording that carries anything, rather than only the few a card shows: which of them
    this card names is decided in `_assign_highlights`, once the shelf beside it is final.

    Ranked on the friction a session shows as a whole rather than by naming the leader of each
    signal in turn. Per-signal leaders describe half of what they point at and hide the sessions
    carrying several kinds of trouble at once: measured on a production-shaped card, the top
    rage-click session also held six errors and the top error session also held four rage clicks,
    while the session sitting just behind on both axes never appeared. That session is the one
    showing a person hitting two problems in a row, which is the case this surface exists to find.

    Kinds before volume for the same reason: a session that rage clicked and then hit an error says
    more about the variant than one that only rage clicked twice as often. Volume then decides the
    ties, but damped, because past a few occurrences a count measures the session's length, and
    ranking on raw totals puts the longest session first on every card it appears on.

    Repeating the card's own event counts as one more kind of signal, from two occurrences up
    since one is what put the session on the card at all, and it outranks friction volume on a tie:
    on a behavior card the recording worth opening first is the one where the difference the card
    claims is most on screen, not the one carrying the most of something every card shows.
    `count_repetition` is False when the card's own event is a friction signal, whose count already
    says the same thing.
    """
    scored: list[tuple[int, int, int, str, str]] = []
    for recording in recordings:
        present = [
            (recording.signals[event], singular)
            for event, singular in HIGHLIGHT_SIGNALS
            if recording.signals[event] > 0
        ]
        # A broken session tops every card it backs: damping caps what its counts are worth, but it
        # still wins ties on carrying every kind of signal, so it is kept off the highlights
        # entirely rather than merely held back. A rage click vouches for the session: loops don't
        # rage click, and a person grinding through this much friction is worth featuring.
        if recording.signals["$rageclick"] == 0 and any(
            count >= MAX_HIGHLIGHT_SIGNAL_COUNT for count, _singular in present
        ):
            continue
        # Every signal the session carries, in the shelf's own priority order rather than by size,
        # so two recordings' reasons stay comparable at a glance.
        phrases = [pluralize(count, singular) for count, singular in present]
        repetition = recording.repetition if count_repetition else 0
        if repetition > 1:
            phrases.append(f"did this {repetition} times")
        if not phrases:
            continue
        kinds = len(present) + (1 if repetition > 1 else 0)
        damped_repetition = min(repetition, HIGHLIGHT_COUNT_DAMPING) if repetition > 1 else 0
        damped_signals = sum(min(count, HIGHLIGHT_COUNT_DAMPING) for count, _singular in present)
        scored.append((kinds, damped_repetition, damped_signals, recording.session_id, ", ".join(phrases)))
    # Ties broken on the session id rather than left to dict order, so the same shelf computed
    # twice names the same recordings.
    scored.sort(key=lambda entry: (-entry[0], -entry[1], -entry[2], entry[3]))
    return [
        ExperimentWatchHighlight(session_id=session_id, reason=reason)
        for _kinds, _repetition, _signals, session_id, reason in scored
    ]
