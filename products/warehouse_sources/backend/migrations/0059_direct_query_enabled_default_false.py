from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0058_externaldataschemaoomevent")]

    operations = [
        migrations.AlterField(
            model_name="externaldatasource",
            name="direct_query_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
