"""Django models for founder_mode.

One row per startup idea a founder is working through. Stages each own a JSON column:

    ideation:        {what, how, who, problem}
    validation:      stage 2 envelope — competitor research + verdict (Gemini)
    gtm:             stage 3 envelope — conceptual positioning, pricing, channels (Gemini)
    mvp:             stage 4 envelope — MVP happy path (Gemini, placeholder for now)
    marketing_page:  stage 5a envelope — landing page build spec (Gemini)
    marketing_steps: stage 5b envelope — practical launch playbook with social posts (OpenAI)

Each envelope is server-managed and follows the same shape:
    {status: pending|running|completed|failed, started_at, completed_at|failed_at, result, error}
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
    marketing_page = models.JSONField(default=dict, blank=True)
    marketing_steps = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"FounderProject<{self.name}>"
