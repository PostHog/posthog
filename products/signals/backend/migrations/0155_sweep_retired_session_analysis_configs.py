from django.db import migrations


def delete_session_analysis_configs(apps, schema_editor):
    # No emitter produces `session_analysis_cluster`, so a config row for it can only make a team
    # read as watching a source that sends nothing. The type is retired under every product, so the
    # product is not part of the match. Few enough rows match that one delete is safe.
    SignalSourceConfig = apps.get_model("signals", "SignalSourceConfig")
    SignalSourceConfig.objects.filter(source_type="session_analysis_cluster").delete()


class Migration(migrations.Migration):
    dependencies = [("signals", "0154_backfill_report_actionability")]

    # Re-creating rows for a source that emits nothing would invent config a team never asked for.
    operations = [
        migrations.RunPython(delete_session_analysis_configs, migrations.RunPython.noop, elidable=True),
    ]
