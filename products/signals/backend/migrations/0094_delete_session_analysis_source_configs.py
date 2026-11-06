from django.db import migrations


def delete_session_analysis_configs(apps, schema_editor):
    """Drop the config rows for the retired session summarization signal source.

    Nothing has emitted against them since the feature was removed, and this release takes away the
    last surface that read them, so a team could neither turn the source off nor get anything from
    leaving it on. They also made `has_enabled_source` report true, which let onboarding read as
    finished on the strength of a source that produces nothing.

    Deleted in batches: this is roughly 1,800 rows across both regions, and one unbounded DELETE
    would hold row locks on the whole set for the length of the statement.
    """
    SignalSourceConfig = apps.get_model("signals", "SignalSourceConfig")
    doomed = SignalSourceConfig.objects.filter(
        source_product="session_replay",
        source_type="session_analysis_cluster",
    )
    while True:
        batch = list(doomed.values_list("id", flat=True)[:500])
        if not batch:
            break
        SignalSourceConfig.objects.filter(id__in=batch).delete()


class Migration(migrations.Migration):
    dependencies = [("signals", "0093_delete_per_evaluation_source_configs")]

    # Deleting rows nothing reads is not reversible in any meaningful sense: re-creating them would
    # invent config a team never asked for.
    operations = [
        migrations.RunPython(delete_session_analysis_configs, migrations.RunPython.noop, elidable=True),
    ]
