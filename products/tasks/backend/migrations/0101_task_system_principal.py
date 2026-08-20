from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0100_alter_loop_origin_product_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="system_principal",
            field=models.CharField(
                blank=True,
                choices=[("signals", "Signals")],
                editable=False,
                help_text="Trusted system principal that owns this task. Mutually exclusive with created_by.",
                max_length=32,
                null=True,
            ),
        ),
    ]
