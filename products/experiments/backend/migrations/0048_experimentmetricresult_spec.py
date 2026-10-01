from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Nullable columns without a default, so ADD COLUMN changes only the catalog and rewrites no rows.
    """

    dependencies = [
        ("experiments", "0047_experimentmetricresult_key_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="experimentmetricresult",
            name="spec",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="experimentmetricresult",
            name="spec_version",
            field=models.SmallIntegerField(blank=True, null=True),
        ),
    ]
