"""DRF serializers for today. Response shapes come from the facade contracts."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.signals.backend.facade import api as signals

from ..facade.contracts import (
    Briefing,
    BriefingItem,
    BriefingItemChart,
    BriefingItemMetric,
    BriefingItemReport,
    BriefingSegment,
    Candidate,
    CandidateFact,
    CandidateList,
)


class TodayQuerySerializer(serializers.Serializer):
    timezone = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="IANA timezone of the person's browser, for example Europe/Prague. The briefing day starts at 8:00 in it. Defaults to the project timezone.",
    )


class BriefingSegmentSerializer(DataclassSerializer):
    text = serializers.CharField(help_text="A run of text in a paragraph. Includes its own spaces.")
    item_key = serializers.CharField(
        allow_null=True, help_text="Key of the item this run links to, or null for plain text."
    )
    highlight = serializers.BooleanField(help_text="True only for the run that names the top item.")

    class Meta:
        dataclass = BriefingSegment


class BriefingItemMetricSerializer(DataclassSerializer):
    metric_id = serializers.CharField(help_text="Stable slug of the metric within its report.")
    title = serializers.CharField(help_text="Short label of what the metric measures.")
    kind = serializers.ChoiceField(
        choices=signals.REPORT_METRIC_KINDS, help_text="What the value measures, for example affected_users."
    )
    role = serializers.ChoiceField(
        choices=signals.REPORT_METRIC_ROLES,
        help_text="`primary` for the report's key observation, otherwise `supporting`.",
    )
    value = serializers.FloatField(help_text="The latest saved snapshot of the metric.")
    series = serializers.ListField(
        child=serializers.FloatField(),
        allow_null=True,
        help_text="Trailing per-bucket values saved with the snapshot, oldest first. Null when none were saved.",
    )
    value_format = serializers.ChoiceField(
        choices=signals.REPORT_METRIC_VALUE_FORMATS, help_text="How to format the value, for example count."
    )
    unit = serializers.CharField(allow_null=True, help_text="Optional short suffix or currency code, such as USD.")
    query = serializers.JSONField(
        help_text="The metric's live InsightVizNode wrapping one TrendsQuery, as the report stores it."
    )

    class Meta:
        dataclass = BriefingItemMetric


class BriefingItemChartSerializer(DataclassSerializer):
    chart_id = serializers.CharField(help_text="Stable slug of the chart within its report.")
    title = serializers.CharField(help_text="Short heading of the chart.")
    query = serializers.JSONField(help_text="The query node the report body draws, as the report stores it.")

    class Meta:
        dataclass = BriefingItemChart


class BriefingItemReportSerializer(DataclassSerializer):
    priority = serializers.CharField(allow_null=True, help_text="The report's priority, P0 to P4, or null if unset.")
    summary = serializers.CharField(help_text="The report's summary, shortened to a few sentences.")
    pull_request_state = serializers.ChoiceField(
        choices=signals.IMPLEMENTATION_PR_STATES,
        allow_null=True,
        help_text="State of the report's implementation pull request, or null when it has none.",
    )
    pull_request_url = serializers.CharField(
        allow_null=True, help_text="URL of the report's implementation pull request, or null when it has none."
    )
    signal_count = serializers.IntegerField(help_text="How many signals the report groups.")
    updated_at = serializers.DateTimeField(help_text="When the report last changed.")
    metrics = BriefingItemMetricSerializer(
        many=True, help_text="The report's metrics that have a saved snapshot, in the report's order."
    )

    charts = BriefingItemChartSerializer(many=True, help_text="The charts in the report body, in the report's order.")

    class Meta:
        dataclass = BriefingItemReport


class BriefingItemSerializer(DataclassSerializer):
    key = serializers.CharField(
        help_text="Stable item key, for example report:<uuid>, dashboard:<id> or ticket:<uuid>."
    )
    title = serializers.CharField(help_text="The item's own title, as the source names it.")
    # DRF removes declared fields from the class, so this does not replace Field.label at runtime.
    label = serializers.CharField(help_text="Short left-bar label of at most 6 words.")  # type: ignore[assignment]
    signal = serializers.CharField(
        help_text="Short fact under the label, at most 40 characters, for example 'Spend down 37%'."
    )
    url = serializers.CharField(help_text="Where the item opens: an app path, or a GitHub URL for pull requests.")
    rank = serializers.IntegerField(help_text="Position in the briefing, 1 is the top item.")
    source_product = serializers.CharField(
        allow_null=True,
        help_text="For a report, the product its signals came from, for example error_tracking or session_replay. Null for every other item.",
    )
    report = BriefingItemReportSerializer(
        allow_null=True,
        help_text="For a report, its priority, summary, implementation pull request and the metric snapshots the viewer may read. Null for every other item and for a deleted report.",
    )

    class Meta:
        dataclass = BriefingItem
        extra_kwargs = {
            "state": {
                "help_text": "`done` when the item was resolved since the briefing was written, `dismissed` when it was dismissed or suppressed, else `open`. Pull requests always stay `open`."
            },
        }


class BriefingSerializer(DataclassSerializer):
    id = serializers.CharField(help_text="Briefing id.")
    local_day = serializers.DateField(help_text="The day this briefing is for, in the person's timezone.")
    headline = serializers.CharField(help_text="One sentence that counts what needs the person.")
    paragraphs = serializers.ListField(
        child=BriefingSegmentSerializer(many=True),
        help_text="Up to 3 paragraphs, each a list of text runs; runs with an item_key are links.",
    )
    items = BriefingItemSerializer(
        many=True, help_text="The items the text names, in rank order: what the page and the left bar show."
    )
    more_reports_count = serializers.IntegerField(
        help_text="Other open reports for the person, beyond the ones the briefing shows."
    )
    open_reports_count = serializers.IntegerField(
        help_text="Open reports in the whole project beyond the ones the briefing shows, whoever they are for."
    )

    class Meta:
        dataclass = Briefing


class CandidateFactSerializer(DataclassSerializer):
    name = serializers.CharField(help_text="Fact name, for example pct_change or unread_messages.")
    value = serializers.CharField(help_text="Fact value as text.")

    class Meta:
        dataclass = CandidateFact


class CandidateSerializer(DataclassSerializer):
    key = serializers.CharField(help_text="Stable item key, for example report:<uuid> or dashboard:<id>.")
    title = serializers.CharField(help_text="The item's own title.")
    url = serializers.CharField(help_text="Where the item opens.")
    rank = serializers.IntegerField(help_text="Position in the briefing, 1 is the top item.")
    facts = CandidateFactSerializer(many=True, help_text="The numbers and short facts the briefing text rests on.")

    class Meta:
        dataclass = Candidate


class CandidateListSerializer(DataclassSerializer):
    local_day = serializers.DateField(help_text="The day the list is for, in the person's timezone.")
    candidates = CandidateSerializer(many=True, help_text="The briefing's items in rank order, up to 5.")
    more_reports_count = serializers.IntegerField(help_text="Other open reports for the person not in the list.")

    class Meta:
        dataclass = CandidateList
