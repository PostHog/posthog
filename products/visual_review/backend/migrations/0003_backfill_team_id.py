# Backfill team_id on child models from their parent Repo/Run.
# Separate from schema migration to avoid holding locks during DML.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0002_add_team_id_to_child_models"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                -- migration-analyzer: safe reason=visual_review tables are new and near-empty
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
