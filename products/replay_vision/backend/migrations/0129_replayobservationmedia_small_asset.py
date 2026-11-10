import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exports", "0015_exportedasset_session_index"),
        ("replay_vision", "0128_replayobservation_rlo_scanner_ranked_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayobservationmedia",
            name="small_asset",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="exports.exportedasset",
            ),
        ),
    ]
