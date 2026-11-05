from django.db import migrations, models

import products.wizard.backend.models


class Migration(migrations.Migration):
    dependencies = [("wizard", "0001_squash_2026_11_02_initial")]

    operations = [
        migrations.AlterField(
            model_name="wizardrunartifact",
            name="type",
            field=models.CharField(
                choices=products.wizard.backend.models.wizard_run_artifact_type_choices,
                max_length=30,
            ),
        ),
    ]
