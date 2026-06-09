import logging

from django.db import models

from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


PRODUCT_CONTEXT_MAX_LENGTH = 10_000
CUSTOM_TAGS_MAX_COUNT = 15
CUSTOM_TAG_NAME_MAX_LENGTH = 60
CUSTOM_TAG_DESCRIPTION_MAX_LENGTH = 200


class TeamSessionSummariesConfig(models.Model):
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True)

    product_context = models.TextField(
        blank=True,
        default="",
        max_length=PRODUCT_CONTEXT_MAX_LENGTH,
        help_text=(
            "Free-form description of the team's product, used to tailor AI-generated session summaries. "
            "Injected into the system prompt of every summary generated for this team."
        ),
    )

    custom_tags = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Team-defined tags layered on top of the fixed taxonomy. Stored as a {name: description} mapping "
            "matching the AI_TAGS_FIXED_TAXONOMY shape. Names must be lowercase snake_case. Descriptions tell "
            "the LLM when to apply each tag."
        ),
    )

    class Meta:
        db_table = "ee_teamsessionsummariesconfig"


register_team_extension_signal(TeamSessionSummariesConfig, logger=logger)
