from django.db import migrations, models
from django.db.models import Count

from posthog.migration_helpers.concurrent_index import CreateIndexConcurrently


def dedupe_internal_sandbox_envs(apps, schema_editor):
    """Collapse pre-existing internal-env duplicates before the unique index is built.

    Concurrent runs could previously INSERT duplicate ``(team_id, name)`` internal envs; keep
    the oldest row per group and delete the rest so the partial unique index can be created.
    """
    SandboxEnvironment = apps.get_model("tasks", "SandboxEnvironment")
    duplicate_groups = (
        SandboxEnvironment.objects.filter(internal=True)
        .values("team_id", "name")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    for group in duplicate_groups:
        rows = list(
            SandboxEnvironment.objects.filter(internal=True, team_id=group["team_id"], name=group["name"]).order_by(
                "created_at", "id"
            )
        )
        for extra in rows[1:]:
            extra.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0041_taskrun_created_at_idx"),
    ]

    operations = [
        migrations.RunPython(dedupe_internal_sandbox_envs, noop_reverse),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="sandboxenvironment",
                    constraint=models.UniqueConstraint(
                        fields=["team", "name"],
                        condition=models.Q(internal=True),
                        name="unique_internal_sandbox_env_team_name",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_internal_sandbox_env_team_name",
                    table_name="posthog_sandbox_environment",
                    columns="(team_id, name)",
                    unique=True,
                    where='WHERE "internal"',
                ),
            ],
        ),
    ]
