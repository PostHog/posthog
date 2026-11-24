"""DRF serializers for hogs."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    HogActionDTO,
    HogDTO,
    HogEventDTO,
    HogMessageDTO,
    HogReportDTO,
    HogRuleDTO,
    HogScheduleDTO,
    HogTriggerDTO,
)
from ..facade.enums import (
    HogActionDecision,
    HogEvidenceKind,
    HogReportFollowUp,
    HogReportPriority,
    HogReportStatus,
    HogRuleEffect,
    HogStatus,
)


class HogMessageSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogMessageDTO
        extra_kwargs = {
            "report": {"help_text": "Set when the message is a report. The chat shows it as a card with its actions."},
            "action": {"help_text": "Set when the message asks the owner to approve an action."},
        }


class HogSerializer(DataclassSerializer):
    last_message = HogMessageSerializer(
        allow_null=True, help_text="The newest message in the owner's chat with this hog."
    )

    class Meta:
        dataclass = HogDTO
        extra_kwargs = {
            "responsibility": {"allow_blank": True, "help_text": "The hog's charter. Blank until setup is done."},
            "memory": {"allow_blank": True, "help_text": "Notes the hog keeps for its future self."},
            "working": {"help_text": "True while the hog is acting on a wake."},
            "unread_count": {"help_text": "Messages from the hog that the owner has not opened."},
            "needs_you_count": {
                "help_text": "Approvals that wait for the owner, plus open reports they have not acted on. "
                "Reading does not lower it."
            },
            "mcp_installation_ids": {"help_text": "MCP store installations this hog may use."},
        }


class HogScheduleSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogScheduleDTO


class CreateHogSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, help_text="The hog's display name.")
    emoji = serializers.CharField(max_length=16, required=False, default="🦔", help_text="Emoji shown as the avatar.")
    color = serializers.CharField(
        max_length=16, required=False, default="#00A884", help_text="Avatar background as a hex color."
    )
    responsibility = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="What the hog looks after. Leave blank to let the hog ask for it in its first chat.",
    )
    mcp_installation_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        help_text="IDs of the owner's MCP store installations this hog may use.",
    )


class UpdateHogSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False, help_text="The hog's display name.")
    emoji = serializers.CharField(max_length=16, required=False, help_text="Emoji shown as the avatar.")
    color = serializers.CharField(max_length=16, required=False, help_text="Avatar background as a hex color.")
    responsibility = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="The hog's charter: what it owns, what is worth reporting, and how often it checks.",
    )
    memory = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=20000,
        help_text="Notes the hog keeps for its future self. Replaces the whole memory.",
    )
    status = serializers.ChoiceField(
        choices=HogStatus.choices,
        required=False,
        help_text="setup until the hog has a charter, then active. paused stops every wake.",
    )
    mcp_installation_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="IDs of the owner's MCP store installations this hog may use.",
    )


class MessageContentSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=8000, help_text="The message text.")


class TellHogSerializer(serializers.Serializer):
    to_hog_id = serializers.UUIDField(help_text="ID of the hog to send the note to. Find it with hogs-list.")
    content = serializers.CharField(max_length=8000, help_text="The note. Say what you found and what you need.")


class ListMessagesQuerySerializer(serializers.Serializer):
    after = serializers.DateTimeField(
        required=False, help_text="Only return messages created after this ISO 8601 time."
    )
    include_internal = serializers.BooleanField(
        required=False, default=False, help_text="Also return notes between hogs, which the chat hides."
    )


class CreateHogScheduleSerializer(serializers.Serializer):
    prompt = serializers.CharField(
        max_length=4000, help_text="A note to your future self: what to check or do when this fires."
    )
    run_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None, help_text="Fire once at this ISO 8601 time."
    )
    cron_expression = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        max_length=120,
        help_text="Fire on a repeat: a 5-field cron expression in UTC, at most every 15 minutes.",
    )


class HogScheduleIdSerializer(serializers.Serializer):
    schedule_id = serializers.UUIDField(help_text="ID of the schedule to delete.")


class HogReportSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogReportDTO
        extra_kwargs = {
            "impact": {"allow_blank": True, "help_text": "One sentence that starts with the number that matters."},
            "proposal": {"allow_blank": True, "help_text": "What the hog would do about it."},
            "verdict_reason": {"allow_blank": True, "help_text": "Why the owner resolved or dismissed the report."},
            "read": {"help_text": "True once the owner has opened the report."},
        }


class HogActionSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogActionDTO
        extra_kwargs = {
            "draft": {"allow_blank": True, "help_text": "Exactly what would be sent or changed."},
            "result": {"allow_blank": True, "help_text": "What happened when the hog carried the action out."},
            "status": {
                "help_text": "pending waits for the owner. approved may be carried out now. denied must not be."
            },
        }


class HogRuleSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogRuleDTO


class HogTriggerSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogTriggerDTO
        extra_kwargs = {
            "instructions": {"allow_blank": True},
            "fire_path": {"help_text": "POST any JSON body to this path on the PostHog host to fire the trigger."},
        }


class HogEventSerializer(DataclassSerializer):
    class Meta:
        dataclass = HogEventDTO
        extra_kwargs = {"woke_hog": {"help_text": "False for a repeated event, a paused hog, or a hog at its cap."}}


class EvidenceInputSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=500, help_text="What this piece of evidence shows.")
    source = serializers.CharField(  # type: ignore[assignment]
        max_length=1000, help_text="A link or an identifier a person can check, such as an insight URL or an issue ID."
    )
    kind = serializers.ChoiceField(
        choices=HogEvidenceKind.choices,
        required=False,
        default=HogEvidenceKind.OTHER.value,
        help_text="What kind of record the source is.",
    )


class PublishReportSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, help_text="The outcome to change, not the observation.")
    summary = serializers.CharField(
        max_length=8000, help_text="The first paragraph is the lead: what is happening, to whom, since when."
    )
    priority = serializers.ChoiceField(
        choices=HogReportPriority.choices,
        help_text="p0 broken for many now, p1 hurts users today, p2 fix this week, p3 when there is time, "
        "p4 worth knowing.",
    )
    impact = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        default="",
        help_text="One sentence that starts with the number that matters.",
    )
    proposal = serializers.CharField(
        max_length=4000,
        required=False,
        allow_blank=True,
        default="",
        help_text="What you would do, concretely enough to act on.",
    )
    evidence = serializers.ListField(
        child=EvidenceInputSerializer(),
        required=False,
        default=list,
        max_length=20,
        help_text="Specific records a person can check.",
    )


class ReportVerdictSerializer(serializers.Serializer):
    report_id = serializers.UUIDField(help_text="ID of the report.")
    status = serializers.ChoiceField(
        choices=HogReportStatus.choices, help_text="resolved or dismissed closes the report. open reopens it."
    )
    reason = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default="", help_text="Why, in a few words."
    )


class ReportIdSerializer(serializers.Serializer):
    report_id = serializers.UUIDField(help_text="ID of the report.")


class ReportFollowUpSerializer(serializers.Serializer):
    report_id = serializers.UUIDField(help_text="ID of the report.")
    mode = serializers.ChoiceField(
        choices=HogReportFollowUp.choices,
        help_text="implement makes the proposed change. investigate finds the root cause and changes nothing.",
    )


class ReportFollowUpResultSerializer(serializers.Serializer):
    started = serializers.BooleanField(help_text="False when the hog is paused or at its hourly wake limit.")


class ProposeActionSerializer(serializers.Serializer):
    kind = serializers.SlugField(
        max_length=60,
        help_text="A short, stable name for the class of side effect, such as slack-message, github-pr or "
        "email-send. The owner's rules match on it, so reuse the same kind for the same sort of action.",
    )
    label = serializers.CharField(max_length=200, help_text="One line saying what you would do and to whom.")  # type: ignore[assignment]
    draft = serializers.CharField(
        max_length=8000,
        required=False,
        allow_blank=True,
        default="",
        help_text="Exactly what you would send or change. The owner may edit it before approving.",
    )


class DecideActionSerializer(serializers.Serializer):
    action_id = serializers.UUIDField(help_text="ID of the action.")
    decision = serializers.ChoiceField(choices=HogActionDecision.choices, help_text="approve or deny.")
    always = serializers.BooleanField(
        required=False, default=False, help_text="Also save the decision as a standing rule for this kind of action."
    )
    draft = serializers.CharField(
        max_length=8000,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        help_text="An edited draft to approve in place of the hog's.",
    )


class CompleteActionSerializer(serializers.Serializer):
    action_id = serializers.UUIDField(help_text="ID of the approved action you carried out.")
    result = serializers.CharField(max_length=2000, help_text="What happened, with a link when there is one.")


class SetRuleSerializer(serializers.Serializer):
    kind = serializers.SlugField(max_length=60, help_text="The action kind the rule covers.")
    effect = serializers.ChoiceField(
        choices=HogRuleEffect.choices, help_text="allow runs without asking, ask waits for the owner, deny refuses."
    )


class CreateHogTriggerSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, help_text="What sends these events, such as Deploy finished.")
    instructions = serializers.CharField(
        max_length=4000,
        required=False,
        allow_blank=True,
        default="",
        help_text="A note to your future self: what to check when an event arrives, and what is worth reporting.",
    )


class HogTriggerIdSerializer(serializers.Serializer):
    trigger_id = serializers.UUIDField(help_text="ID of the trigger to delete.")
