from django.db import migrations, models


class Migration(migrations.Migration):
    """Promote 0027's index to the new unique constraint and drop the old (scanner, session_id) one.

    `ADD CONSTRAINT ... UNIQUE USING INDEX` adopts the prebuilt index with no table scan. New-first,
    drop-second ordering (one transaction) so there is never a window without uniqueness. The old
    constraint's lookups are covered by the new index's (scanner_id, session_id) prefix.
    """

    dependencies = [
        ("replay_vision", "0027_observation_moment_unique_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="replayobservation",
                    name="replay_observation_unique_scanner_session",
                ),
                migrations.AddConstraint(
                    model_name="replayobservation",
                    constraint=models.UniqueConstraint(
                        fields=("scanner", "session_id", "moment_key"),
                        name="replay_observation_unique_scanner_session_moment",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "replay_vision_replayobservation"
                            ADD CONSTRAINT "replay_observation_unique_scanner_session_moment"
                            UNIQUE USING INDEX "replay_observation_unique_scanner_session_moment"; -- existing-table-constraint-ignore
                        ALTER TABLE "replay_vision_replayobservation"
                            DROP CONSTRAINT "replay_observation_unique_scanner_session";
                    """,
                    reverse_sql="""
                        ALTER TABLE "replay_vision_replayobservation"
                            ADD CONSTRAINT "replay_observation_unique_scanner_session"
                            UNIQUE ("scanner_id", "session_id"); -- existing-table-constraint-ignore
                        ALTER TABLE "replay_vision_replayobservation"
                            DROP CONSTRAINT "replay_observation_unique_scanner_session_moment";
                    """,
                ),
            ],
        ),
    ]
