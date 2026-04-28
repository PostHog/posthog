from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0011_errortrackingissueassignment_team_id_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="errortrackingsuppressionrule",
            name="bytecode",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="errortrackingsuppressionrule",
            name="disabled_data",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="errortrackingsuppressionrule",
            name="sampling_rate",
            field=models.FloatField(default=1.0),
        ),
    ]
