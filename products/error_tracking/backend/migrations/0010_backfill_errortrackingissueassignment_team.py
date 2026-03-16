from django.db import migrations


def backfill_team_id(apps, schema_editor):
    ErrorTrackingIssueAssignment = apps.get_model("error_tracking", "ErrorTrackingIssueAssignment")
    batch_size = 100

    while True:
        ids = list(
            ErrorTrackingIssueAssignment.objects.filter(team_id__isnull=True).values_list("id", flat=True)[:batch_size]
        )
        if not ids:
            break

        batch = list(ErrorTrackingIssueAssignment.objects.filter(id__in=ids).select_related("issue"))
        for assignment in batch:
            assignment.team_id = assignment.issue.team_id

        ErrorTrackingIssueAssignment.objects.bulk_update(batch, ["team_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0009_errortrackingissueassignment_team"),
    ]

    operations = [
        migrations.RunPython(backfill_team_id, reverse_code=migrations.RunPython.noop),
    ]
