from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0003_alter_mcpoauthstate_install_source"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="mcpoauthstate",
                    name="twig_callback_url",
                    field=models.TextField(blank=True, default="", db_column="twig_callback_url"),
                ),
                migrations.RenameField(
                    model_name="mcpoauthstate",
                    old_name="twig_callback_url",
                    new_name="posthog_code_callback_url",
                ),
            ],
            database_operations=[],
        ),
    ]
