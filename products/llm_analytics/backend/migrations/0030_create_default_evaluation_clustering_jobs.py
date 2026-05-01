from django.db import migrations

BATCH_SIZE = 1000
DEFAULT_NAME = "Default - evaluations"


def create_default_evaluation_jobs(apps, schema_editor):
    """Create a "Default - evaluations" ClusteringJob for every team that already has
    any ClusteringJob row. Mirrors the precedent set by migration 0018, which created
    "Default - traces" and "Default - generations" rows for teams with a ClusteringConfig.

    Scope: teams that have engaged with clustering in any way (trace, generation, or
    evaluation). This backfills team 2 and similar teams that have trace/gen jobs but
    no evaluation job yet, so the eval coordinator has a real row to dispatch against.

    Idempotent via the unique (team, name) constraint: re-running the migration (or
    running it after a team already has a "Default - evaluations" row) is a no-op for
    that team thanks to ignore_conflicts=True.
    """
    ClusteringJob = apps.get_model("llm_analytics", "ClusteringJob")

    team_ids = list(ClusteringJob.objects.values_list("team_id", flat=True).distinct())
    if not team_ids:
        return

    for start in range(0, len(team_ids), BATCH_SIZE):
        batch = team_ids[start : start + BATCH_SIZE]
        ClusteringJob.objects.bulk_create(
            [
                ClusteringJob(
                    team_id=tid,
                    name=DEFAULT_NAME,
                    analysis_level="evaluation",
                    event_filters=[],
                    enabled=True,
                )
                for tid in batch
            ],
            ignore_conflicts=True,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0029_add_azure_openai_provider"),
    ]

    operations = [
        # reverse_code=noop matches migration 0018's precedent. Forward uses
        # ignore_conflicts=True, so a name+level filter on reverse can't tell
        # rows this migration inserted apart from rows inserted by future paths
        # (e.g. an automated post_save signal on Team, or admin tooling that
        # pre-seeds default jobs — neither exists today, but flagging because
        # if they're added later, a naive reverse would be data-destructive).
        migrations.RunPython(
            create_default_evaluation_jobs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
