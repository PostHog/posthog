from django.db import migrations


def normalize_icon_keys(apps, schema_editor):
    MCPServerTemplate = apps.get_model("mcp_store", "MCPServerTemplate")
    for template in MCPServerTemplate.objects.iterator():
        normalized = "_".join((template.icon_key or "").lower().split())
        if normalized != template.icon_key:
            template.icon_key = normalized
            template.save(update_fields=["icon_key"])


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0010_mcpservertemplate_category_and_docs_url"),
    ]

    operations = [
        migrations.RunPython(normalize_icon_keys, reverse_code=migrations.RunPython.noop),
    ]
