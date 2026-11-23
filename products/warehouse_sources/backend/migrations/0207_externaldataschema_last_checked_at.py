from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0206_externaldatadestinationdelivery"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="last_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
