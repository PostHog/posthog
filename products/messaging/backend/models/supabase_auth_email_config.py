from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class SupabaseAuthEmailConfig(TeamScopedRootMixin, UUIDModel):
    """Sends a Supabase project's auth emails through the team's transactional email templates.

    Supabase posts every auth email to the team's Send Email Hook endpoint, signed with `hook_secret`.
    `templates` maps each Supabase email action type to the message template that sends it.
    """

    # db_constraint=False so CreateModel takes no lock on posthog_team / posthog_user.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    # The Supabase project URL, such as https://abcdefgh.supabase.co. Confirmation links point at its verify endpoint.
    supabase_url = models.URLField(max_length=200, blank=True, default="")
    # The Standard Webhooks secret Supabase signs the hook with, as `v1,whsec_<base64>`.
    hook_secret = EncryptedTextField(null=True, blank=True)
    # Supabase email action type -> message template id.
    templates = models.JSONField(default=dict)

    class Meta:
        app_label = "messaging"
        db_table = "posthog_messaging_supabase_auth_email_config"
        constraints = [models.UniqueConstraint(fields=["team"], name="unique_supabase_auth_email_config_per_team")]
