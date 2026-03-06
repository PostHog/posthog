from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0009_errortrackingissueassignment_team"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                UPDATE posthog_errortrackingissueassignment a
                SET team_id = i.team_id
                FROM posthog_errortrackingissue i
                WHERE a.issue_id = i.id
                  AND a.team_id IS NULL
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
