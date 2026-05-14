from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orchestra", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="execution",
            name="team_id",
            field=models.BigIntegerField(db_index=True, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="task",
            name="team_id",
            field=models.BigIntegerField(db_index=True, default=0),
            preserve_default=False,
        ),
        migrations.RunSQL(
            sql="ALTER TABLE orchestra_event ADD COLUMN team_id BIGINT NOT NULL DEFAULT 0;"
            "CREATE INDEX idx_orch_event_team ON orchestra_event (team_id);",
            reverse_sql="DROP INDEX IF EXISTS idx_orch_event_team;ALTER TABLE orchestra_event DROP COLUMN team_id;",
        ),
    ]
