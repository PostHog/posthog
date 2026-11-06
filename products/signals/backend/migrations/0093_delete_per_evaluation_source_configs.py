from django.db import migrations


def delete_per_evaluation_source_configs(apps, schema_editor):
    # One row per team that ever switched the source on, so a single filtered delete is enough.
    SignalSourceConfig = apps.get_model("signals", "SignalSourceConfig")
    SignalSourceConfig.objects.filter(source_product="llm_analytics", source_type="evaluation").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0092_remove_per_evaluation_signal_source"),
    ]

    operations = [
        # The rows carried the per-evaluation allowlist that gated one signal per evaluation run.
        # Nothing emits those any more, so the rows are dead config — and leaving them behind would
        # keep handing the API a source_type that is no longer a valid choice.
        migrations.RunPython(
            delete_per_evaluation_source_configs,
            reverse_code=migrations.RunPython.noop,
            elidable=True,
        ),
    ]
