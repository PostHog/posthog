from datetime import UTC, datetime

from django.db import migrations

# Batch runs created before this date never recorded a final status, so they still read as queued. Runs back then
# were sent without being marked done, so completed is the closest true status.
STATUS_TRACKING_STARTED = datetime(2026, 7, 4, tzinfo=UTC)


# updated_at keeps its old value, because the app reads it as the time a run finished.
def complete_runs_from_before_status_tracking(apps, schema_editor):
    HogFlowBatchJob = apps.get_model("workflows", "HogFlowBatchJob")
    HogFlowBatchJob.objects.using(schema_editor.connection.alias).filter(
        status="queued", created_at__lt=STATUS_TRACKING_STARTED
    ).update(status="completed")


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0052_advent_calendar_answer"),
    ]

    operations = [
        migrations.RunPython(complete_runs_from_before_status_tracking, migrations.RunPython.noop, elidable=True),
    ]
