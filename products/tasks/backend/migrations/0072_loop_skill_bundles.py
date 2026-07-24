from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0071_alter_origin_product_mcp_analytics"),
    ]

    operations = [
        migrations.AddField(
            model_name="loop",
            name="skill_bundles",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
