from django.db import models


# Platform state, not tenant data: one row mirrors the shared sandbox SES tenant for every team, so
# the model has no team_id.
class SandboxSenderTenantState(models.Model):
    tenant_name = models.CharField(max_length=64, unique=True)
    sending_status = models.CharField(max_length=32, blank=True, default="", db_default="")
    synced_at = models.DateTimeField(null=True, blank=True)
