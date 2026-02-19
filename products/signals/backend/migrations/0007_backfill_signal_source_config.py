from django.db import migrations


def convert_proactive_tasks_enabled(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    SignalSourceConfig = apps.get_model("signals", "SignalSourceConfig")

    for team in Team.objects.filter(proactive_tasks_enabled=True).only("id"):
        SignalSourceConfig.objects.get_or_create(
            team=team,
            source_type="session_analysis",
            defaults={"enabled": True, "config": {}},
        )


def reverse_convert(apps, schema_editor):
    SignalSourceConfig = apps.get_model("signals", "SignalSourceConfig")
    SignalSourceConfig.objects.filter(source_type="session_analysis").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0006_signal_source_config"),
    ]

    operations = [
        migrations.RunPython(convert_proactive_tasks_enabled, reverse_convert),
    ]
