import re

from django.contrib.postgres.fields import ArrayField
from django.core import validators
from django.db import models
from django.utils.deconstruct import deconstructible

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDTModel


@deconstructible
class EmailWithDisplayNameValidator:
    # In "Michael (some guy) <michael@x.com>" display_name_regex's group 1 matches "Michael"
    # (round brackets are comments according to RFC #822, content in there is ignored), and group 2 matches "michael@x.com"
    display_name_regex = r"([^(]+) <(.+)>$"

    def __call__(self, value: str) -> None:
        display_name_match = re.match(self.display_name_regex, value)
        if display_name_match:
            value = display_name_match.group(2).strip()
        return validators.validate_email(value)


class UserInterview(UUIDTModel, CreatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    interviewee_emails = ArrayField(
        models.CharField(max_length=254, validators=[EmailWithDisplayNameValidator()]), default=list
    )
    transcript = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    # Optional topic linkage for AI voice interviews triggered via SharingConfiguration links.
    topic = models.ForeignKey(
        "UserInterviewTopic",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interviews",
    )
    interviewee_identifier = models.CharField(max_length=400, blank=True, default="")
    recording_url = models.URLField(blank=True, default="", max_length=2048)
    call_metadata = models.JSONField(default=dict, blank=True)


class UserInterviewTopic(UUIDTModel, CreatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    interviewee_emails = ArrayField(
        models.CharField(max_length=254, validators=[EmailWithDisplayNameValidator()]),
        default=list,
        blank=True,
    )
    interviewee_distinct_ids = ArrayField(
        models.CharField(max_length=400),
        default=list,
        blank=True,
    )
    topic = models.TextField()
    agent_context = models.TextField(blank=True, default="")
    questions = ArrayField(
        models.TextField(),
        default=list,
        blank=True,
    )
    invite_subject = models.CharField(max_length=255, blank=True, default="", db_default="")
    invite_message = models.TextField(blank=True, default="", db_default="")

    class Meta:
        ordering = ["-created_at"]


class IntervieweeContext(UUIDTModel, CreatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    topic = models.ForeignKey(
        UserInterviewTopic,
        on_delete=models.CASCADE,
        related_name="interviewee_contexts",
    )
    interviewee_identifier = models.CharField(max_length=400)
    agent_context = models.TextField()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["topic", "interviewee_identifier"],
                name="unique_interviewee_per_topic",
            ),
        ]
