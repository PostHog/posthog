from posthog.models.team.extensions import register_team_extension_signal

from products.error_tracking.backend.models import ErrorTrackingSettings

# Older projects without a settings row keep the model's false default when they first read settings.
register_team_extension_signal(ErrorTrackingSettings, defaults={"adaptive_ingestion_enabled": True})
