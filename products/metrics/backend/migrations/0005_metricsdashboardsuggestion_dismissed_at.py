from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("metrics", "0004_metricrecordingrule"),
    ]

    operations = [
        migrations.AddField(
            model_name="metricsdashboardsuggestion",
            name="dismissed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When a user of the team dismissed the suggestion. The row stays, so that an analysis does not suggest the template to the team again.",
                null=True,
            ),
        ),
    ]
