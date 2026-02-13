from django.db import migrations


def move_api_keys_to_encrypted_storage(apps, schema_editor):
    MCPServerInstallation = apps.get_model("mcp_store", "MCPServerInstallation")

    for inst in MCPServerInstallation.objects.filter(
        server__auth_type="api_key",
    ).select_related("server"):
        config = inst.configuration or {}
        api_key = config.pop("api_key", None)
        if not api_key:
            continue

        sensitive = inst.sensitive_configuration or {}
        sensitive["api_key"] = api_key
        inst.configuration = config
        inst.sensitive_configuration = sensitive
        inst.save(update_fields=["configuration", "sensitive_configuration"])


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0007_add_is_signal_source"),
    ]

    operations = [
        migrations.RunPython(move_api_keys_to_encrypted_storage, migrations.RunPython.noop),
    ]
