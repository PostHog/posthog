from django.db import models, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver

import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel
from posthog.plugins.plugin_server_api import reload_hog_flow_action_templates_on_workers

logger = structlog.get_logger(__name__)


class HogFlowActionTemplate(TeamScopedRootMixin, UUIDModel):
    """
    A team-scoped, reusable configuration for a workflow function action (e.g. a webhook destination
    configured once and linked from many workflows). Workflow actions store only a reference
    (`config.action_template_id`); the worker resolves inputs from this row at execution time, so
    edits here propagate to every linked action automatically.
    """

    class Meta:
        # The CDP worker reads this table directly by name; keep in sync with
        # nodejs/src/cdp/services/hogflows/hogflow-action-template-manager.service.ts
        db_table = "posthog_hogflowactiontemplate"
        indexes = [
            models.Index(fields=["team", "deleted"]),
        ]

    # db_constraint=False on the hot-table FKs (team, user) so CreateModel takes no lock
    # on posthog_team / posthog_user; app-level enforcement is enough here.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    # The catalog HogFunctionTemplate.template_id this configuration is for, e.g. "template-webhook".
    template_id = models.CharField(max_length=400)
    # Non-secret inputs, stored compiled ({value, bytecode, ...}) so the worker can execute them
    # without a validation pass. Secret inputs live in `encrypted_inputs` instead.
    inputs = models.JSONField(default=dict)
    encrypted_inputs: EncryptedJSONStringField = EncryptedJSONStringField(null=True, blank=True)
    mappings = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    deleted = models.BooleanField(default=False)

    def __str__(self):
        return f"HogFlowActionTemplate {self.id}: {self.name}"


@receiver(post_save, sender=HogFlowActionTemplate)
def hog_flow_action_template_saved(sender, instance: HogFlowActionTemplate, created, **kwargs):
    reload_hog_flow_action_templates_on_workers(team_id=instance.team_id, template_ids=[str(instance.id)])


@receiver(post_delete, sender=HogFlowActionTemplate)
def hog_flow_action_template_deleted(sender, instance: HogFlowActionTemplate, **kwargs):
    team_id = instance.team_id
    template_id = str(instance.id)
    # post_delete fires inside the delete transaction, so publish only after commit; otherwise a
    # worker could re-read the still-live row and cache it for another TTL.
    transaction.on_commit(
        lambda: reload_hog_flow_action_templates_on_workers(team_id=team_id, template_ids=[template_id])
    )
