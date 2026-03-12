from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0009_suppression_rule_bytecode"),
    ]

    operations = [
        migrations.AddField(
            model_name="errortrackingsuppressionrule",
            name="sampling_rate",
            field=models.FloatField(default=1.0),
        ),
    ]
