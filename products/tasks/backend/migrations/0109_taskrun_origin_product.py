from django.db import migrations, models

import products.tasks.backend.models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0108_channel_auto_archive_after_days"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskrun",
            name="origin_product",
            field=models.CharField(
                blank=True,
                choices=products.tasks.backend.models.task_origin_product_choices,
                default="",
                db_default="",
                max_length=20,
            ),
        ),
    ]
