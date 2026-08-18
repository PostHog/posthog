from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0090_alter_origin_product_signals_chat")]

    operations = [
        migrations.AddField(
            model_name="task",
            name="pr_loop_enabled",
            field=models.BooleanField(
                blank=True,
                help_text=(
                    "Whether to keep watching this task's pull request after it opens, fixing CI and "
                    "replying to review comments. Null inherits the project default."
                ),
                null=True,
            ),
        ),
    ]
