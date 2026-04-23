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
            batch_size=BATCH_SIZE,
            ignore_conflicts=True,
        )


def remove_default_evaluation_jobs(apps, schema_editor):
    """Reverse: delete the rows this migration created, identified by name + level."""
    ClusteringJob = apps.get_model("llm_analytics", "ClusteringJob")
    ClusteringJob.objects.filter(name=DEFAULT_NAME, analysis_level="evaluation").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analytics", "0028_clusteringjob_evaluation_level"),
    ]

    operations = [
        migrations.RunPython(
            create_default_evaluation_jobs,
            reverse_code=remove_default_evaluation_jobs,
        ),
    ]
