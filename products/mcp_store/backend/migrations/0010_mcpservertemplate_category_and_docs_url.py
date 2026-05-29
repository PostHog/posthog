from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0009_drop_mcpserver_created_by_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="mcpservertemplate",
            name="category",
            field=models.CharField(
                choices=[
                    ("business", "Business Operations"),
                    ("data", "Data & Analytics"),
                    ("design", "Design & Content"),
                    ("dev", "Developer Tools & APIs"),
                    ("infra", "Infrastructure"),
                    ("productivity", "Productivity & Collaboration"),
                ],
                default="dev",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="mcpservertemplate",
            name="docs_url",
            field=models.URLField(blank=True, default="", max_length=2048),
        ),
    ]
