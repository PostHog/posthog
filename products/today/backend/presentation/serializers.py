"""DRF serializers for today. Response shapes come from the facade contracts."""

from typing import Any

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    CodeFile,
    FigureMark,
    FigureQuote,
    HighlightItem,
    HighlightMetric,
    HighlightMover,
    HighlightPin,
    Highlights,
    HighlightValueFormat,
    ImpactNumber,
    ImpactWorking,
    KeyClause,
    PageLink,
    PreviewLine,
    PullRequestLink,
    PulsePin,
    PulsePins,
    RecordingTarget,
    ReportKeyClauses,
    ReportPage,
    SignalPreview,
    SignalView,
)
from ..facade.enums import (
    CitedSource,
    FigureSourceKind,
    FigureText,
    HighlightInterval,
    HighlightLabel,
    HighlightMetricReason,
    HighlightPinStatus,
    HighlightPriority,
    HighlightsStatus,
    HighlightUnit,
    ImpactNumberKey,
    KeyClauseRole,
)


class ExcerptChoiceRequestSerializer(serializers.Serializer):
    finding = serializers.CharField(max_length=6000, help_text="The finding the code excerpts should show.")
    excerpts = serializers.ListField(
        child=serializers.CharField(max_length=2000),
        min_length=2,
        max_length=5,
        help_text="Candidate code excerpts, best scored first.",
    )


class ExcerptChoiceSerializer(serializers.Serializer):
    index = serializers.IntegerField(
        allow_null=True, help_text="The excerpt that shows what the finding describes, or null when unsure."
    )


class PullRequestLinkSerializer(DataclassSerializer):
    url = serializers.CharField(help_text="The pull request on GitHub.")
    number = serializers.IntegerField(help_text="The pull request number.")

    class Meta:
        dataclass = PullRequestLink


class CodeFileSerializer(DataclassSerializer):
    repo = serializers.CharField(help_text="The repository as owner/name.")
    path = serializers.CharField(help_text="The file path in the repository.")

    class Meta:
        dataclass = CodeFile


class PreviewLineSerializer(DataclassSerializer):
    text = serializers.CharField(help_text="One line of the preview block.")
    quiet = serializers.BooleanField(help_text="Whether the line is secondary, such as a stack frame.")

    class Meta:
        dataclass = PreviewLine


class PageLinkSerializer(DataclassSerializer):
    url = serializers.CharField(help_text="Where the link goes, outside PostHog.")
    text = serializers.CharField(help_text="The link text.")

    class Meta:
        dataclass = PageLink


class SignalPreviewSerializer(DataclassSerializer):
    hint = serializers.CharField(help_text="What expanding the signal shows, such as 'Show the stack trace'.")
    code = CodeFileSerializer(many=True, help_text="Repository files to quote, the finding's own file first.")
    block = PreviewLineSerializer(many=True, help_text="A preformatted block, such as a stack trace or a query.")
    text = serializers.CharField(help_text="The finding's text beyond its first sentence.")
    facts = serializers.ListField(child=serializers.CharField(), help_text="Short facts about the source.")
    link = PageLinkSerializer(allow_null=True, help_text="A link that replaces the signal's own destination.")
    link_label = serializers.CharField(
        allow_null=True, help_text="A label that replaces the label of the signal's own destination."
    )

    class Meta:
        dataclass = SignalPreview


class RecordingTargetSerializer(DataclassSerializer):
    session_id = serializers.CharField(help_text="The recording's session id.")
    start_at = serializers.DateTimeField(
        allow_null=True, help_text="Where the player starts, a few seconds before the finding."
    )
    offset = serializers.CharField(allow_null=True, help_text="The finding's time in the recording, as MM:SS.")
    seek_seconds = serializers.IntegerField(
        allow_null=True,
        help_text="Where the player starts, in seconds from the recording start. Null without an offset.",
    )

    class Meta:
        dataclass = RecordingTarget


class SignalViewSerializer(DataclassSerializer):
    signal_id = serializers.CharField(help_text="The signal's id.")
    source_product = serializers.CharField(help_text="The product that emitted the signal.")
    source_type = serializers.CharField(help_text="The kind of signal within its product.")
    source_id = serializers.CharField(help_text="The id of the source object, such as an issue or a ticket.")
    content = serializers.CharField(help_text="The signal's text as emitted.")
    timestamp = serializers.DateTimeField(help_text="When the signal happened.")
    extra = serializers.DictField(
        child=serializers.JSONField(),
        help_text="The emitter's extra fields as it sent them, used to link to the source object. Values are any JSON.",
    )
    headline = serializers.CharField(help_text="The signal as one short line.")
    lead = serializers.CharField(help_text="The signal's first sentence.")
    meta = serializers.CharField(help_text="Identifiers such as a pull request or ticket number, joined by dots.")
    cited = serializers.ChoiceField(
        choices=CitedSource.choices, allow_null=True, help_text="What a scout finding cites: code or a Slack thread."
    )
    recording = RecordingTargetSerializer(allow_null=True, help_text="The recording the signal plays, if any.")
    link = PageLinkSerializer(allow_null=True, help_text="Where a scout finding links outside PostHog, if anywhere.")
    preview = SignalPreviewSerializer(allow_null=True, help_text="What expanding the signal shows, if anything.")

    class Meta:
        dataclass = SignalView


class ImpactWorkingSerializer(DataclassSerializer):
    expression = serializers.CharField(help_text="How the number is worked out, such as '120 ms × 30,000 calls'.")
    result = serializers.CharField(help_text="What the working comes to, such as '1.00 hours a day'.")

    class Meta:
        dataclass = ImpactWorking


class ImpactNumberSerializer(DataclassSerializer):
    key = serializers.ChoiceField(
        choices=ImpactNumberKey.choices,
        help_text="Which number this is: distinct support tickets or database hours a day.",
    )
    value = serializers.CharField(help_text="The number as shown, such as '2' or '1 hour'.")
    sentence = serializers.CharField(help_text="The sentence that follows the number.")
    signal = SignalViewSerializer(allow_null=True, help_text="The signal the number comes from, if one does.")
    values = serializers.ListField(
        child=serializers.CharField(), help_text="The figures in the signal's headline to mark."
    )
    working = ImpactWorkingSerializer(allow_null=True, help_text="How the number is worked out, if it is.")

    class Meta:
        dataclass = ImpactNumber


class ReportPageSerializer(DataclassSerializer):
    lead = serializers.CharField(help_text="The summary's opening paragraph, as markdown.")
    proposal = serializers.CharField(
        help_text="The proposed fix cut to whole sentences, as markdown. Empty when the report proposes none."
    )
    impact_sentence = serializers.CharField(
        help_text="The impact section cut to whole sentences, as markdown, when it states a measurement. Empty otherwise."
    )
    named_pull_request = PullRequestLinkSerializer(
        allow_null=True,
        help_text="The pull request the proposal names, or else the summary, when it names exactly one.",
    )
    solution_names_pull_request = serializers.BooleanField(help_text="Whether the proposal names any pull request.")
    evidence = SignalViewSerializer(
        many=True, help_text="The signals to show as evidence, at most 3, newest first, one per source first."
    )
    source_count = serializers.IntegerField(
        help_text="How many distinct source objects the report's newest 100 signals come from. The impact numbers and last seen use the same signals."
    )
    impact_numbers = ImpactNumberSerializer(
        many=True, help_text="Numbers the signals size the problem with, such as distinct support tickets."
    )
    last_seen = serializers.DateTimeField(
        allow_null=True, help_text="When the newest session, ticket or alert behind the report happened."
    )

    class Meta:
        dataclass = ReportPage


class KeyClausesQuerySerializer(serializers.Serializer):
    include_impact = serializers.BooleanField(
        default=True,
        help_text="Whether to mark the impact sentence. Pass false when the page shows an impact number instead.",
    )


class KeyClauseSerializer(DataclassSerializer):
    start = serializers.IntegerField(help_text="Where the clause starts in its text, as the reader sees it.")
    end = serializers.IntegerField(help_text="Where the clause ends in its text.")
    role = serializers.ChoiceField(choices=KeyClauseRole.choices, help_text="What the clause tells the reader.")
    expansion = serializers.ListField(
        child=serializers.CharField(), help_text="Sentences from the report that explain the clause further."
    )

    class Meta:
        dataclass = KeyClause


class ReportKeyClausesSerializer(DataclassSerializer):
    lead = KeyClauseSerializer(many=True, help_text="The clauses that state the problem or its cause in the lead.")
    impact = KeyClauseSerializer(
        many=True, help_text="The clauses that state the problem or its cause in the impact sentence."
    )
    proposal = KeyClauseSerializer(many=True, help_text="The clause that states the fix in the proposal.")

    class Meta:
        dataclass = ReportKeyClauses


class FigureQuoteSerializer(DataclassSerializer):
    kind = serializers.ChoiceField(
        choices=FigureSourceKind.choices, help_text="Where the number comes from: a signal or the agent's research."
    )
    signal = SignalViewSerializer(
        allow_null=True, help_text="The signal that states the number. Null when the agent's research states it."
    )
    at = serializers.DateTimeField(help_text="When the source was written.")
    sentence = serializers.CharField(help_text="The source sentence that states the number.")
    start = serializers.IntegerField(help_text="Where the number starts in the sentence.")
    end = serializers.IntegerField(help_text="Where the number ends in the sentence.")

    class Meta:
        dataclass = FigureQuote


class FigureMarkSerializer(DataclassSerializer):
    text = serializers.ChoiceField(
        choices=FigureText.choices, help_text="The page text the number is in: the lead or the impact sentence."
    )
    start = serializers.IntegerField(help_text="Where the number starts in that text, as the reader sees it.")
    end = serializers.IntegerField(help_text="Where the number ends in that text.")
    figure = serializers.CharField(help_text="The number as the page shows it.")
    quote = FigureQuoteSerializer(help_text="The sentence that states the same result.")

    class Meta:
        dataclass = FigureMark


class FigureMarksSerializer(serializers.Serializer):
    marks = FigureMarkSerializer(many=True, help_text="The numbers to mark, at most 4, each with its source.")


class HighlightValueFormatSerializer(DataclassSerializer):
    format = serializers.CharField(
        allow_null=True, help_text="Number format of the insight, for example numeric, percentage or currency."
    )
    prefix = serializers.CharField(allow_null=True, help_text="Text the insight shows before each value.")
    postfix = serializers.CharField(allow_null=True, help_text="Text the insight shows after each value.")
    decimal_places = serializers.IntegerField(allow_null=True, help_text="Most decimal places the insight shows.")

    class Meta:
        dataclass = HighlightValueFormat


class HighlightMoverSerializer(DataclassSerializer):
    label = serializers.CharField(  # type: ignore[assignment]
        help_text="Name of one series of the insight, for example a breakdown value."
    )
    value = serializers.FloatField(help_text="Value of the series for the last complete period.")
    change_pct = serializers.FloatField(
        allow_null=True,
        help_text="Change of the series against the period before, in percent. Null when the period before is 0.",
    )

    class Meta:
        dataclass = HighlightMover


class PulsePinSerializer(DataclassSerializer):
    key = serializers.CharField(
        max_length=200,
        help_text="Key of the number to keep: a key metric setting such as signup_event, or insight:<short_id>.",
    )
    name = serializers.CharField(
        max_length=400, help_text="Name to show for the number until the highlights compute its value."
    )
    dashboard_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="For an insight pinned from a dashboard tile, the dashboard whose filters it keeps. Null otherwise.",
    )

    class Meta:
        dataclass = PulsePin


MAX_PINS_IN_REQUEST = 20


class PulsePinsSerializer(DataclassSerializer):
    pins = PulsePinSerializer(
        many=True,
        help_text=f"Numbers the person keeps at the start of the key numbers, in order. Suggestions fill the free places. Only the first 4 distinct keys are kept. At most {MAX_PINS_IN_REQUEST} entries.",
    )

    class Meta:
        dataclass = PulsePins

    def to_internal_value(self, data: Any) -> PulsePins:
        if isinstance(data, dict) and isinstance(data.get("pins"), list) and len(data["pins"]) > MAX_PINS_IN_REQUEST:
            raise serializers.ValidationError({"pins": [f"Send at most {MAX_PINS_IN_REQUEST} pins."]})
        return super().to_internal_value(data)


class HighlightMetricSerializer(DataclassSerializer):
    key = serializers.CharField(
        help_text="Stable key of the metric: a key metric setting such as signup_event, or insight:<short_id>."
    )
    name = serializers.CharField(help_text="Name of the key metric or of the insight, for example Sign-ups.")
    value = serializers.FloatField(
        help_text="Value for the last complete period: the last 7 complete days, or the last complete week or month."
    )
    unit = serializers.ChoiceField(
        choices=HighlightUnit.choices,
        help_text="`events` for a count of events, `people` for unique people, `number` for an insight value.",
    )
    change_pct = serializers.FloatField(
        allow_null=True,
        help_text="Change against the period before, in percent. Null when the period before is 0.",
    )
    series = serializers.ListField(
        child=serializers.FloatField(),
        help_text="Values oldest first: daily for the last 28 complete days, or one value per week or month.",
    )
    interval = serializers.ChoiceField(
        choices=HighlightInterval.choices, help_text="What one value in `series` covers: a day, a week or a month."
    )
    url = serializers.CharField(
        allow_null=True,
        help_text="Path of the insight the metric comes from. For a key metric, a new trends insight of the same days.",
    )
    value_format = HighlightValueFormatSerializer(
        allow_null=True,
        help_text="How the insight formats its values. Null for a key metric and for an insight with plain numbers.",
    )
    period_starts = serializers.ListField(
        child=serializers.DateField(),
        help_text="The first day of the period each value in `series` covers, in the project's timezone. Same length and order as `series`.",
    )
    reason = serializers.ChoiceField(
        choices=HighlightMetricReason.choices,
        allow_null=True,
        help_text="Why the pulse suggests the metric: `routine` for an insight the person opens often, `dashboard` for a tile of a dashboard they open often, `key_metric` for a key metric of the project. Null for a number the person pinned, which `pins` lists, and for metrics computed before this field existed.",
    )
    dashboard_name = serializers.CharField(
        allow_null=True,
        help_text="Name of the dashboard the tile comes from when `reason` is `dashboard`, else null.",
    )
    dashboard_id = serializers.IntegerField(
        allow_null=True,
        help_text="Id of the dashboard the tile comes from, with its filters applied. Pass it when pinning the tile. Null otherwise.",
    )
    opened_days = serializers.IntegerField(
        allow_null=True,
        help_text="On how many of the last 14 days the person opened the insight, or the dashboard of the tile. Null for a key metric.",
    )
    last_opened = serializers.DateField(
        allow_null=True,
        help_text="The last day the person opened the insight, or the dashboard of the tile, in the project's timezone. Null for a key metric.",
    )
    previous_value = serializers.FloatField(
        allow_null=True,
        help_text="Value for the period before the last complete one, the base of `change_pct`. Null when unknown.",
    )
    movers = HighlightMoverSerializer(
        many=True,
        help_text="For an insight with several series, the series that changed most last period, biggest change first. Empty otherwise.",
    )

    class Meta:
        dataclass = HighlightMetric


class HighlightItemSerializer(DataclassSerializer):
    key = serializers.CharField(help_text="Stable key of the item for this person and day.")
    label = serializers.ChoiceField(  # type: ignore[assignment]
        choices=HighlightLabel.choices,
        help_text="`risk` when something got worse or broke, `opportunity` when the person can act to gain.",
    )
    priority = serializers.ChoiceField(
        choices=HighlightPriority.choices,
        help_text="Priority on the same scale as report priorities. `P1` for a risk with a score of 0.75 or more, `P2` for another risk, `P3` for an opportunity with a score of 0.4 or more, `P4` for another opportunity.",
    )
    title = serializers.CharField(help_text="One sentence that says what happened, with numbers.")
    detail = serializers.CharField(help_text="One or two short sentences with the comparison and the next action.")
    url = serializers.CharField(allow_null=True, help_text="Path in the app to open, relative to the project.")
    series = serializers.ListField(
        child=serializers.FloatField(),
        allow_null=True,
        help_text="Values behind the item for a small trend line, oldest first. Null when the item has no trend.",
    )
    score = serializers.FloatField(help_text="Importance weighted by relevance, from 0 to 1.")

    class Meta:
        dataclass = HighlightItem
        extra_kwargs = {
            "source": {"help_text": "Name of the highlight source that found the item, for example alerts."},
        }


class HighlightPinSerializer(DataclassSerializer):
    key = serializers.CharField(help_text="Key of a number the person keeps on their home.")
    status = serializers.ChoiceField(
        choices=HighlightPinStatus.choices,
        help_text="`ready` when the number is in `pulse`. `unavailable` when it has no number to show, for example a deleted insight, one that is not a trend, or a query that failed or did not finish in time. A pin missing from this list was added after these highlights were computed.",
    )

    class Meta:
        dataclass = HighlightPin


class HighlightsSerializer(DataclassSerializer):
    status = serializers.ChoiceField(
        choices=HighlightsStatus.choices,
        help_text="`ready` when the content is fresh. `computing` while new highlights are being computed: the content is the last ready highlights of the day, or empty, so poll again every 2 seconds until the status changes. `failed` when the last computation failed: the content is the last ready highlights of the day, or empty.",
    )
    generated_at = serializers.DateTimeField(
        allow_null=True, help_text="When the content was computed. Null when no highlights were computed yet today."
    )
    day = serializers.DateField(help_text="The day the highlights are for, in the project's timezone.")
    refresh_at = serializers.DateTimeField(
        help_text="Midnight at the end of `day` in the project's timezone, when the next day's highlights start. Load them again then."
    )
    pulse = HighlightMetricSerializer(many=True, help_text="Key metrics of the project from its settings.")
    items = HighlightItemSerializer(
        many=True,
        help_text="Up to 6 items, the highest scores across sources, in display order: by `priority`, then by `score`, highest first.",
    )
    pins = HighlightPinSerializer(
        many=True,
        help_text="The numbers the person keeps, in their order, with the state of each one. Pinned numbers lead `pulse`.",
    )

    class Meta:
        dataclass = Highlights
