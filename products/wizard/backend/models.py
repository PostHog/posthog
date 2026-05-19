"""
Django models for wizard.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.wizard.backend.facade.enums import RunPhase


class WizardSession(UUIDModel, TeamScopedRootMixin):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")

    session_id = models.CharField(max_length=255)
    workflow_id = models.CharField(max_length=255)
    skill_id = models.CharField(max_length=255)
    started_at = models.DateTimeField()

    run_phase = models.CharField(max_length=50, choices=[(phase.value, phase.value) for phase in RunPhase])

    tasks = models.JSONField(default=list)
    event_plan = models.JSONField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [models.UniqueConstraint(fields=["team", "session_id"], name="unique_wizard_session_per_team")]

        indexes = [
            # to optimize fetching the latest session
            models.Index(
                fields=["team", "workflow_id", "skill_id", "-started_at"],
            )
        ]
