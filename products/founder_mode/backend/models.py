"""Django models for founder_mode.

One row per startup idea a founder is working through. Each of the four stages
(ideation, validation, GTM, MVP) writes into its own JSON column so teammates
can iterate on their stage independently without schema coordination.

Expected shapes (not enforced at the DB layer — see logic.py for the schemas):
    ideation:   {what, how, who, problem}
    validation: {status, report, error, ideation_hash, started_at, updated_at}
    gtm:        defined by the GTM stage owner
    mvp:        defined by the MVP stage owner
"""

from django.db import models

from posthog.models.utils import UUIDModel


class FounderProject(UUIDModel):
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="founder_projects",
    )
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    name = models.CharField(max_length=200)
    ideation = models.JSONField(default=dict, blank=True)
    validation = models.JSONField(default=dict, blank=True)
    gtm = models.JSONField(default=dict, blank=True)
    mvp = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"FounderProject<{self.name}>"
