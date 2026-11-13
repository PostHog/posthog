"""Serializers for the session recording features: session context, session buckets and session event deltas."""

from rest_framework import serializers

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.metric_events import MetricSourceRole
from products.experiments.backend.session_buckets import (
    MAX_BUCKET_SCAN_DAYS,
    MAX_SESSION_BUCKET_LIMIT,
    ExperimentSessionBucket,
)
from products.experiments.backend.session_context import MAX_SESSION_CONTEXT_BATCH
from products.experiments.backend.session_event_deltas import (
    FIRST_SESSION_HORIZON_HOURS,
    MAX_CARD_HIGHLIGHTS,
    MAX_CARD_RECORDINGS,
    MAX_DELTA_SCAN_DAYS,
    ExperimentWatchCardKind,
    ExperimentWatchCardStrength,
    ExperimentWatchEmptyReason,
)


class ExperimentSessionMetricSourceHitSerializer(serializers.Serializer):
    """One event/action source of a metric with at least one matching event in a session recording."""

    source_role = serializers.ChoiceField(
        source="role",
        choices=[role.value for role in MetricSourceRole],
        help_text=(
            "What this source means to its metric: 'source' (a mean metric's single event), 'step' (a funnel "
            "step, numbered by source_index), 'numerator'/'denominator' (a ratio metric's two sides), or "
            "'retention_start'/'retention_completion' (a retention metric's start event and return visit). "
            "A hit on one source is not a hit on the metric as the analysis counts it."
        ),
    )
    source_name = serializers.CharField(source="name", help_text="Display name of the source event or action.")
    source_index = serializers.IntegerField(
        source="index",
        help_text=(
            "0-based position of this source among all the metric's sources, data-warehouse ones included — so a "
            "funnel step keeps its real step number even when an earlier step has no session events."
        ),
    )
    source_total = serializers.IntegerField(
        source="total", help_text="Total number of sources the metric is defined over."
    )
    event_count = serializers.IntegerField(help_text="Number of events in the session matching this source.")
    first_timestamp = serializers.DateTimeField(
        help_text="Timestamp of the first event in the session matching this source."
    )
    timestamps = serializers.ListField(
        child=serializers.DateTimeField(),
        help_text=(
            "Ascending timestamps of this source's matching events in the session, capped at the first 50. "
            "event_count is the true total, so this list may be shorter — treat these as seek points, not a count."
        ),
    )


class ExperimentSessionMetricHitSerializer(serializers.Serializer):
    """One experiment metric with at least one matching event in a session recording."""

    metric_uuid = serializers.CharField(
        help_text="UUID of the experiment metric (inline primary/secondary or saved) whose events fired."
    )
    metric_name = serializers.CharField(
        help_text="Display name of the metric, or an event-derived title (matching the experiment UI) when unnamed."
    )
    event_count = serializers.IntegerField(
        help_text="Total number of events in the session matching any of the metric's event/action sources."
    )
    first_timestamp = serializers.DateTimeField(
        help_text="Timestamp of the first event in the session matching the metric."
    )
    timestamps = serializers.ListField(
        child=serializers.DateTimeField(),
        help_text=(
            "Ascending timestamps of the metric's matching events in the session, capped at the first 50. "
            "event_count is the true total, so this list may be shorter — treat these as seek points, not a count."
        ),
    )
    sources = ExperimentSessionMetricSourceHitSerializer(
        many=True,
        help_text=(
            "Which of the metric's sources fired, so a hit reads as 'step 2 of 3' or 'the start event of a "
            "retention metric' rather than an unqualified 'this metric happened'. Sources with no matching event "
            "are omitted, as is the whole breakdown for metrics beyond the scan's aggregate ceiling. A retention "
            "metric whose start and completion are the same event contributes only the start source: the "
            "completion would match the identical events and render a duplicate."
        ),
    )


class ExperimentSessionContextItemSerializer(serializers.Serializer):
    """One experiment whose feature flag a session recording saw."""

    experiment_id = serializers.IntegerField(help_text="ID of the experiment whose feature flag the session saw.")
    experiment_name = serializers.CharField(help_text="Name of the experiment.")
    flag_key = serializers.CharField(help_text="Key of the experiment's feature flag.")
    variant = serializers.CharField(
        help_text=(
            "Variant the session saw. Taken from the earliest event matching the experiment's exposure criteria "
            "when one exists, otherwise from the earliest flag evaluation in the session, otherwise from the "
            "$feature/<key> property stamped on the session's events."
        )
    )
    variants_seen = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "All distinct variant values observed for this flag during the session, sorted alphabetically. "
            "Only the flag's defined variant keys count; non-enrollment responses (false) are ignored. "
            "More than one value means the session saw multiple variants — a signal of multi-exposure bias."
        ),
    )
    multiple_variants = serializers.BooleanField(
        help_text="True when the session saw more than one variant of this flag."
    )
    first_exposure_timestamp = serializers.DateTimeField(
        allow_null=True,
        help_text=(
            "Timestamp of the first event in the session matching the experiment's exposure criteria — "
            "the default exposure event ($feature_flag_called), or the configured custom event/action. Null when "
            "no event in the session matched the criteria; the variant is then known from flag evaluations or "
            "stamped $feature/<key> properties. "
            "Session-scoped: the experiment analysis counts exposure per person across the whole run window, "
            "so the person's counted first exposure may lie in an earlier session."
        ),
    )
    experiment_start_date = serializers.DateTimeField(allow_null=True, help_text="When the experiment was launched.")
    experiment_end_date = serializers.DateTimeField(
        allow_null=True, help_text="When the experiment ended. Null while the experiment is still running."
    )
    metrics_in_session = ExperimentSessionMetricHitSerializer(
        many=True,
        help_text=(
            "This experiment's metrics with at least one matching event in the session, sorted by first "
            "occurrence. Empty when none of the experiment's metric events fired during the session."
        ),
    )


class ExperimentSessionContextResponseSerializer(serializers.Serializer):
    """Experiment/variant context for a session recording."""

    session_id = serializers.CharField(help_text="ID of the session recording the context was resolved for.")
    results = ExperimentSessionContextItemSerializer(
        many=True,
        help_text=(
            "Experiments (and variants) the session saw, sorted by experiment name. Empty when no launched "
            "experiment's run window overlaps the recording or no flag data was observed in the session."
        ),
    )


class ExperimentSessionContextsRequestSerializer(serializers.Serializer):
    """Request body for the batch session-context endpoint."""

    session_ids = serializers.ListField(
        child=serializers.CharField(allow_blank=False, help_text="ID of one session recording."),
        min_length=1,
        max_length=MAX_SESSION_CONTEXT_BATCH,
        help_text=(
            f"IDs of the session recordings to resolve experiment context for, at most "
            f"{MAX_SESSION_CONTEXT_BATCH} per request. Duplicates are ignored."
        ),
    )


class ExperimentSessionContextsResponseSerializer(serializers.Serializer):
    """Experiment/variant context for a batch of session recordings."""

    results = ExperimentSessionContextResponseSerializer(
        many=True,
        help_text=(
            "Per-session experiment context, in the order the session IDs were requested. Sessions whose "
            "recording metadata doesn't exist yet (still ingesting, or unknown to this project) are omitted, "
            "as are recordings you don't have access to and sessions beyond the batch's recording-day budget "
            "(only the most recent days are computed). Fetch omitted sessions individually via the "
            "single-session endpoint."
        ),
    )


class ExperimentInSessionExposureSerializer(serializers.Serializer):
    """How the recordings tab's in-session exposure scope reads on this experiment."""

    available = serializers.BooleanField(
        help_text=(
            "Whether the in-session exposure scope can answer for this experiment. Mirrors the recordings "
            "query, which refuses `experiment_exposure.in_session` exactly when this is false."
        )
    )
    unavailable_reason = serializers.CharField(
        allow_null=True,
        help_text=(
            "Why the in-session scope can't answer for this experiment, worded for display next to the "
            "disabled option. Null when available."
        ),
    )
    uses_stamped_fallback = serializers.BooleanField(
        help_text=(
            "True when in-session evidence is the stamped `$feature/<flag_key>` property, which means the "
            "flag was active in the session, rather than the exposure event itself being captured there. "
            "Copy must not claim the exposure was captured in the session when this is set."
        )
    )


class ExperimentSessionBucketRequestSerializer(serializers.Serializer):
    """Request body for the session-bucket endpoint."""

    bucket = serializers.ChoiceField(
        choices=ExperimentSessionBucket.choices,
        help_text=(
            "Which question the returned session set answers. 'fired_any': the session fired at least one event "
            "of any listed metric (an OR the recordings query itself can't express). 'no_metric_activity': the "
            "session fired none of them. 'funnel_dropoff': the session saw an exposure event but never fired the "
            "funnel metric's last step; the exposure is the funnel's implicit first step, the same as in the "
            "experiment analysis. All three are session-scoped and goal-free: they say what happened in the "
            "session, not whether it helped or hurt the metric."
        ),
    )
    metric_uuids = serializers.ListField(
        child=serializers.CharField(allow_blank=False, help_text="UUID of one of the experiment's metrics."),
        required=False,
        default=list,
        help_text=(
            "Metrics the bucket is computed over. Exactly one funnel metric for 'funnel_dropoff'. Omit for the "
            "other buckets to use every metric of the experiment that can be matched to recordings."
        ),
    )
    variant = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "Restrict to sessions that saw this variant. Omit for every variant. A session that saw more than "
            "one variant matches each variant it saw."
        ),
    )
    limit = serializers.IntegerField(
        required=False,
        default=MAX_SESSION_BUCKET_LIMIT,
        min_value=1,
        max_value=MAX_SESSION_BUCKET_LIMIT,
        help_text=(
            f"Maximum session IDs to return, at most {MAX_SESSION_BUCKET_LIMIT}. The most recently active "
            "matching sessions win."
        ),
    )

    def validate(self, attrs: dict) -> dict:
        if attrs["bucket"] == ExperimentSessionBucket.FUNNEL_DROPOFF and len(attrs.get("metric_uuids") or []) != 1:
            raise serializers.ValidationError(
                {"metric_uuids": ["The drop-off bucket takes exactly one funnel metric."]}
            )
        return attrs


class ExperimentSessionBucketMetricSerializer(serializers.Serializer):
    """One metric the bucket was computed over."""

    metric_uuid = serializers.CharField(help_text="UUID of the experiment metric.")
    metric_name = serializers.CharField(
        help_text="Display name of the metric, or an event-derived title (matching the experiment UI) when unnamed."
    )


class ExperimentSessionBucketExcludedMetricSerializer(serializers.Serializer):
    """One requested metric the bucket could not be computed over."""

    metric_uuid = serializers.CharField(help_text="UUID of the experiment metric.")
    metric_name = serializers.CharField(help_text="Display name of the metric.")
    reason = serializers.CharField(
        help_text=(
            "Why the metric can't be matched to recordings: a data-warehouse-only source, a retention window, "
            "or events only ever captured server-side."
        )
    )


class ExperimentSessionBucketResponseSerializer(serializers.Serializer):
    """Session recordings of an experiment matching a bucket."""

    session_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "IDs of matching sessions that have a recording, most recently active first. Feed these to a "
            "recordings query as session_ids; they are a subset of the experiment's exposed sessions, so the "
            "exposure filter can stay in place alongside them."
        ),
    )
    truncated = serializers.BooleanField(
        help_text="True when more sessions matched than the limit returned. Older matches were dropped first."
    )
    considered_metrics = ExperimentSessionBucketMetricSerializer(
        many=True,
        help_text=(
            "The metrics the bucket was actually computed over. Load-bearing for 'no_metric_activity': "
            "'fired nothing' only means something next to the list of metrics it was evaluated against."
        ),
    )
    excluded_metrics = ExperimentSessionBucketExcludedMetricSerializer(
        many=True,
        help_text=(
            "Requested metrics left out of the bucket because they can never match a recording, with the reason. "
            "They are reported rather than silently producing an empty result."
        ),
    )
    date_from = serializers.DateTimeField(
        help_text=(
            f"Start of the window scanned, never before the experiment started. At most {MAX_BUCKET_SCAN_DAYS} days "
            "before date_to when the scan found an exposure to anchor on. When it found none, how far back the "
            "search for one reached, which the project's recording retention bounds. Matches outside the window "
            "are not returned."
        )
    )
    date_to = serializers.DateTimeField(
        help_text=(
            "End of the window scanned: 24 hours after the latest exposure captured in a session, capped at the "
            "experiment's end date or now. The pad covers the metric events a session fires after its exposure. "
            "The scan ends at the experiment's end date, or now while it runs, when that exposure can't be "
            "located, so an experiment whose exposures stopped long ago is still scanned where its sessions are."
        )
    )
    filter_test_accounts = serializers.BooleanField(
        help_text=(
            "Whether the project's test-account filters were applied, following the experiment's exposure "
            "criteria, the same rule the experiment's recordings list uses."
        )
    )
    used_exposure_fallback = serializers.BooleanField(
        help_text=(
            "True when the exposed population was matched on the stamped $feature/<flag key> event property "
            "instead of the exposure event, because the default exposure event has only ever been captured "
            "server-side and can never match a session. The sessions then mean 'the flag was active in this "
            "session', not 'the exposure moment was captured'. The variant comes from the flag's value on each "
            "event, so a returning user can appear under a variant they were re-bucketed into later."
        )
    )


class ExperimentSessionEventDeltaRequestSerializer(serializers.Serializer):
    """The watch cards endpoint takes no parameters: the shelf is computed per experiment, every
    variant at once."""


class ExperimentWatchHighlightSerializer(serializers.Serializer):
    """One recording a card names first, and the phrase that says why."""

    session_id = serializers.CharField(help_text="The recording to open. Always one of the card's own session_ids.")
    reason = serializers.CharField(
        help_text=(
            "Everything this recording carries that earned it the place, ready to render as-is, for example "
            "'6 rage clicks, 6 errors' or '1 error, did this 4 times'. Every signal the session shows is "
            "listed, so the phrase is the whole picture rather than the single strongest part of it. Friction "
            "counts run from the moment the person was exposed to the end of the session, so friction before "
            "they met the variant is left out; 'did this N times' counts the card's own event. Not a comparison "
            "and not a reason the card exists."
        )
    )


class ExperimentWatchCardSerializer(serializers.Serializer):
    """One group of recordings worth opening, and the sentence that justifies it.

    Deliberately no rate, no ratio and no person count: a precise number next to an event name is
    an effect size, and the experiment's results publish those for everything it measures, computed
    over a different window and a different unit. The only number here is how many recordings the
    card can actually show.
    """

    kind = serializers.ChoiceField(
        choices=ExperimentWatchCardKind.choices,
        help_text=(
            "What the card is: 'behavior' for an event this variant did clearly more than the other variants "
            "together, 'friction' for the same finding on an error or rage signal, 'variant_only' for an event "
            "no other variant fired at all, and 'metric' for a shortcut to recordings around one of the "
            "experiment's own metric events. A 'variant_only' card shows the variant rendering its own change "
            "rather than a behavior difference, so present it as confirmation the change is live and never as a "
            "finding. Metric cards claim nothing about how the metric moved: that is the experiment results' "
            "answer."
        ),
    )
    event = serializers.CharField(help_text="The event behind the card.")
    variant = serializers.CharField(
        help_text="The variant whose recordings these are: for comparison cards, the one that did the event more."
    )
    strength = serializers.ChoiceField(
        choices=ExperimentWatchCardStrength.choices,
        allow_null=True,
        help_text=(
            "How far apart this variant and the rest are, as a band rather than a number: 'only' when nobody in "
            "the other variants did it at all among the people compared, then 'far_more', 'more' and "
            "'slightly_more'. Read off the conservative end of the difference, so a card that clears the bar "
            "only because the sample is large reports as slight. Null on metric cards, which compare nothing. "
            "Present a band as a comparison ('far more common in test'), never convert it into a multiple."
        ),
    )
    metric_name = serializers.CharField(
        allow_null=True,
        help_text=(
            "The metric this card's event belongs to, on a comparison card as well as on a shortcut card. When "
            "set, the experiment's results measure this event over the whole run window with the statistics "
            "that go with a result, so say the card points there and never present the card as a second answer "
            "about that metric. Null when no metric counts the event."
        ),
    )
    recording_count = serializers.IntegerField(
        help_text=(
            f"How many recordings the card carries, at most max_card_recordings ({MAX_CARD_RECORDINGS}). Every "
            "card is backed by recordings that actually exist: a finding whose sessions were never recorded is "
            "dropped rather than promised. A count sitting on the ceiling means at least that many, so say 'at "
            "least' and never compare two such counts: how often the event happened is the experiment's results, "
            "and this only counts what replay kept."
        )
    )
    session_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="The recordings themselves, most recent first, ready to hand to the recordings list as-is.",
    )
    highlights = ExperimentWatchHighlightSerializer(
        many=True,
        help_text=(
            f"Which of the card's recordings to open first, at most {MAX_CARD_HIGHLIGHTS}, ranked by how much "
            "each one carries: recordings showing several kinds of signal at once come before recordings "
            "showing more of a single kind. Offer these before the full list: the recordings list orders "
            "by its own sort, so session_ids order never reaches the viewer, and twenty recordings that share "
            "an event are otherwise indistinguishable in it. Empty when no recording the viewer can open "
            "carries a signal, which is worth saying rather than hiding."
        ),
    )


class ExperimentWatchVariantSerializer(serializers.Serializer):
    """One variant's compared population."""

    key = serializers.CharField(help_text="The variant key.")
    persons = serializers.IntegerField(
        help_text=(
            "Exposed people the comparison read for this variant: the most recently exposed people, each "
            "read from their first session after being exposed. Someone selected who had no session in that "
            "horizon is not counted here, so this sits at or below the variant's enrollment between date_from "
            "and date_to. People rather than sessions because a variant can change how often the flag is "
            "evaluated again later, which moves a variant's session count without anyone behaving differently. "
            "One session each, from the moment of exposure on, so every variant gets the same amount of "
            "behavior per person."
        )
    )
    sessions = serializers.IntegerField(
        help_text=(
            f"Sessions those people had within {FIRST_SESSION_HORIZON_HOURS} hours of being exposed, and before "
            "the experiment ended or this request was made, which is more than the comparison reads: it says how "
            "much recorded material sits behind the variant."
        )
    )


class ExperimentSessionEventDeltaResponseSerializer(serializers.Serializer):
    """The recordings worth watching for this experiment, grouped into cards.

    Descriptive, never a result: cards say where behavior visibly differed and hand over the
    recordings, while the experiment's results measure its metrics over the whole run window and
    state the magnitudes. Nothing here says a variant is winning.
    """

    cards = ExperimentWatchCardSerializer(
        many=True,
        help_text=(
            "The shelf, strongest comparison first, then the variant's own rendering, then metric shortcuts. "
            "Events the variants can't be told apart on get no card at all rather than a weak one, so an empty "
            "shelf means no difference was big enough to be sure of, not that nothing was measured. Empty also "
            "takes the metric shortcuts with it: a shelf of shortcuts and no finding restates what the "
            "experiment's results already answer while reading as a finding, so it is withheld. Read "
            "empty_reason and say what it reports instead of presenting an empty shelf. Group by kind before "
            "presenting: a 'variant_only' card outranks every real difference by construction, and reading the "
            "shelf in order would report it as the headline."
        ),
    )
    variants = ExperimentWatchVariantSerializer(
        many=True,
        help_text=(
            "Every variant the analysis compares, with its population, in the flag's variant order. "
            "A variant the experiment excludes never appears here, because the analysis does not count it "
            "either, so read a missing key as excluded rather than as zero people."
        ),
    )
    multiple_variant_persons = serializers.IntegerField(
        help_text=(
            "People who saw more than one variant and were left out of every card. Always 0 when the experiment "
            "attributes such users to the variant they saw first."
        )
    )
    multiple_variant_handling = serializers.ChoiceField(
        choices=[handling.value for handling in MultipleVariantHandling],
        help_text=(
            "How the experiment handles someone who saw more than one variant, followed here so the cards split "
            "their people the same way the analysis does."
        ),
    )
    metric_events = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "The events the experiment's own metrics count. A card on one of these carries metric_name and must "
            "be read as pointing at the experiment's results, which measure the same event over the whole run "
            "window with the statistics that go with a result. Cards state no magnitude for exactly this "
            "reason, so never turn one into a claim about how the metric moved."
        ),
    )
    date_from = serializers.DateTimeField(
        help_text=(
            "When the earliest compared person was first exposed. The comparison takes the most recently "
            "exposed people, newest first, until it has as many as one comparison covers or their first "
            f"sessions span {MAX_DELTA_SCAN_DAYS} days of events, so on a busy experiment this is hours rather "
            "than days before date_to, and on an experiment that stopped enrolling it can be long before the "
            "experiment's end. Display this, not the experiment's own dates. Equal to date_to when nobody has "
            "been exposed yet."
        )
    )
    date_to = serializers.DateTimeField(
        help_text=(
            "One minute past the newest compared person's first exposure. Nobody first exposed between "
            "date_from and date_to was passed over, so the pair is a stretch of enrollment rather than a hull "
            "around scattered people. It bounds who was selected, not who was read: variants[].persons counts "
            "only those who then had a session. While an experiment runs this sits about an hour before now, "
            "because the newest hour of enrollment is held back until those people's first sessions have "
            "finished rather than read half-way through. Sessions reach past it, up to "
            f"{FIRST_SESSION_HORIZON_HOURS} hours after each person's own exposure, so this is not the end of "
            "the events that were read."
        )
    )
    filter_test_accounts = serializers.BooleanField(
        help_text=(
            "Whether the project's test-account filters were applied, following the experiment's exposure "
            "criteria, the same rule the experiment's recordings list uses."
        )
    )
    used_exposure_fallback = serializers.BooleanField(
        help_text=(
            "Always false. The compared population is the exposed population the experiment's results count, "
            "matched to sessions by person, so no stamped-property fallback exists any more. The field stays "
            "for compatibility with existing readers."
        )
    )
    sessions_truncated = serializers.BooleanField(
        help_text=(
            "True when more people were exposed than one comparison covers, so the most recently exposed were "
            "used and people exposed before date_from were left out. Every variant is still covered over the "
            "same stretch of enrollment. Named for the session ceiling it used to report; the name is kept for "
            "existing readers."
        )
    )
    events_truncated = serializers.BooleanField(
        help_text=(
            "True when the project has more distinct event names in the window than one comparison can rank, so "
            "some were never considered."
        )
    )
    min_variant_persons = serializers.IntegerField(
        help_text=(
            "How many exposed people a variant needs before it can be compared at all. Below it a variant's "
            "cards would be noise whatever the evidence bar allows."
        )
    )
    max_card_recordings = serializers.IntegerField(
        help_text=(
            "The most recordings one card can carry. A card whose recording_count equals this hit the ceiling, "
            "so report it as 'at least this many' rather than as a count."
        )
    )
    dropped_duplicate_cards = serializers.IntegerField(
        help_text=(
            "How many cards were removed because their recordings were already another card's on the same "
            "shelf. Nothing was lost: the recordings are all reachable through the cards that stayed."
        )
    )
    too_early = serializers.BooleanField(
        help_text=(
            "True when fewer than two variants have min_variant_persons exposed people, so no comparison exists and "
            "cards is empty. Show the variants' counts alongside it: an empty shelf presented without them would "
            "read as 'the variants behaved identically'. Read empty_reason and sessions_truncated before telling "
            "anyone to check back: this is also true when the variants are empty because the people exposed have "
            "no sessions we can see, which empty_reason reports as 'no_session_linked_exposures' and which more "
            "time fixes only while those people were exposed less than a day ago. And when sessions_truncated is "
            "true, only people exposed between date_from and date_to were compared, so more time helps only if "
            "more people are exposed within a stretch that long."
        )
    )
    empty_reason = serializers.ChoiceField(
        choices=ExperimentWatchEmptyReason.choices,
        allow_null=True,
        help_text=(
            "Why cards is empty, and null whenever cards is not empty. Report which of the four happened "
            "rather than reporting an empty shelf, because they ask different things of the reader. "
            "'too_early': fewer than two variants have min_variant_persons exposed people, so nothing was compared "
            "yet. The answer can still change unless sessions_truncated is true, in which case only the people "
            "exposed between date_from and date_to were compared and more time helps only if more people are "
            "exposed within a stretch that long; a rollout split that changed during the run lands here too, "
            "and the experiment's exposure chart is where that shows. "
            "'no_separation': the variants were compared and no event told them apart, which is a result rather "
            "than a failure. 'no_recordings': events did tell the variants apart, but no recording behind them can "
            "be opened, so the project's session replay sampling and retention are what decide whether this "
            "surface can ever show anything. 'no_session_linked_exposures': the people exposed between date_from "
            "and date_to had no session we can see since being exposed, looking up to "
            f"{FIRST_SESSION_HORIZON_HOURS} hours after each exposure, so there was nothing to compare. Two things "
            "reach this state, and they ask for different answers: no browser or mobile SDK is capturing events, "
            "because sessions exist nowhere else, or the exposed people have not come back. While the experiment "
            "runs the read stops at the time of the request, so people exposed less than a day ago are judged on "
            "less than a day and can still return. Check which one before telling anyone to check back, because "
            "more exposures captured the same way yield more of the same. Never fill an empty shelf with the "
            "experiment's metrics: shortcut cards to those metrics' events are withheld here for exactly that "
            "reason."
        ),
    )
