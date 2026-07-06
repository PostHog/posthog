from django.db import migrations


def turn_on_scout_source(apps, schema_editor):
    """Land every team on scout findings surfacing to the inbox.

    The team-level "Surface findings in your inbox" toggle is being removed, so there's no
    longer a UI to turn it back on. The emit gate is now fail-open (absence of a row means on),
    which covers teams that never had a row. This flips the handful that explicitly toggled off
    in the old UI so they aren't stranded off — a team that really wants to opt out can still
    write an explicit disabled row via the MCP/API. One row per team, so a filtered UPDATE is cheap.
    """
    SignalSourceConfig = apps.get_model("signals", "SignalSourceConfig")
    SignalSourceConfig.objects.filter(
        source_product="signals_scout",
        source_type="cross_source_issue",
        enabled=False,
    ).update(enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0048_signalreportartefact_latest_index"),
    ]

    operations = [
        migrations.RunPython(turn_on_scout_source, migrations.RunPython.noop),
    ]
