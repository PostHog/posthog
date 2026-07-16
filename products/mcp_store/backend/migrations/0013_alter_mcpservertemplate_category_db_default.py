from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0012_alter_mcpserverinstallation_unique_together_and_more"),
    ]

    operations = [
        migrations.AlterField(
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
                db_default="dev",
                default="dev",
                max_length=20,
            ),
        ),
    ]
