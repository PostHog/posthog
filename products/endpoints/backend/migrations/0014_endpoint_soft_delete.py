from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0013_add_endpointversion_is_active"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="endpoint",
            name="unique_team_endpoint_name",
        ),
        migrations.AddField(
            model_name="endpoint",
            name="deleted",
            field=models.BooleanField(blank=True, default=False, null=True),
        ),
        migrations.AddField(
            model_name="endpoint",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
