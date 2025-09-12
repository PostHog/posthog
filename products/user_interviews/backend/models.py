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

    def __call__(self, value):
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
