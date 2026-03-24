# Generated manually — adds denormalized team_id to child models
# and backfills existing rows from the parent Repo/Run.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="artifact",
            name="team_id",
            field=models.BigIntegerField(db_index=True, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="run",
            name="team_id",
            field=models.BigIntegerField(db_index=True, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="runsnapshot",
            name="team_id",
            field=models.BigIntegerField(db_index=True, default=0),
            preserve_default=False,
        ),
        # Backfill existing rows
        migrations.RunSQL(
            sql="""
                UPDATE visual_review_run
                SET team_id = visual_review_repo.team_id
                FROM visual_review_repo
                WHERE visual_review_run.repo_id = visual_review_repo.id
                  AND visual_review_run.team_id = 0;

                UPDATE visual_review_runsnapshot
                SET team_id = visual_review_run.team_id
                FROM visual_review_run
                WHERE visual_review_runsnapshot.run_id = visual_review_run.id
                  AND visual_review_runsnapshot.team_id = 0;

                UPDATE visual_review_artifact
                SET team_id = visual_review_repo.team_id
                FROM visual_review_repo
                WHERE visual_review_artifact.repo_id = visual_review_repo.id
                  AND visual_review_artifact.team_id = 0;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
