from django.db import models

from posthog.models.team import Team


class OptOutSyncConfig(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)

    # Step 1: App API import
    app_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    app_import_result = models.JSONField(null=True, blank=True)

    # Step 2: CSV upload
    csv_import_result = models.JSONField(null=True, blank=True)

    # Step 3: Inbound webhook sync (Customer.io → PostHog)
    webhook_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    webhook_enabled = models.BooleanField(default=False)

    # Step 4: Outbound track sync (PostHog → Customer.io)
    track_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    track_enabled = models.BooleanField(default=False)

    class Meta:
        app_label = "messaging"
        db_table = "posthog_messaging_optout_sync_config"
