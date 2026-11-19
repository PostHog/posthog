from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0045_errortrackingissuesummary"),
    ]

    operations = [
        migrations.AddField(
            model_name="errortrackingsuppressionrule",
            name="built_in_key",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="errortrackingsuppressionrule",
            name="built_in_hash",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
