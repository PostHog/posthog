"""
Django models for wizard.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UUIDModel

from products.wizard.backend.facade.enums import RunPhase


class WizardSession(UUIDModel, TeamScopedRootMixin, CreatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")

    # db_constraint=False because posthog_user is a hot table (a constrained FK would lock it).
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )

    session_id = models.CharField(max_length=255)
    workflow_id = models.CharField(max_length=255)
    skill_id = models.CharField(max_length=255)
    started_at = models.DateTimeField()

    run_phase = models.CharField(max_length=50, choices=[(phase.value, phase.value) for phase in RunPhase])

    tasks = models.JSONField(default=list)
    event_plan = models.JSONField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)
    # An in-flight wizard_ask prompt ({id, asked_at, question_count, sensitive, prompts?}).
    # Null means no input is pending — each push replaces it, so the CLI clearing the
    # question is just the next upsert without the field.
    pending_input = models.JSONField(null=True, blank=True)
    # The markdown handoff doc (the wizard's setup report) once the run has produced one.
    # Unlike the fields above it is monotonic within a session: a push without it keeps
    # the stored value (see upsert_session), since the doc arrives late in the run.
    handoff_text = models.TextField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [models.UniqueConstraint(fields=["team", "session_id"], name="unique_wizard_session_per_team")]

        indexes = [
            # to optimize fetching the latest session
            models.Index(
                fields=["team", "workflow_id", "skill_id", "-started_at"],
            ),
            # the detector queries team + workflow_id (no skill_id) ordered by started_at desc
            models.Index(
                fields=["team", "workflow_id", "-started_at"],
                name="wizard_sess_team_wf_start_idx",
            ),
        ]
