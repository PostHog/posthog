from django.db import migrations, models

import products.warehouse_sources.backend.models.external_data_destination


class Migration(migrations.Migration):
    dependencies = [("warehouse_sources", "0167_externaldatajob_running_idx")]

    operations = [
        migrations.AlterField(
            model_name="externaldatadestination",
            name="type",
            field=models.CharField(
                choices=products.warehouse_sources.backend.models.external_data_destination.external_data_destination_type_choices,
                max_length=64,
            ),
        ),
    ]
