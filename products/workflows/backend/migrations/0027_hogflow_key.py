from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0026_workflowproposal"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflow",
            name="key",
            field=models.CharField(
                blank=True,
                help_text="Client-chosen identifier, unique within this environment. Set only when creating a workflow. Filter the list with `?key=`. Letters, numbers, hyphens (-) and underscores (_) only.",
                max_length=400,
                null=True,
            ),
        ),
    ]
