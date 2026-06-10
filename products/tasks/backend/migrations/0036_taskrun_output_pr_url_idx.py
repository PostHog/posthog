import django.db.models.fields.json
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("tasks", "0035_task_origin_product_signals_scout"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="taskrun",
            index=models.Index(
                django.db.models.fields.json.KeyTransform("pr_url", "output"),
                name="task_run_output_pr_url_idx",
                condition=models.Q(output__pr_url__isnull=False),
            ),
        ),
    ]
