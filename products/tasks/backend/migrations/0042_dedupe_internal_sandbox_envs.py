from django.db import migrations
from django.db.models import Count


def dedupe_internal_sandbox_envs(apps, schema_editor):
    """Collapse pre-existing internal-env duplicates before the unique index is built.

    Concurrent runs could previously INSERT duplicate ``(team_id, name)`` internal envs; keep
    the oldest row per group and delete the rest so the partial unique index added in the
    following migration can be created. Internal envs are few per team, so this is small.
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
    dependencies = [
        ("tasks", "0041_taskrun_created_at_idx"),
    ]

    operations = [
        migrations.RunPython(dedupe_internal_sandbox_envs, noop_reverse),
    ]
