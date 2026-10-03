from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0110_signalreportartefact_team_type_recent_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="signals_researched",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
