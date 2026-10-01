"""DRF serializers for today. Response shapes come from the facade contracts."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import Briefing, BriefingItem, BriefingSegment, Candidate, CandidateFact, CandidateList


class TodayQuerySerializer(serializers.Serializer):
    timezone = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text="IANA timezone of the person's browser, for example Europe/Prague. Editions start at 8:00 and 12:00 in it. Defaults to the project timezone.",
    )


class BriefingSegmentSerializer(DataclassSerializer):
    text = serializers.CharField(help_text="A run of text in a paragraph. Includes its own spaces.")
    item_key = serializers.CharField(
        allow_null=True, help_text="Key of the item this run links to, or null for plain text."
    )
    highlight = serializers.BooleanField(help_text="True only for the run that names the top item.")

    class Meta:
        dataclass = BriefingSegment


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

    class Meta:
        dataclass = BriefingItem


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
        extra_kwargs = {
            "edition": {"help_text": "'morning' from 8:00, or 'midday' from 12:00, in the person's timezone."},
        }


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
