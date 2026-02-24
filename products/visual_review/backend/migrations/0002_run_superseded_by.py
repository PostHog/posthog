# Generated manually

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("visual_review", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="run",
            name="superseded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="supersedes",
                to="visual_review.run",
            ),
        ),
    ]
