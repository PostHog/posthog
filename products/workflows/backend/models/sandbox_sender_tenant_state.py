from django.db import models


class SandboxSenderTenantState(models.Model):
    """Instance-level mirror of the shared sandbox SES tenant; platform state, not tenant data, so no team_id."""

    tenant_name = models.CharField(max_length=64, unique=True)
    sending_status = models.CharField(max_length=32, blank=True, default="", db_default="")
    reputation_impact = models.CharField(max_length=32, blank=True, default="", db_default="")
    synced_at = models.DateTimeField(null=True, blank=True)
