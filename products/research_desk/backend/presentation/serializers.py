"""DRF serializers for research_desk."""

from typing import Any

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import ContactCheckResult, ResearchSessionDTO, ResearchSourceDTO, ResearchTouch
from ..facade.enums import SourceKind


class ResearchSourceSerializer(DataclassSerializer):
    class Meta:
        dataclass = ResearchSourceDTO
        extra_kwargs = {
            "id": {"help_text": "Unique ID of the source."},
            "kind": {"help_text": "What the source is: a workflow, survey, cohort, or event name."},
            "external_id": {
                "help_text": "Workflow ID, survey ID, cohort ID, or event name that identifies the source."
            },
            "label": {"help_text": "Human-readable name, such as 'Error tracking interview outreach'."},
            "owner_email": {"help_text": "Email of the PostHog employee who runs this outreach."},
            "product_area": {"help_text": "Product area the outreach is about, such as 'session replay'."},
            "origin": {"help_text": "Whether a person or a scout registered the source."},
            "active": {"help_text": "Inactive sources are ignored by the contact check."},
            "created_at": {"help_text": "When the source was registered."},
            "updated_at": {"help_text": "When the source was last changed."},
        }


class CreateResearchSourceSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=SourceKind.choices, help_text="What the source is: a workflow, survey, cohort, or event name."
    )
    external_id = serializers.CharField(
        max_length=400,
        help_text="Workflow ID, survey ID, cohort ID, or event name, depending on kind.",
    )
    label = serializers.CharField(max_length=255, help_text="Human-readable name for the source.")  # type: ignore[assignment]
    owner_email = serializers.EmailField(
        required=False, default="", allow_blank=True, help_text="Email of the employee who runs this outreach."
    )
    product_area = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=128, help_text="Product area the outreach is about."
    )


class UpdateResearchSourceSerializer(serializers.Serializer):
    label = serializers.CharField(required=False, max_length=255, help_text="Human-readable name for the source.")  # type: ignore[assignment]
    owner_email = serializers.EmailField(
        required=False, allow_blank=True, help_text="Email of the employee who runs this outreach."
    )
    product_area = serializers.CharField(
        required=False, allow_blank=True, max_length=128, help_text="Product area the outreach is about."
    )
    active = serializers.BooleanField(required=False, help_text="Set to false to stop counting this source.")


class ResearchSessionSerializer(DataclassSerializer):
    class Meta:
        dataclass = ResearchSessionDTO
        extra_kwargs = {
            "id": {"help_text": "Unique ID of the session."},
            "origin": {"help_text": "Where the session was detected, such as a calendar."},
            "external_ref": {"help_text": "Stable ID from the origin, such as a calendar event UID."},
            "title": {"help_text": "Meeting title."},
            "start_time": {"help_text": "When the session starts."},
            "end_time": {"help_text": "When the session ends, if known."},
            "status": {"help_text": "Scheduled, held, or cancelled."},
            "organizer_email": {"help_text": "Email of the employee who organized the session."},
            "internal_emails": {"help_text": "PostHog attendees."},
            "external_emails": {"help_text": "Customer attendees."},
            "meeting_url": {"help_text": "Link to join the meeting, if known."},
            "brief_posted_at": {"help_text": "When a brief for this session was posted to Slack."},
            "created_at": {"help_text": "When the session was first detected."},
        }


class ListResearchSessionsQuerySerializer(serializers.Serializer):
    start_after = serializers.DateTimeField(
        required=False, help_text="Only return sessions that start at or after this time (ISO 8601)."
    )
    start_before = serializers.DateTimeField(
        required=False, help_text="Only return sessions that start before this time (ISO 8601)."
    )


class ResearchTouchSerializer(DataclassSerializer):
    class Meta:
        dataclass = ResearchTouch
        extra_kwargs = {
            "channel": {"help_text": "How the contact was reached: email, survey, event, cohort, or session."},
            "contact": {"help_text": "Email address that was contacted."},
            "source_label": {"help_text": "Name of the source or session that made the contact."},
            "owner_email": {"help_text": "Employee responsible for the contact, if known."},
            "occurred_at": {"help_text": "When the contact happened. Empty for cohort membership."},
            "source_id": {"help_text": "ID of the source that made the contact, if any."},
            "session_id": {"help_text": "ID of the session, for session touches."},
        }


class ContactCheckResultSerializer(DataclassSerializer):
    touches = ResearchTouchSerializer(many=True, help_text="Every research touch found, newest first.")

    class Meta:
        dataclass = ContactCheckResult
        extra_kwargs = {
            "emails": {"help_text": "Normalized emails that were checked."},
            "domain": {"help_text": "Normalized domain that was checked, if any."},
            "last_touch_at": {"help_text": "Most recent dated touch, if any."},
            "recently_contacted": {
                "help_text": "True when a touch falls inside the warning window or the contact is in an active "
                "'already contacted' cohort. This is a warning, not a block."
            },
            "warn_within_days": {"help_text": "Size of the warning window in days."},
            "lookback_days": {"help_text": "How far back touches were searched, in days."},
        }


class ContactCheckQuerySerializer(serializers.Serializer):
    emails = serializers.ListField(
        child=serializers.CharField(max_length=320),
        required=False,
        default=list,
        max_length=50,
        help_text="Emails to check. Repeat the parameter or pass a comma-separated list.",
    )
    domain = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=253,
        help_text="Company domain to check, such as 'example.com'. Matches anyone at that domain.",
    )
    lookback_days = serializers.IntegerField(
        required=False, default=180, min_value=1, max_value=730, help_text="How far back to search, in days."
    )
    warn_within_days = serializers.IntegerField(
        required=False,
        default=60,
        min_value=0,
        max_value=730,
        help_text="Touches within this many days set recently_contacted.",
    )

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        emails = data.getlist("emails") if hasattr(data, "getlist") else data.get("emails", [])
        if isinstance(emails, str):
            emails = [emails]
        split = [part.strip() for value in emails for part in value.split(",") if part.strip()]
        merged = {key: data.get(key) for key in ("domain", "lookback_days", "warn_within_days") if key in data}
        return super().to_internal_value({**merged, "emails": split})

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.get("emails") and not attrs.get("domain"):
            raise serializers.ValidationError("Pass at least one email or a domain.")
        return attrs
