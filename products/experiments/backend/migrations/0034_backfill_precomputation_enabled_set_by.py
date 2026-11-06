from django.db import migrations


def backfill_manual(apps, schema_editor):
    # Every team enabled so far was enabled by a human via the staff endpoint.
    # Tiny update: only teams on the precomputation allowlist have this set.
    TeamExperimentsConfig = apps.get_model("experiments", "TeamExperimentsConfig")
    TeamExperimentsConfig.objects.filter(experiment_precomputation_enabled=True).update(
        precomputation_enabled_set_by="manual"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0033_teamexperimentsconfig_precomputation_enabled_set_by"),
    ]

    operations = [
        migrations.RunPython(backfill_manual, migrations.RunPython.noop, elidable=True),
    ]
