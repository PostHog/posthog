from django.db import migrations


def delete_session_analysis_configs(apps, schema_editor):
    # 0094 cleared these rows while `session_analysis_cluster` was still a valid config choice, so a
    # team could write a fresh one back through the API afterwards. This release takes the choice
    # away, and the counting paths stop excluding the pair by name, so sweep whatever landed in
    # between. Filtered on the type alone: the API checked `source_product` and `source_type`
    # separately, so a write could pair the retired type with any product, and the counts read every
    # such row as a live source. Expected to match nothing: one filtered delete is enough.
    SignalSourceConfig = apps.get_model("signals", "SignalSourceConfig")
    SignalSourceConfig.objects.filter(source_type="session_analysis_cluster").delete()


class Migration(migrations.Migration):
    dependencies = [("signals", "0135_signalreportcheck")]

    # Re-creating rows for a source that emits nothing would invent config a team never asked for.
    operations = [
        migrations.RunPython(delete_session_analysis_configs, migrations.RunPython.noop, elidable=True),
    ]
