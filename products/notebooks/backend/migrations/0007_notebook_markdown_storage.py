from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notebooks", "0006_resourcenotebook_account_unique_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="notebook",
            name="content_storage",
            field=models.CharField(
                choices=[("json", "json"), ("markdown", "markdown")],
                db_default="json",
                default="json",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="notebook",
            name="markdown_content",
            field=models.TextField(blank=True, null=True),
        ),
    ]
