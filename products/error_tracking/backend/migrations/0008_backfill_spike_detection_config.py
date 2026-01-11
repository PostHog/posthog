from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def backfill_spike_detection_config(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    ErrorTrackingSpikeDetectionConfig = apps.get_model("error_tracking", "ErrorTrackingSpikeDetectionConfig")

    batch_size = 1000
    last_id = 0

    while True:
        teams = list(Team.objects.filter(id__gt=last_id).order_by("id")[:batch_size].values_list("id", flat=True))
        if not teams:
            break

        configs_to_create = []
        for team_id in teams:
            configs_to_create.append(
                ErrorTrackingSpikeDetectionConfig(
                    team_id=team_id,
                    snooze_duration_minutes=10,
                    multiplier=10,
                    threshold=500,
                )
            )

        ErrorTrackingSpikeDetectionConfig.objects.bulk_create(configs_to_create, ignore_conflicts=True)
        logger.info("backfill_spike_detection_config_batch", batch_start=last_id, batch_end=teams[-1])
        last_id = teams[-1]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("error_tracking", "0007_spike_detection_config"),
    ]

    operations = [
        migrations.RunPython(backfill_spike_detection_config, migrations.RunPython.noop),
    ]
