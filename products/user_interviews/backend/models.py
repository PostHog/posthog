from django.db import models
from posthog.models.team import Team
from django.contrib.postgres.fields import ArrayField
from posthog.models.utils import UUIDModel, CreatedMetaFields


class UserInterview(UUIDModel, CreatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    interviewee_emails = ArrayField(models.EmailField())
    transcript = models.TextField(blank=True)
    summary = models.TextField(blank=True)

    def __str__(self):
        return f"Interview {self.id} for team {self.team_id} by {self.interviewer.email if self.interviewer else 'Unknown'}"
