from django.db import migrations, models

import products.wizard.backend.models


class Migration(migrations.Migration):
    dependencies = [
        ("wizard", "0011_rename_competes_with_to_alternative_to"),
    ]

    operations = [
        migrations.AlterField(
            model_name="wizardrunartifact",
            name="type",
            field=models.CharField(
                choices=products.wizard.backend.models.wizard_run_artifact_type_choices, max_length=30
            ),
        ),
    ]
